# MetaSnow (früher SkiRadar)

Website und Daten zur iOS-App **MetaSnow** – 3D-Schneekarte der Alpen, Pisten-Routing und Ski-Tracker.

- Hilfe & Support: https://lasselemmer2.github.io/skiradar/
- Sicherheitshinweise & Haftung: https://lasselemmer2.github.io/skiradar/sicherheit.html
- Datenschutz: https://lasselemmer2.github.io/skiradar/datenschutz.html
- Impressum: https://lasselemmer2.github.io/skiradar/impressum.html
- English: https://lasselemmer2.github.io/skiradar/en/ · Français: …/fr/ · Italiano: …/it/

## Pistendaten

Unter [Releases](https://github.com/lasselemmer2/skiradar/releases) liegt jede Woche eine neue `alpen-pisten.json.gz`.
Sie wird automatisch aus dem öffentlichen OpenSkiData-Export erzeugt (`.github/workflows/pisten.yml`, `tools/pisten_bauen.py`).

Daten: OpenSkiData / OpenSkiMap.org, © OpenStreetMap-Mitwirkende, Skimap.org –
lizenziert unter der [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/). Siehe `daten/LIZENZ.md`.

## Wetterdaten

Zweimal täglich holt `.github/workflows/wetter.yml` (Skript `tools/wetter_bauen.py`) die Vorhersage für alle Skiorte
der App und ein Wolken-/Schneeraster bei [Open-Meteo.com](https://open-meteo.com/) und legt sie im Release
[`wetter`](https://github.com/lasselemmer2/skiradar/releases/tag/wetter) ab (`wetter-berg.json.gz`, `wetter-tal.json.gz`).
So fragt nicht jedes iPhone einzeln den Wetterdienst ab. Die Orte stehen in `daten/orte.json`.

Wetterdaten: Open-Meteo.com, Lizenz [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) – Modelle von DWD (ICON), ECMWF, NOAA (GFS) und Météo-France.
