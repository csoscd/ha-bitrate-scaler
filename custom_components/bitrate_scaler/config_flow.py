
# custom_components/bitrate_scaler/config_flow.py
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector as sel

from .const import (
    DOMAIN,
    DEFAULT_MODE,
    DEFAULT_PRECISION,
    DEFAULT_KBIT_THRESHOLD,
    DEFAULT_MBIT_THRESHOLD,
    MODE_DYNAMIC_UNIT,
    MODE_FIXED_WITH_ATTR,
)


def _gather_matching_entities(hass: HomeAssistant) -> List[str]:
    """
    Liefert alle entity_ids, die dem Muster sensor.*.rx bzw. sensor.*.tx entsprechen.
    Nutzt das State-Register (kein Polling).
    """
    matches: List[str] = []
    for st in hass.states.async_all():
        eid = st.entity_id
        # Wir filtern nur sensor.* und lassen explizit .rx / .tx durch
        if not eid.startswith("sensor."):
            continue
        if eid.endswith(".rx") or eid.endswith(".tx"):
            matches.append(eid)
    return sorted(matches)


def _build_sources_selector(hass: HomeAssistant, default: Optional[List[str]] = None) -> sel.EntitySelector:
    """
    Baut einen EntitySelector, der ausschließlich die dynamisch ermittelten
    'sensor.*.rx' / 'sensor.*.tx' zur Auswahl anbietet.
    """
    candidates = _gather_matching_entities(hass)
    return sel.EntitySelector(
        sel.EntitySelectorConfig(
            domain="sensor",
            multiple=True,
            include_entities=candidates,  # gültiger Key im aktuellen HA
        )
    )


def _user_schema(hass: HomeAssistant) -> vol.Schema:
    """Erst-Setup-Formular (Config-Flow) mit dynamischem EntitySelector."""
    return vol.Schema(
        {
            vol.Required("mode", default=DEFAULT_MODE): vol.In(
                [MODE_FIXED_WITH_ATTR, MODE_DYNAMIC_UNIT]
            ),
            vol.Required("precision", default=DEFAULT_PRECISION): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=4)
            ),
            vol.Required("threshold_kbit", default=DEFAULT_KBIT_THRESHOLD): vol.All(
                vol.Coerce(int), vol.Range(min=1)
            ),
            vol.Required("threshold_mbit", default=DEFAULT_MBIT_THRESHOLD): vol.All(
                vol.Coerce(int), vol.Range(min=1000)
            ),
            vol.Required("sources"): _build_sources_selector(hass),
        }
    )


class BitrateScalerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config-Flow für Bitrate Scaler."""
    VERSION = 1

    async def async_step_user(self, user_input: Dict[str, Any] | None = None):
