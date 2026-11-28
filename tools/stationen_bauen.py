#!/usr/bin/env python3
"""Gemessene Schneehöhen der Alpen aus offenen Stationsnetzen – eine kleine Datei für MetaSnow.

Quellen (alle frei, ohne Schlüssel; jede Quelle für sich abgesichert – fällt eine aus, bleiben die anderen):
  SLF IMIS + Vergleichsstationen (Schweiz)        CC BY 4.0   https://measurement-api.slf.ch
  Lawinenwarndienste Tirol, Südtirol, Trentino    CC BY 4.0   https://avalanche.report
  GeoSphere Austria TAWES (Österreich)            CC BY 4.0   https://data.hub.geosphere.at
  Météo-France Stationen (franz. Alpen, täglich)  Licence Ouverte 2.0  https://meteo.data.gouv.fr
  Deutscher Wetterdienst (bayerische Alpen)       CC BY 4.0   https://opendata.dwd.de

Aufruf: python3 tools/stationen_bauen.py <ausgabeordner>
Ergebnis: <ausgabeordner>/stationen.json
  {"ts": Unixzeit, "q": {quelle: anzahl}, "s": [[lon, lat, höhe_m, name, schneehöhe_cm, änderung_24h_cm|null, neuschnee_24h_cm|null, messzeit_unix, quelle], …]}
"""
import csv, gzip, io, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

UA = {'User-Agent': 'MetaSnow/1.0 (+https://github.com/lasselemmer2/skiradar)'}
BBOX = (4.3, 42.8, 17.8, 49.8)          # lon_min, lat_min, lon_max, lat_max
MAX_ALT_H = 36                           # ältere Messungen werden weggelassen (Stunden)


def get(url, timeout=90, tries=3):
    last = None
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (a + 1))
    raise last


def getj(url, **kw):
    return json.loads(get(url, **kw))


def iso(s):
    s = s.strip().replace('Z', '+00:00')
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp())


def inbox(lon, lat):
    return BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]


def num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def rnd(v):
    return None if v is None else round(v, 1)


# ---------------------------------------------------------------- SLF (Schweiz)
def slf():
    out = []
    base = 'https://measurement-api.slf.ch/public/api/'
    for kind in ('imis', 'study-plot'):
        meta = {s['code']: s for s in getj(base + kind + '/stations')}
        rows = getj(base + kind + '/measurements', timeout=180)
        by = {}
        for m in rows:
            by.setdefault(m['station_code'], []).append(m)
        for code, ms in by.items():
            st = meta.get(code)
            if not st:
                continue
            ms = [m for m in ms if num(m.get('HS')) is not None]
            if not ms:
                continue
            ms.sort(key=lambda m: m['measure_date'])
            last = ms[-1]
            t = iso(last['measure_date'])
            hs = num(last['HS'])
            d24 = None
            if kind == 'imis':
                old = [m for m in ms if iso(m['measure_date']) <= t - 23 * 3600]
                if old:
                    d24 = hs - num(old[-1]['HS'])
            hn = num(last.get('HN_1D')) if kind == 'study-plot' else None
            out.append([st['lon'], st['lat'], st.get('elevation'), st['label'], hs, rnd(d24), hn, t, 'slf'])
    return out


# ------------------------------------------- Lawinenwarndienste Tirol/Südtirol/Trentino
def euregio():
    out = []
    j = getj('https://static.avalanche.report/weather_stations/stations.geojson')
    for f in j['features']:
        p, c = f['properties'], f['geometry']['coordinates']
        hs = num(p.get('HS'))
        if hs is None or not p.get('date'):
            continue
        out.append([c[0], c[1], c[2] if len(c) > 2 else None, p.get('name') or '', hs, rnd(num(p.get('HSD24'))), None, iso(p['date']), 'euregio'])
    return out


# ------------------------------------------------------------- GeoSphere (Österreich)
def geosphere():
    out = []
    base = 'https://dataset.api.hub.geosphere.at/v1/station/current/tawes-v1-10min'
    meta = getj(base + '/metadata')
    st = {s['id']: s for s in meta['stations'] if s.get('is_active') and inbox(s['lon'], s['lat'])}
    ids = sorted(st)
    for i in range(0, len(ids), 80):
        q = urllib.parse.urlencode([('parameters', 'SCHNEE')] + [('station_ids', x) for x in ids[i:i + 80]])
        j = getj(base + '?' + q)
        ts = j.get('timestamps') or []
        t = iso(ts[-1]) if ts else int(time.time())
        for f in j.get('features', []):
            sid = str(f['properties'].get('station'))
            d = f['properties'].get('parameters', {}).get('SCHNEE', {}).get('data') or []
            hs = next((num(x) for x in reversed(d) if num(x) is not None), None)
            s = st.get(sid)
            if hs is None or not s:
                continue
            out.append([s['lon'], s['lat'], s.get('altitude'), s['name'].title(), hs, None, None, t, 'geosphere'])
    return out


# --------------------------------------------------- Météo-France (franz. Alpen)
DEPTS = ('73', '74', '38', '05', '04', '06', '01')


def meteofrance():
    out = []
    urls = {}
    page = 'https://www.data.gouv.fr/api/2/datasets/donnees-climatologiques-de-base-horaires/resources/?page_size=200'
    while page:  # Liste der Dateien durchgehen, damit der Jahreswechsel im Dateinamen egal ist
        res = getj(page)
        for r in res.get('data', []):
            m = re.search(r'/H_(\d+)_latest-[\d-]+\.csv\.gz$', r.get('url', ''))
            if m and m.group(1) in DEPTS:
                urls[m.group(1)] = r['url']
        page = res.get('next_page')
    now = time.time()
    for dep, url in sorted(urls.items()):
        raw = gzip.decompress(get(url, timeout=300))
        rd = csv.reader(io.StringIO(raw.decode('utf-8', 'replace')), delimiter=';')
        head = next(rd)
        ix = {k: i for i, k in enumerate(head)}
        iS, iH, iT = ix['NUM_POSTE'], ix['NEIGETOT'], ix['AAAAMMJJHH']
        iF = ix.get('HNEIGEF')
        last = {}
        hist = {}
        for row in rd:
            if len(row) <= iH:
                continue
            hs = num(row[iH])
            if hs is None:
                continue
            try:
                t = int(datetime.strptime(row[iT], '%Y%m%d%H').replace(tzinfo=timezone.utc).timestamp())
            except ValueError:
                continue
            if t < now - 4 * 86400:
                continue
            sid = row[iS]
            hist.setdefault(sid, []).append((t, hs, num(row[iF]) if iF is not None else None))
            last[sid] = row
        for sid, h in hist.items():
            h.sort()
            t, hs, _ = h[-1]
            old = [x for x in h if x[0] <= t - 23 * 3600]
            d24 = hs - old[-1][1] if old and old[-1][0] >= t - 30 * 3600 else None
            fresh = [x[2] for x in h if x[0] > t - 24 * 3600 and x[2] is not None]
            hn = sum(fresh) if fresh else None
            r = last[sid]
            lon, lat, alt = num(r[ix['LON']]), num(r[ix['LAT']]), num(r[ix['ALTI']])
            if lon is None or not inbox(lon, lat):
                continue
            out.append([lon, lat, alt, r[ix['NOM_USUEL']].title(), hs, rnd(d24), rnd(hn), t, 'meteofrance'])
    return out


# --------------------------------------------------------- DWD (bayerische Alpen)
def dwd():
    out = []
    cat = get('https://www.dwd.de/DE/leistungen/met_verfahren_mosmix/mosmix_stationskatalog.cfg?view=nasPublication').decode('latin-1')
    st = []
    for line in cat.splitlines():
        m = re.match(r'^(\w{4,5})\s+\S+\s+(.+?)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+)\s*$', line)
        if not m:
            continue
        sid, name, lat, lon, el = m.group(1), m.group(2).strip(), float(m.group(3)), float(m.group(4)), int(m.group(5))
        if 47.2 <= lat <= 47.85 and 9.8 <= lon <= 13.1 and sid.isdigit() and sid.startswith('10'):
            st.append((sid, name, lat, lon, el))
    for sid, name, lat, lon, el in st:
        try:
            txt = get('https://opendata.dwd.de/weather/weather_reports/poi/%s-BEOB.csv' % sid, tries=1).decode('utf-8', 'replace')
        except Exception:  # noqa: BLE001 – nicht jede Station hat eine Datei
            continue
        rows = list(csv.reader(io.StringIO(txt), delimiter=';'))
        if len(rows) < 4:
            continue
        col = None
        for hr in rows[:3]:
            for i, h in enumerate(hr):
                hl = h.lower()
                if 'schneeh' in hl or ('snow' in hl and ('thick' in hl or 'height' in hl or 'depth' in hl)):
                    col = i
            if col is not None:
                break
        if col is None:
            continue
        data = []
        for r in rows[3:]:
            if len(r) <= col:
                continue
            v = num(r[col].replace(',', '.'))
            try:
                t = int(datetime.strptime(r[0] + ' ' + r[1], '%d.%m.%y %H:%M').replace(tzinfo=timezone.utc).timestamp())
            except (ValueError, IndexError):
                continue
            if v is not None:
                data.append((t, v))
        if not data:
            continue
        data.sort()
        t, hs = data[-1]
        old = [x for x in data if x[0] <= t - 23 * 3600]
        out.append([lon, lat, el, name.title(), hs, rnd(hs - old[-1][1]) if old else None, None, t, 'dwd'])
    return out


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    alle, q = [], {}
    now = int(time.time())
    for name, fn in (('slf', slf), ('euregio', euregio), ('geosphere', geosphere), ('meteofrance', meteofrance), ('dwd', dwd)):
        try:
            rows = fn()
            rows = [r for r in rows if r[4] is not None and 0 <= r[4] < 1500 and now - r[7] < MAX_ALT_H * 3600 * (2 if name == 'meteofrance' else 1)
                    and inbox(r[0], r[1])]
            for r in rows:
                r[0], r[1] = round(r[0], 4), round(r[1], 4)
                r[2] = None if r[2] is None else int(round(r[2]))
                r[4] = round(r[4])
            alle += rows
            q[name] = len(rows)
            print(name, len(rows), 'Stationen', flush=True)
        except Exception as e:  # noqa: BLE001
            q[name] = 0
            print(name, 'FEHLER', repr(e)[:300], flush=True)
    alt = os.path.join(outdir, 'stationen.json')
    if not alle:
        print('Keine Station erreichbar – alte Datei bleibt.')
        return 1
    with open(alt, 'w', encoding='utf-8') as f:
        json.dump({'ts': now, 'q': q, 's': alle}, f, ensure_ascii=False, separators=(',', ':'))
    print('gesamt', len(alle), 'Stationen →', alt, os.path.getsize(alt), 'Bytes')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'stationen'))
