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

# -----------------------------
# Hilfsfunktionen für Auswahl
# -----------------------------
def _gather_matching_entities(hass: HomeAssistant) -> List[str]:
    """
    Liefert alle entity_ids, die dem Muster sensor.*.rx bzw. sensor.*.tx entsprechen.
    Nutzt das State-Register (kein Polling).
    """
    matches: List[str] = []
    for st in hass.states.async_all():
        eid = st.entity_id
        if not eid.startswith("sensor."):
            continue
        if eid.endswith(".rx") or eid.endswith(".tx"):
            matches.append(eid)
    return sorted(matches)


def _build_sources_selector(hass: HomeAssistant) -> sel.EntitySelector:
    """
    Baut einen EntitySelector, der ausschließlich die dynamisch ermittelten
    'sensor.*.rx' / 'sensor.*.tx' zur Auswahl anbietet.
    """
    candidates = _gather_matching_entities(hass)
    return sel.EntitySelector(
        sel.EntitySelectorConfig(
            domain="sensor",
            multiple=True,
            include_entities=candidates,  # gültiger Key in aktuellen HA-Versionen
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


# -----------------------------
# Config-Flow (Ersteinrichtung)
# -----------------------------
class BitrateScalerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config-Flow für Bitrate Scaler."""
    VERSION = 1

    async def async_step_user(self, user_input: Dict[str, Any] | None = None):
        errors: Dict[str, str] = {}

        # Prüfen, ob überhaupt passende Entitäten vorhanden sind
        candidates = _gather_matching_entities(self.hass)
        schema = _user_schema(self.hass)

        if not candidates:
            # Formular anzeigen, aber mit Fehlerhinweis
            errors["sources"] = "no_matching_entities"

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors=errors,
            )

        sources: List[str] = user_input.get("sources") or []
        if not sources:
            errors["sources"] = "no_sources"
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors=errors,
            )

        # Deterministische unique_id aus Quellenliste
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
            "sources": sources,
            "aliases": {},  # Alias-Mapping wird später im Options-Flow gepflegt
        }

        title = f"Bitrate Scaler ({len(sources)} Quellen)"
        return self.async_create_entry(title=title, data=data)

    async def async_step_import(self, user_input: Dict[str, Any]):
        """Optionaler YAML-Import: re-use der user-Logik."""
        return await self.async_step_user(user_input)


# -----------------------------
# Options-Flow (Nachpflege)
# -----------------------------
class BitrateScalerOptionsFlow(config_entries.OptionsFlow):
    """Options-Flow: Modus/Schwellen/Quellen + Alias-Namen je Quelle."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        # Temporäre Puffer für Schritt 1
        self._tmp_sources: List[str] = []
        self._tmp_mode: str = DEFAULT_MODE
        self._tmp_precision: int = DEFAULT_PRECISION
        self._tmp_kbit: int = DEFAULT_KBIT_THRESHOLD
        self._tmp_mbit: int = DEFAULT_MBIT_THRESHOLD

    async def async_step_init(self, user_input: Dict[str, Any] | None = None):
        """Schritt 1: Modus/Präzision/Schwellen + (neu) Quellen auswählen."""
        data = self._entry.data
        mode = data.get("mode", DEFAULT_MODE)
        precision = data.get("precision", DEFAULT_PRECISION)
        thresholds = data.get("thresholds", {})
        kbit = thresholds.get("kbps", DEFAULT_KBIT_THRESHOLD)
        mbit = thresholds.get("mbps", DEFAULT_MBIT_THRESHOLD)
        sources = data.get("sources", [])

        selector = _build_sources_selector(self.hass)

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
                vol.Required("sources", default=sources): selector,
            }
        )

        if user_input is None:
            # Fehlerhinweis, wenn aktuell keine passenden Entitäten existieren
            if not _gather_matching_entities(self.hass):
                return self.async_show_form(
                    step_id="init",
                    data_schema=options_schema,
                    errors={"sources": "no_matching_entities"},
                )
            return self.async_show_form(step_id="init", data_schema=options_schema)

        # Werte puffern, weiter zu Alias-Schritt
        self._tmp_mode = user_input["mode"]
        self._tmp_precision = user_input["precision"]
        self._tmp_kbit = user_input["threshold_kbit"]
        self._tmp_mbit = user_input["threshold_mbit"]
        self._tmp_sources = user_input.get("sources", [])

        if not self._tmp_sources:
            return self.async_show_form(
                step_id="init", data_schema=options_schema, errors={"sources": "no_sources"}
            )

        return await self.async_step_aliases()

    async def async_step_aliases(self, user_input: Dict[str, Any] | None = None):
        """Schritt 2: Alias-Felder (Text) pro selektierter Quelle."""
        data = self._entry.data
        existing_aliases: Dict[str, str] = data.get("aliases", {})

        # Dynamische Felder: alias_<entity_id>
        alias_schema_dict: Dict[Any, Any] = {}
        for src in self._tmp_sources:
            default_alias = existing_aliases.get(src) or src
            alias_schema_dict[vol.Optional(f"alias_{src}", default=default_alias)] = sel.TextSelector()

        alias_schema = vol.Schema(alias_schema_dict)

        if user_input is None:
            return self.async_show_form(step_id="aliases", data_schema=alias_schema)

        # Alias-Mapping einsammeln
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
