# Pistendaten der Alpen (alpen-pisten.json.gz)

Auszug der Pisten und Lifte im Alpenraum (43–49° N, 5–17° O) aus **OpenSkiData / OpenSkiMap.org**,
© OpenStreetMap-Mitwirkende, Skimap.org.

Diese Datenbank steht unter der **Open Database License (ODbL) 1.0**:
https://opendatacommons.org/licenses/odbl/1-0/

Die jeweils aktuelle Datei gibt es unter „Releases“ dieses Repositorys. Sie wird wöchentlich automatisch aus dem
öffentlichen OpenSkiData-Export neu erzeugt (Skript: `tools/pisten_bauen.py`).

Format: `{v, date, src, cov, fail, blocks: {"46.2,10.2": "<JSON der Wege>"}}` – ein Weg ist
`[OSM-Way-ID, OSM-Tags, Koordinaten als ganze Zahlen (1e-5 °), jeweils als Differenz zum Vorgänger]`.
