"""Höhenlage je Skiort aus den Liften: tiefste Talstation und höchste Bergstation.
   Für jeden Ort (tools/skiorte.json: Name, Breite, Länge) werden alle Lifte genommen, deren Tal- oder Bergstation
   höchstens RADIUS_KM vom Ort entfernt liegt. Die Höhen der beiden Liftenden kommen aus dem Geländemodell
   (Mapzen Terrain Tiles auf AWS Open Data, Terrarium-Kacheln, Zoom 13 ≈ 15 m je Pixel).
   Liegt eine Liftstation mit eingetragener Höhe (OSM ele) höchstens 80 m vom Liftende, gilt deren Höhe.
   Ergebnis wird als "elev": {Name: [tiefster Liftstart, höchstes Liftende, Anzahl Lifte, Länge/Breite tief, Länge/Breite hoch]} in die Pistendatei geschrieben.
   Aufruf: python3 tools/hoehen_bauen.py daten/alpen-pisten.json.gz"""
import gzip, json, math, os, struct, sys, time, urllib.parse, urllib.request, zlib

RADIUS_KM = 6
SKIP = {'magic_carpet', 'zip_line', 'goods', 'station', 'pylon', 'canopy'}
Z = 13
DEM = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'

def png_rgb(b):
    assert b[:8] == b'\x89PNG\r\n\x1a\n'
    i, idat = 8, b''
    while i < len(b):
        n = struct.unpack('>I', b[i:i + 4])[0]; t = b[i + 4:i + 8]; d = b[i + 8:i + 8 + n]; i += 12 + n
        if t == b'IHDR': w, h, bd, ct = struct.unpack('>IIBB', d[:10])
        elif t == b'IDAT': idat += d
    raw = zlib.decompress(idat); bpp = 3 if ct == 2 else 4; st = w * bpp
    out = bytearray(); prev = bytearray(st); p = 0
    for _ in range(h):
        f = raw[p]; p += 1; line = bytearray(raw[p:p + st]); p += st
        for x in range(st):
            a = line[x - bpp] if x >= bpp else 0; up = prev[x]; c = prev[x - bpp] if x >= bpp else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + up) & 255
            elif f == 3: line[x] = (line[x] + (a + up) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(up - c), abs(a - c), abs(a + up - 2 * c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else up if pb <= pc else c)) & 255
        out += line; prev = line
    return w, bpp, bytes(out)

_tiles = {}
def ele(lon, lat, rad=0):
    n = 2 ** Z; fx = (lon + 180) / 360 * n; la = math.radians(lat)
    fy = (1 - math.log(math.tan(la) + 1 / math.cos(la)) / math.pi) / 2 * n
    x, y = int(fx), int(fy)
    if (x, y) not in _tiles:
        for k in range(4):
            try:
                _tiles[(x, y)] = png_rgb(urllib.request.urlopen(DEM.format(z=Z, x=x, y=y), timeout=30).read()); break
            except Exception as e:
                if k == 3: raise
                time.sleep(2 * (k + 1))
    w, bpp, d = _tiles[(x, y)]
    px = min(w - 1, int((fx - x) * w)); py = min(w - 1, int((fy - y) * w)); best = -1e9
    # rad > 0: höchster Wert im Umkreis (Bergstationen auf schmalen Gipfeln liegen im 30-m-Geländemodell sonst zu tief)
    for dy in range(-rad, rad + 1):
        for dx in range(-rad, rad + 1):
            X = max(0, min(w - 1, px + dx)); Y = max(0, min(w - 1, py + dy)); i = (Y * w + X) * bpp
            best = max(best, d[i] * 256 + d[i + 1] + d[i + 2] / 256 - 32768)
    return best

def stationen():
    """Liftstationen mit eingetragener Höhe (OSM-Tag ele) – eine einzige Overpass-Abfrage für die ganzen Alpen."""
    q = '[out:json][timeout:180];node["aerialway"="station"]["ele"](43,5,49,17);out;'
    req = urllib.request.Request('https://overpass-api.de/api/interpreter', data=('data=' + urllib.parse.quote(q)).encode(),
                                 headers={'User-Agent': 'MetaSnow-Pistendaten/1.0 (github.com/lasselemmer2/skiradar; 1x pro Woche)'})
    js = json.loads(urllib.request.urlopen(req, timeout=240).read())
    out = []
    for el in js.get('elements', []):
        try:
            e = float(str(el['tags']['ele']).replace(',', '.').replace('m', '').strip())
        except Exception:
            continue
        if 200 < e < 4900:
            out.append((round(el['lon'], 5), round(el['lat'], 5), round(e)))
    return out

def km(lo1, la1, lo2, la2):
    return math.hypot((lo1 - lo2) * math.cos(math.radians(la1)) * 111.32, (la1 - la2) * 111.32)

def main(path):
    d = json.loads(gzip.open(path).read())
    orte = json.load(open(os.path.join(os.path.dirname(__file__), 'skiorte.json'), encoding='utf-8'))
    lifts = []
    for blk in d['blocks'].values():
        for f in json.loads(blk):
            typ = (f[1] or {}).get('aerialway')
            if not typ or typ in SKIP: continue
            a = f[2]; x, y = a[0], a[1]; x1, y1 = x, y
            for i in range(2, len(a), 2): x1 += a[i]; y1 += a[i + 1]
            if km(x / 1e5, y / 1e5, x1 / 1e5, y1 / 1e5) < .08: continue
            lifts.append((x / 1e5, y / 1e5, x1 / 1e5, y1 / 1e5))
    print('Lifte', len(lifts))
    try:
        st = stationen()
    except Exception as e:
        print('Stationshöhen aus OSM nicht abrufbar:', e); st = []
    print('Stationen mit Höhe (OSM):', len(st))
    grid = {}
    for s_ in st:
        grid.setdefault((round(s_[0], 2), round(s_[1], 2)), []).append(s_)
    def osm_ele(x, y):
        best, bd = None, .08                                   # Station höchstens 80 m vom Liftende
        for gx in (-.01, 0, .01):
            for gy in (-.01, 0, .01):
                for s_ in grid.get((round(x + gx, 2), round(y + gy, 2)), ()):
                    d = km(x, y, s_[0], s_[1])
                    if d < bd: best, bd = s_[2], d
        return best
    used = 0
    out = {}
    for name, lat, lon in orte:
        mine = [l for l in lifts if km(l[0], l[1], lon, lat) < RADIUS_KM or km(l[2], l[3], lon, lat) < RADIUS_KM]
        if not mine: continue
        lo, hi, plo, phi = 1e9, -1e9, None, None
        for l in mine:
            for (x, y) in ((l[0], l[1]), (l[2], l[3])):
                o = osm_ele(x, y)
                if o is not None: e = eh = o; used += 1
                else: e, eh = ele(x, y), ele(x, y, 2)
                if e < lo: lo, plo = e, (x, y)
                if eh > hi: hi, phi = eh, (x, y)
        out[name] = [round(lo), round(hi), len(mine), round(plo[0], 5), round(plo[1], 5), round(phi[0], 5), round(phi[1], 5)]
        print(f'{name}: {round(lo)}–{round(hi)} m ({len(mine)} Lifte)', flush=True)
    d['elev'] = out
    d['stations'] = st                                         # für die Höhenschilder an den Bergstationen in der App
    print('Liftenden mit OSM-Höhe:', used)
    with gzip.open(path, 'wt', encoding='utf-8') as g:
        json.dump(d, g, ensure_ascii=False, separators=(',', ':'))
    print('Orte mit Höhen:', len(out), '· Kacheln:', len(_tiles))

if __name__ == '__main__':
    main(sys.argv[1])
