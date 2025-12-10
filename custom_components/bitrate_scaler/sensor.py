
from __future__ import annotations
import math
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    DEFAULT_KBIT_THRESHOLD,
    DEFAULT_MBIT_THRESHOLD,
    DEFAULT_MODE,
    DEFAULT_PRECISION,
    MODE_DYNAMIC_UNIT,
    MODE_FIXED_WITH_ATTR,
)

try:
    from homeassistant.components.sensor import SensorDeviceClass
    HAS_DEVICE_CLASS = True
except Exception:
    HAS_DEVICE_CLASS = False


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a ConfigEntry."""
    data = hass.data[DOMAIN][entry.entry_id]
    sources: List[str] = data.get("sources", [])
    mode: str = data.get("mode", DEFAULT_MODE)
    precision: int = int(data.get("precision", DEFAULT_PRECISION))
    thresholds = data.get("thresholds", {})
    kb_thr: float = float(thresholds.get("kbps", DEFAULT_KBIT_THRESHOLD))
    mb_thr: float = float(thresholds.get("mbps", DEFAULT_MBIT_THRESHOLD))

    entities: List[BitrateScalerSensor] = []
    for src in sources:
        entities.append(
            BitrateScalerSensor(
                hass=hass,
                entry_id=entry.entry_id,
                source_entity_id=src,
                name_override=None,
                mode=mode,
                precision=precision,
                kbit_threshold=kb_thr,
                mbit_threshold=mb_thr,
            )
        )

    if entities:
        async_add_entities(entities)


class BitrateScalerSensor(SensorEntity):
    """Skaliert bit/s auf kbit/s bzw. Mbit/s (Anzeige)."""

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

        self._display_unit = "bit/s"
        self._display_value = None

        self._attr_unique_id = f"{DOMAIN}:{entry_id}:{self._source}"
        self._attr_name = self._derive_name()
        if HAS_DEVICE_CLASS:
            self._attr_device_class = SensorDeviceClass.DATA_RATE

        # Fester State‑Unit in FIXED‑Modus
        if self._mode == MODE_FIXED_WITH_ATTR:
            self._attr_unit_of_measurement = "bit/s"

    def _derive_name(self) -> str:
        if self._name_override:
            return self._name_override
        src_state = self.hass.states.get(self._source)
        if src_state:
            fn = src_state.attributes.get("friendly_name")
            if fn:
                return f"{fn} (skaliert)"
        return f"{self._source} (skaliert)"

    async def async_added_to_hass(self) -> None:
        # Auf State‑Änderungen der Quelle reagieren
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._source], self._handle_source_state_change
            )
        )

    @callback
    def _handle_source_state_change(self, event) -> None:
        self.async_schedule_update_ha_state(True)

    @property
    def available(self) -> bool:
        src_state = self.hass.states.get(self._source)
        if not src_state:
            return False
        try:
            float(src_state.state)
            return True
        except Exception:
            return False

    def _scale(self, raw_bits: float) -> tuple[float, str]:
        if math.isnan(raw_bits):
            return (float("nan"), "bit/s")
        if raw_bits >= self._mb_thr:
            return (raw_bits / 1_000_000.0, "Mbit/s")
        if raw_bits >= self._kb_thr:
            return (raw_bits / 1_000.0, "kbit/s")
        return (raw_bits, "bit/s")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {
            "source_entity_id": self._source,
            "display_unit": self._display_unit,
        }
        if self._display_value is not None:
            attrs["display_value_str"] = f"{self._display_value:.{self._precision}f} {self._display_unit}"
        return attrs

    @property
    def state(self) -> Any:
        src_state = self.hass.states.get(self._source)
        if not src_state:
            return None
        try:
            raw = float(src_state.state)
        except Exception:
            return None

        scaled_val, scaled_unit = self._scale(raw)
        self._display_unit = scaled_unit
        self._display_value = scaled_val

        if self._mode == MODE_DYNAMIC_UNIT:
            self._attr_unit_of_measurement = scaled_unit
            return round(scaled_val, self._precision)
        else:
            self._attr_unit_of_measurement = "bit/s"
            return round(raw, self._precision)
