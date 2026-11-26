"""Höhenlage je Skiort aus den Liften: tiefste Talstation und höchste Bergstation.
   Für jeden Ort (tools/skiorte.json: Name, Breite, Länge) werden alle Lifte genommen, deren Tal- oder Bergstation
   höchstens RADIUS_KM vom Ort entfernt liegt. Die Höhen der beiden Liftenden kommen aus dem Geländemodell
   (Mapzen Terrain Tiles auf AWS Open Data, Terrarium-Kacheln, Zoom 13 ≈ 15 m je Pixel).
   Ergebnis wird als "elev": {Name: [tiefster Liftstart, höchstes Liftende, Anzahl Lifte, Länge/Breite tief, Länge/Breite hoch]} in die Pistendatei geschrieben.
   Aufruf: python3 tools/hoehen_bauen.py daten/alpen-pisten.json.gz"""
import gzip, json, math, os, struct, sys, time, urllib.request, zlib

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
def ele(lon, lat):
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
    px = min(w - 1, int((fx - x) * w)); py = min(w - 1, int((fy - y) * w)); i = (py * w + px) * bpp
    return d[i] * 256 + d[i + 1] + d[i + 2] / 256 - 32768

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
    out = {}
    for name, lat, lon in orte:
        mine = [l for l in lifts if km(l[0], l[1], lon, lat) < RADIUS_KM or km(l[2], l[3], lon, lat) < RADIUS_KM]
        if not mine: continue
        lo, hi, plo, phi = 1e9, -1e9, None, None
        for l in mine:
            for (x, y) in ((l[0], l[1]), (l[2], l[3])):
                e = ele(x, y)
                if e < lo: lo, plo = e, (x, y)
                if e > hi: hi, phi = e, (x, y)
        out[name] = [round(lo), round(hi), len(mine), round(plo[0], 5), round(plo[1], 5), round(phi[0], 5), round(phi[1], 5)]
        print(f'{name}: {round(lo)}–{round(hi)} m ({len(mine)} Lifte)', flush=True)
    d['elev'] = out
    with gzip.open(path, 'wt', encoding='utf-8') as g:
        json.dump(d, g, ensure_ascii=False, separators=(',', ':'))
    print('Orte mit Höhen:', len(out), '· Kacheln:', len(_tiles))

if __name__ == '__main__':
    main(sys.argv[1])
