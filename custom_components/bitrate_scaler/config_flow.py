
from __future__ import annotations
import hashlib
from typing import Any, Dict, List

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

STEP_USER_SCHEMA = vol.Schema(
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
        # Mehrfachauswahl von Sensor-Entitäten (domain="sensor")
        vol.Required("sources"): sel.EntitySelector(
            sel.EntitySelectorConfig(domain="sensor", multiple=True)
        ),
    }
)

class BitrateScalerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow für Bitrate Scaler."""
    VERSION = 1

    async def async_step_user(self, user_input: Dict[str, Any] | None = None):
        errors: Dict[str, str] = {}
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_SCHEMA,
                errors=errors,
            )

        sources: List[str] = user_input.get("sources") or []
        if not sources:
            errors["sources"] = "no_sources"
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_SCHEMA,
                errors=errors,
            )

        # Unique ID aus der Source-Liste deterministisch erzeugen (damit gleiche Auswahl nicht dupliziert wird)
        uid_base = ",".join(sorted(sources)).encode("utf-8")
        unique_id = hashlib.sha1(uid_base).hexdigest()

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        data = {
            "mode": user_input["mode"],
            "precision": user_input["precision"],
            "thresholds": {
                "kbps": user_input["threshold_kbit"],
                "mbps": user_input["threshold_mbit"],
            },
            "sources": sources,  # Liste von entity_id Strings
        }

        # Titel in der Geräte-&-Dienste-Ansicht
        title = f"Bitrate Scaler ({len(sources)} Quellen)"
        return self.async_create_entry(title=title, data=data)

    async def async_step_import(self, user_input: Dict[str, Any]):
        """Unterstützung für YAML-Import (optional)."""
        return await self.async_step_user(user_input)


class BitrateScalerOptionsFlow(config_entries.OptionsFlow):
    """Options-Flow: nachträgliche Änderungen über die UI."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: Dict[str, Any] | None = None):
        if user_input is not None:
            # Modus/Präzision/Schwellen & Quellen aktualisieren
            new_data = {
                **self._entry.data,
                "mode": user_input["mode"],
                "precision": user_input["precision"],
                "thresholds": {
                    "kbps": user_input["threshold_kbit"],
                    "mbps": user_input["threshold_mbit"],
                },
                "sources": user_input["sources"],
            }
            # Data der ConfigEntry aktualisieren
            self.hass.config_entries.async_update_entry(self._entry, data=new_data)
            return self.async_create_entry(title="", data={})

        # Bestehende Werte als Defaults setzen
        data = self._entry.data
        mode = data.get("mode", DEFAULT_MODE)
        precision = data.get("precision", DEFAULT_PRECISION)
        thresholds = data.get("thresholds", {})
        kbit = thresholds.get("kbps", DEFAULT_KBIT_THRESHOLD)
        mbit = thresholds.get("mbps", DEFAULT_MBIT_THRESHOLD)
        sources = data.get("sources", [])

        options_schema = vol.Schema(
            {
                vol.Required("mode", default=mode): vol.In(
                    [MODE_FIXED_WITH_ATTR, MODE_DYNAMIC_UNIT]
                ),
                vol.Required("precision", default=precision): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=4)
                ),
                vol.Required("threshold_kbit", default=kbit): vol.All(
                    vol.Coerce(int), vol.Range(min=1)
                ),
                vol.Required("threshold_mbit", default=mbit): vol.All(
                    vol.Coerce(int), vol.Range(min=1000)
                ),
                vol.Required("sources", default=sources): sel.EntitySelector(
                    sel.EntitySelectorConfig(domain="sensor", multiple=True)
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )

def _get_options_flow(config_entry: config_entries.ConfigEntry):
    return BitrateScalerOptionsFlow(config_entry)
