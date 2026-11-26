#!/usr/bin/env python3
"""Baut die Pistendatei der Alpen für SkiRadar (läuft beim Bauen in Xcode auf dem Mac).

Quelle: OpenSkiData (openskidata.org) – täglicher Export aller Pisten und Lifte aus OpenStreetMap.
Erlaubt: automatischer Download höchstens einmal pro Tag. Wir prüfen höchstens alle 14 Tage,
ob es einen neueren Stand gibt; sonst wird die zwischengespeicherte Datei benutzt.

Aufruf: pisten_bauen.py <Cache-Ordner> <Zielordner im App-Paket>
Ergebnis: alpen-pisten.json.gz  –  {v, date, src, cov, fail, blocks: {"46.2,10.2": "<JSON der Wege>"}}
  Weg = [OSM-Way-ID, Tags wie in OSM, Koordinaten als ganze Zahlen (1e-5 °), jeweils Differenz zum Vorgänger]
  Ein Weg steht in jedem 0,2°-Bereich, den er berührt.
"""
import gzip, json, math, os, shutil, subprocess, sys, time

BASE = 'https://tiles.openskimap.org'
COV = [43.0, 5.0, 49.0, 17.0]          # Alpen + Vorland (Süd, West, Nord, Ost)
PB = 0.2
CHECK_DAYS = 14
NAME = 'alpen-pisten.json.gz'


def log(*a):
    print('Pistendaten:', *a, flush=True)


def curl(url):
    """Download über curl (nutzt die Zertifikate des Macs; --compressed entpackt die Übertragung)."""
    return subprocess.Popen(['/usr/bin/curl', '-sSLf', '--compressed', '--retry', '3', '-A', 'SkiRadar-Datenbau (GitHub Action, woechentlich)', url],
                            stdout=subprocess.PIPE)


def get_json(url):
    p = curl(url)
    data = p.stdout.read()
    if p.wait() != 0:
        raise RuntimeError('Download fehlgeschlagen: ' + url)
    return json.loads(data)


def lines(url):
    p = curl(url)
    for ln in p.stdout:
        yield ln
    if p.wait() != 0:
        raise RuntimeError('Download fehlgeschlagen: ' + url)


def in_cov(cs):
    return any(COV[0] <= c[1] < COV[2] and COV[1] <= c[0] < COV[3] for c in cs)


def osm_id(p):
    for s in p.get('sources') or []:
        if s.get('type') == 'openstreetmap' and str(s.get('id', '')).startswith('way/'):
            return int(s['id'][4:])
    return None


def run_tags(p):
    uses = p.get('uses') or []
    ty = next((x for x in ['downhill', 'nordic', 'skitour', 'sled', 'hike'] if x in uses), None)
    if not ty or p.get('status') in ('abandoned', 'disused'):
        return None
    t = {'piste:type': ty}
    if p.get('difficulty'): t['piste:difficulty'] = p['difficulty']
    if p.get('name'): t['name'] = p['name']
    if p.get('ref'): t['piste:ref'] = p['ref']
    if p.get('grooming'): t['piste:grooming'] = p['grooming']
    if p.get('lit') is True: t['lit'] = 'yes'
    if p.get('oneway') is True: t['oneway'] = 'yes'
    elif p.get('oneway') is False: t['oneway'] = 'no'
    if p.get('snowmaking') is True: t['piste:snowmaking'] = 'yes'
    if p.get('description'): t['description'] = p['description']
    if p.get('wikidataID'): t['wikidata'] = p['wikidataID']
    if p.get('status') and p['status'] != 'operating': t['piste:status'] = p['status']
    return t


def lift_tags(p):
    lt = p.get('liftType')
    if not lt or lt == 'zip_line' or p.get('status') in ('abandoned', 'disused'):
        return None
    t = {'aerialway': lt}
    if p.get('name'): t['name'] = p['name']
    if p.get('ref'): t['ref'] = p['ref']
    if p.get('capacity'): t['aerialway:capacity'] = str(p['capacity'])
    if p.get('occupancy'): t['aerialway:occupancy'] = str(p['occupancy'])
    if p.get('duration'): t['aerialway:duration'] = str(round(p['duration'] / 60))
    if p.get('heating') is True: t['aerialway:heating'] = 'yes'
    if p.get('bubble') is True: t['aerialway:bubble'] = 'yes'
    if p.get('detachable') is True: t['aerialway:detachable'] = 'yes'
    if p.get('status') and p['status'] != 'operating': t['piste:status'] = p['status']
    return t


def bkey(la, lo):
    return '%.1f,%.1f' % (math.floor(la / PB + 1e-9) * PB, math.floor(lo / PB + 1e-9) * PB)


def _km(x):
    """Summe aller lengthInKm-Angaben in einem Statistik-Zweig."""
    if isinstance(x, dict):
        return sum((v if k == 'lengthInKm' and isinstance(v, (int, float)) else _km(v)) for k, v in x.items())
    if isinstance(x, list):
        return sum(_km(v) for v in x)
    return 0


def _center(g):
    t, c = g.get('type'), g.get('coordinates')
    if t == 'Point':
        return c
    pts = []
    def walk(a):
        if a and isinstance(a[0], (int, float)):
            pts.append(a)
        else:
            for b in a or []:
                walk(b)
    walk(c)
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]


def build_areas():
    """Namen und Mittelpunkte aller Skigebiete (Alpinski und Langlauf) – für die Namensschilder auf der Karte."""
    out = []
    raw = b''.join(lines(f'{BASE}/geojson/ski_areas.geojson'))
    feats = []
    try:                                   # ganze Datei als eine FeatureCollection (so liefert OpenSkiData die Skigebiete)
        d = json.loads(raw)
        feats = d.get('features') or [] if isinstance(d, dict) else []
    except Exception:
        pass
    if not feats:                          # sonst: ein Feature pro Zeile (wie bei Pisten und Liften)
        for ln in raw.splitlines():
            ln = ln.strip().rstrip(b',')
            if b'"Feature"' in ln[:40]:
                try:
                    feats.append(json.loads(ln))
                except Exception:
                    pass
    log('Skigebiete in der Datei:', len(feats), '' if feats else '– Anfang: ' + raw[:200].decode('utf-8', 'replace'))
    for f in feats:
        p = f.get('properties') or {}
        name = (p.get('name') or '').strip()
        if not name or p.get('status') in ('abandoned', 'disused'):
            continue
        acts = p.get('activities') or []
        kind = 'a' if 'downhill' in acts else 'n' if 'nordic' in acts else None
        if not kind:
            continue
        c = _center(f.get('geometry') or {})
        if not c or not (COV[0] <= c[1] < COV[2] and COV[1] <= c[0] < COV[3]):
            continue
        st = ((p.get('statistics') or {}).get('runs') or {}).get('byActivity') or {}
        km = round(_km(st.get('downhill') if kind == 'a' else st.get('nordic')), 1)
        out.append([name, round(c[0], 5), round(c[1], 5), km, kind])
    if not out and feats:
        log('Beispiel-Eigenschaften:', json.dumps(feats[0].get('properties'), ensure_ascii=False)[:600])
    out.sort(key=lambda a: -a[3])
    log(len(out), 'Skigebiete mit Namen')
    return out


def build(dst, date):
    ways, used, fake = [], set(), [9 * 10 ** 12]
    for kind in ('lifts', 'runs'):
        n = 0
        for ln in lines(f'{BASE}/geojson/{kind}.geojson'):
            ln = ln.strip()
            if ln.endswith(b','):
                ln = ln[:-1]
            if not ln.startswith(b'{"type":"Feature"'):
                continue
            try:
                f = json.loads(ln)
            except Exception:
                continue
            g = f.get('geometry') or {}
            parts = [g['coordinates']] if g.get('type') == 'LineString' else g['coordinates'] if g.get('type') == 'MultiLineString' else []
            if not parts or not any(in_cov(cs) for cs in parts):
                continue
            t = (run_tags if kind == 'runs' else lift_tags)(f.get('properties') or {})
            if not t:
                continue
            wid = osm_id(f['properties'])
            for i, cs in enumerate(parts):
                if len(cs) < 2:
                    continue
                k = wid if (i == 0 and wid is not None and wid not in used) else None
                if k is None:
                    k = fake[0]; fake[0] += 1
                used.add(k)
                ways.append((k, t, [(round(c[0] * 1e5), round(c[1] * 1e5)) for c in cs]))
            n += 1
        log(kind, n, 'in den Alpen')
    blocks = {}
    for wid, t, cs in ways:
        keys = set()
        for i, (x, y) in enumerate(cs):
            lo, la = x / 1e5, y / 1e5
            keys.add(bkey(la, lo))
            if i:
                plo, pla = cs[i - 1][0] / 1e5, cs[i - 1][1] / 1e5
                n = int(max(abs(lo - plo), abs(la - pla)) / 0.05)
                for k in range(1, n + 1):
                    f = k / (n + 1)
                    keys.add(bkey(pla + (la - pla) * f, plo + (lo - plo) * f))
        d, px, py = [], 0, 0
        for x, y in cs:
            d += [x - px, y - py]
            px, py = x, y
        rec = [wid, t, d]
        for k in keys:
            blocks.setdefault(k, []).append(rec)
    try:
        areas = build_areas()
    except Exception as e:
        log('Skigebiets-Namen nicht ladbar:', e)
        areas = []
    out = {'v': 1, 'date': date, 'src': 'OpenSkiData / OpenSkiMap.org, © OpenStreetMap-Mitwirkende (ODbL), Skimap.org',
           'cov': COV, 'fail': {}, 'areas': areas,
           'blocks': {k: json.dumps(v, separators=(',', ':'), ensure_ascii=False) for k, v in blocks.items()}}
    tmp = dst + '.tmp'
    with gzip.open(tmp, 'wb', 9) as f:
        f.write(json.dumps(out, separators=(',', ':'), ensure_ascii=False).encode())
    os.replace(tmp, dst)
    log(len(ways), 'Wege,', len(blocks), 'Bereiche,', round(os.path.getsize(dst) / 1e6, 1), 'MB, Stand', date)


def main(cache_dir, target_dir):
    os.makedirs(cache_dir, exist_ok=True)
    cached = os.path.join(cache_dir, NAME)
    stamp = os.path.join(cache_dir, 'stand.txt')
    fresh = os.path.exists(cached) and time.time() - os.path.getmtime(stamp if os.path.exists(stamp) else cached) < CHECK_DAYS * 86400
    if not fresh:
        try:
            meta = get_json(f'{BASE}/metadata.json')
            date = meta['source']['openStreetMap']['dataTimestamp'][:10]
            old = open(stamp).read().strip() if os.path.exists(stamp) else ''
            if date != old or not os.path.exists(cached):
                log('lade neuen Stand', date, '(dauert beim ersten Mal ein paar Minuten)')
                build(cached, date)
            open(stamp, 'w').write(date)
            os.utime(stamp)
        except Exception as e:
            log('Aktualisierung nicht möglich:', e, '– nehme vorhandene Datei' if os.path.exists(cached) else '')
    if os.path.exists(cached) and target_dir:
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(cached, os.path.join(target_dir, NAME))
        log('in die App gepackt')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else '')
