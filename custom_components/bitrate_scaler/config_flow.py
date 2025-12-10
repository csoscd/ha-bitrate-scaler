
from __future__ import annotations
import hashlib
from typing import Any, Dict, List, Optional

import voluptuous as vol
from homeassistant import config_entries
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


def _sources_selector(default: Optional[List[str]] = None):
    """EntitySelector nur für sensor.*.rx und sensor.*.tx."""
    return sel.EntitySelector(
        sel.EntitySelectorConfig(
            domain="sensor",
            multiple=True,
            filter=[
                {"entity_id": "sensor.*.rx"},
                {"entity_id": "sensor.*.tx"},
            ]
        )
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
        vol.Required("sources"): _sources_selector(),
    }
)


class BitrateScalerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config-Flow für Bitrate Scaler."""
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

        # Deterministische unique_id aus Quellenliste
        uid_base = ",".join(sorted(sources)).encode("utf-8")
        unique_id = hashlib.sha1(uid_base).hexdigest()
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        # Initial speichern, Aliases leer
        data = {
            "mode": user_input["mode"],
            "precision": user_input["precision"],
            "thresholds": {
                "kbps": user_input["threshold_kbit"],
                "mbps": user_input["threshold_mbit"],
            },
            "sources": sources,
            "aliases": {},  # später im Options-Flow pflegbar
        }

        title = f"Bitrate Scaler ({len(sources)} Quellen)"
        return self.async_create_entry(title=title, data=data)

    async def async_step_import(self, user_input: Dict[str, Any]):
        """Optionaler YAML-Import."""
        return await self.async_step_user(user_input)


class BitrateScalerOptionsFlow(config_entries.OptionsFlow):
    """Options-Flow mit Alias-Schritt."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        self._tmp_sources: List[str] = []
        self._tmp_mode: str = DEFAULT_MODE
        self._tmp_precision: int = DEFAULT_PRECISION
        self._tmp_kbit: int = DEFAULT_KBIT_THRESHOLD
        self._tmp_mbit: int = DEFAULT_MBIT_THRESHOLD

    async def async_step_init(self, user_input: Dict[str, Any] | None = None):
        """Erster Options-Schritt: Modus/Präzision/Schwellen + Quellen wählen."""
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
                vol.Required("sources", default=sources): _sources_selector(),
            }
        )

        if user_input is None:
            return self.async_show_form(step_id="init", data_schema=options_schema)

        # Temporär puffern und in nächsten Schritt (Aliases)
        self._tmp_mode = user_input["mode"]
        self._tmp_precision = user_input["precision"]
        self._tmp_kbit = user_input["threshold_kbit"]
        self._tmp_mbit = user_input["threshold_mbit"]
        self._tmp_sources = user_input.get("sources", [])

        if not self._tmp_sources:
            # No sources -> zurück zur init-Form
            return self.async_show_form(
                step_id="init", data_schema=options_schema, errors={"sources": "no_sources"}
            )

        return await self.async_step_aliases()

    async def async_step_aliases(self, user_input: Dict[str, Any] | None = None):
        """Zweiter Options-Schritt: Alias-Felder pro selektierter Quelle."""
        data = self._entry.data
        existing_aliases: Dict[str, str] = data.get("aliases", {})

        # Dynamische Felder: alias_<entity_id> für jede selektierte Quelle
        alias_schema_dict: Dict[Any, Any] = {}
        for src in self._tmp_sources:
            default_alias = existing_aliases.get(src) or src
            alias_schema_dict[vol.Optional(f"alias_{src}", default=default_alias)] = sel.TextSelector()

        alias_schema = vol.Schema(alias_schema_dict)

        if user_input is None:
            return self.async_show_form(step_id="aliases", data_schema=alias_schema)

        # Mapping einsammeln
        aliases: Dict[str, str] = {}
        for src in self._tmp_sources:
            aliases[src] = user_input.get(f"alias_{src}", src)

        # ConfigEntry-Daten aktualisieren
        new_data = {
            **self._entry.data,
            "mode": self._tmp_mode,
            "precision": self._tmp_precision,
            "thresholds": {
                "kbps": self._tmp_kbit,
                "mbps": self._tmp_mbit,
            },
            "sources": self._tmp_sources,
            "aliases": aliases,
        }
        self.hass.config_entries.async_update_entry(self._entry, data=new_data)
        return self.async_create_entry(title="", data={})
