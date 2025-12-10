# custom_components/bitrate_scaler/sensor.py
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from homeassistant.components.sensor import SensorEntity

# Optional: Geräteeigenschaften — kompatibel zu unterschiedlichen HA-Versionen
try:
    from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
    HAS_DEVICE_CLASS = True
except Exception:
    HAS_DEVICE_CLASS = False
    SensorDeviceClass = None  # type: ignore
    SensorStateClass = None  # type: ignore

from .const import (
    DOMAIN,
    DEFAULT_KBIT_THRESHOLD,
    DEFAULT_MBIT_THRESHOLD,
    DEFAULT_MODE,
    DEFAULT_PRECISION,
    MODE_DYNAMIC_UNIT,
    MODE_FIXED_WITH_ATTR,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Bitrate Scaler sensors from a ConfigEntry."""
    data = hass.data[DOMAIN][entry.entry_id]

    sources: List[str] = data.get("sources", [])
    mode: str = data.get("mode", DEFAULT_MODE)
    precision: int = int(data.get("precision", DEFAULT_PRECISION))
    thresholds: Dict[str, Any] = data.get("thresholds", {})
    kb_thr: float = float(thresholds.get("kbps", DEFAULT_KBIT_THRESHOLD))
    mb_thr: float = float(thresholds.get("mbps", DEFAULT_MBIT_THRESHOLD))
    aliases: Dict[str, str] = data.get("aliases", {})

    entities: List[BitrateScalerSensor] = []
    for src in sources:
        name_override = aliases.get(src)
        entities.append(
            BitrateScalerSensor(
                hass=hass,
                entry_id=entry.entry_id,
                source_entity_id=src,
                name_override=name_override,
                mode=mode,
                precision=precision,
                kbit_threshold=kb_thr,
                mbit_threshold=mb_thr,
            )
        )

    if entities:
        async_add_entities(entities)


class BitrateScalerSensor(SensorEntity):
    """Derived sensor that scales bit/s to kbit/s or Mbit/s for display."""

    _attr_should_poll = False  # Event-basiert, kein Polling

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        source_entity_id: str,
        name_override: Optional[str],
        mode: str,
        precision: int,
        kbit_threshold: float,
        mbit_threshold: float,
    ) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._source = source_entity_id
        self._name_override = name_override
        self._mode = mode
        self._precision = precision
        self._kb_thr = kbit_threshold
        self._mb_thr = mbit_threshold

        # Anzeige-Cache
        self._display_unit: str = "bit/s"
        self._display_value: Optional[float] = None

        # Identität
        self._attr_unique_id = f"{DOMAIN}:{entry_id}:{self._source}"
        self._attr_name = self._derive_name()

        # Geräteeigenschaften (falls verfügbar)
        if HAS_DEVICE_CLASS:
            self._attr_device_class = SensorDeviceClass.DATA_RATE
            self._attr_state_class = SensorStateClass.MEASUREMENT  # type: ignore

        # Einheit im FIXED-Modus (für stabile Historie)
        if self._mode == MODE_FIXED_WITH_ATTR:
            self._attr_native_unit_of_measurement = "bit/s"

        # Icon als kleiner Hinweis (optional)
        self._attr_icon = "mdi:speedometer"

    # ---------------------------
    # Lifecycle & Event Handling
    # ---------------------------

    async def async_added_to_hass(self) -> None:
        """Register for source state changes."""
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._source], self._handle_source_state_change
            )
        )
        # Erste Aktualisierung
        self.async_write_ha_state()

    @callback
    def _handle_source_state_change(self, event) -> None:
        """Handle source state updates by scheduling HA state update."""
        self.async_schedule_update_ha_state(True)

    # ---------------------------
    # Basic Properties
    # ---------------------------

    def _derive_name(self) -> str:
        """Build a human-friendly name using alias or source friendly_name."""
        if self._name_override:
            return f"{self._name_override} (skaliert)"
        src_state = self.hass.states.get(self._source)
        if src_state:
            friendly = src_state.attributes.get("friendly_name")
            if friendly:
                return f"{friendly} (skaliert)"
        return f"{self._source} (skaliert)"

    @property
    def available(self) -> bool:
        """Entity is available only if the source provides a numeric state."""
        src_state = self.hass.states.get(self._source)
        if not src_state:
            return False
        try:
            float(src_state.state)
            return True
        except Exception:
            return False

    # ---------------------------
    # Scaling Logic
    # ---------------------------

    def _scale(self, raw_bits: float) -> tuple[float, str]:
        """
        Scale bit/s to kbit/s or Mbit/s.
        Thresholds are inclusive for the upper tiers.
        """
        if math.isnan(raw_bits):
            return (float("nan"), "bit/s")
        if raw_bits >= self._mb_thr:
            return (raw_bits / 1_000_000.0, "Mbit/s")
        if raw_bits >= self._kb_thr:
            return (raw_bits / 1_000.0, "kbit/s")
        return (raw_bits, "bit/s")

    # ---------------------------
    # State & Attributes (native)
    # ---------------------------

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Expose display info & source metadata."""
        attrs: Dict[str, Any] = {
            "source_entity_id": self._source,
            "display_unit": self._display_unit,
            "mode": self._mode,
            "precision": self._precision,
            "kb_threshold_bits": self._kb_thr,
            "mb_threshold_bits": self._mb_thr,
        }
        if self._display_value is not None and not math.isnan(self._display_value):
            attrs["display_value_str"] = f"{self._display_value:.{self._precision}f} {self._display_unit}"
        return attrs

    @property
    def native_value(self) -> StateType:
        """
        Return the numeric value depending on mode:
        - dynamic_unit: scaled number (k/Mbit/s)
        - fixed_unit_with_attribute: raw bits/s
        """
        src_state = self.hass.states.get(self._source)
        if not src_state:
            return None

        # Nicht-numerisch -> unavailable/None
        try:
            raw = float(src_state.state)
        except Exception:
            self._display_value = None
            self._display_unit = "bit/s"
            return None

        scaled_val, scaled_unit = self._scale(raw)
        self._display_value = scaled_val
        self._display_unit = scaled_unit

        if self._mode == MODE_DYNAMIC_UNIT:
            # Liefere den skalierten Wert als State
            return round(scaled_val, self._precision)

        # FIXED: Liefere den Rohwert in bit/s (stabile Historie)
        return round(raw, self._precision)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """
        Unit for the native_value:
        - dynamic_unit: scaled unit (bit/s, kbit/s, Mbit/s)
        - fixed_unit_with_attribute: "bit/s"
        """
        if self._mode == MODE_DYNAMIC_UNIT:
            # Einheit wechselt abhängig vom zuletzt skalierten Wert
            return self._display_unit
        # FIXED
        return "bit/s"

    # ---------------------------
    # Device Info (optional)
    # ---------------------------

    @property
    def device_info(self) -> Dict[str, Any]:
        """Group all derived sensors under one virtual device."""
        return {
            "identifiers": {(DOMAIN, "bitrate_scaler")},
            "name": "Bitrate Scaler",
            "manufacturer": "Custom",
            "model": "Bitrate Scaler Helper",
        }
