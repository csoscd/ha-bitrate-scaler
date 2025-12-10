
# Bitrate Scaler (Home Assistant)
Skaliert bit/s dynamisch in kbit/s bzw. Mbit/s – wahlweise mit dynamischer Einheit im State oder als Attribut (empfohlen für stabile Historien).

## Installation über HACS
1. HACS → Integrations → Drei Punkte → Custom repositories → URL dieses Repos eintragen, Kategorie **Integration**.
2. Repo auswählen → Installieren → HA neu starten.
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → **Bitrate Scaler**.

## Manuell
`custom_components/bitrate_scaler` in dein HA-Config kopieren → HA neu starten → Integration hinzufügen.

## Konfiguration
Über UI (Config-Flow): Modus, Präzision, Schwellen & Quell-Sensoren auswählen.
