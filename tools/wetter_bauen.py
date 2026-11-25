#!/usr/bin/env python3
"""Zentrales Wetterpaket für die SkiRadar-App.

Ruft Open-Meteo genau mit den Adressen ab, die die App selbst bauen würde
(omChunkU / omPLU / omGridU in der Karte), und packt die Antworten in zwei Dateien:

  wetter-berg.json.gz  – Skiorte auf Berghöhe (+ Zusatzwerte), Wolkenhöhen, Wolken-/Schneeraster
  wetter-tal.json.gz   – Skiorte auf Talhöhe (+ Zusatzwerte)

Format: {"v":1,"ts":<Unix-Sekunden>,"r":{"<Adresse>": <Open-Meteo-Antwort>, ...}}

Die Orte stehen in daten/orte.json (aus der Karte erzeugt, Reihenfolge wichtig: 30er-Blöcke).
Open-Meteo: kostenlose, nicht-kommerzielle Nutzung, CC BY 4.0 (Quelle wird in der App genannt).
Ein Lauf kostet ca. 4000 gewichtete Abrufe; der Job läuft zweimal täglich (< 10 000 pro Tag).
"""
import gzip, json, os, sys, time, urllib.request, urllib.error

HIER = os.path.dirname(os.path.abspath(__file__))
ORTE = json.load(open(os.path.join(HIER, '..', 'daten', 'orte.json'), encoding='utf-8'))

MODELS = ['icon_seamless', 'ecmwf_ifs025', 'gfs_seamless', 'meteofrance_seamless']
VARS = ['precipitation', 'snow_depth', 'cloud_cover', 'temperature_2m', 'freezing_level_height', 'wind_gusts_10m']
VARS2 = ['sunshine_duration', 'weather_code', 'cape']
PL = [925, 850, 800, 700, 600, 500]
GL = [1000, 925, 850, 800, 700, 600, 500]
BASE = 'https://api.open-meteo.com/v1/forecast?'


def js_num(x):
    """Zahl so schreiben, wie JavaScript sie in einen Text verwandelt (47.01, 10.29, 2872)."""
    if isinstance(x, int) or (isinstance(x, float) and x.is_integer() and abs(x) < 1e15):
        return str(int(x))
    return repr(float(x))


def coords(pts):
    return 'latitude=' + ','.join(js_num(p['lat']) for p in pts) + '&longitude=' + ','.join(js_num(p['lon']) for p in pts)


def chunk_url(ch, models, lvl, vars_):
    return (BASE + coords(ch) + ('&elevation=' + ','.join(js_num(p['el']) for p in ch) if lvl == 'berg' else '')
            + '&hourly=' + ','.join(vars_) + ('&models=' + ','.join(MODELS) if models else '')
            + '&forecast_days=15&timeformat=unixtime&timezone=GMT')


def pl_url(ch):
    return (BASE + coords(ch) + '&hourly=' + ','.join('cloud_cover_%dhPa' % p for p in PL)
            + ',wind_speed_10m,wind_direction_10m&forecast_days=15&timeformat=unixtime&timezone=GMT')


def grid_url(ch):
    return (BASE + coords(ch) + '&hourly=' + ','.join('cloud_cover_%dhPa' % p for p in GL)
            + ',precipitation,temperature_2m,snow_depth,wind_speed_850hPa,wind_direction_850hPa,wind_speed_700hPa,wind_direction_700hPa,shortwave_radiation'
            + '&temporal_resolution=hourly_3&past_days=3&forecast_days=15&timeformat=unixtime&timezone=GMT')


def grid():
    """Gleiche Rechnung wie die Karte (gleiche Gleitkomma-Schritte, dann auf 3 Stellen)."""
    out = []
    dy, dx = .36, .5
    la, row = 43.8, 0
    while la <= 48.25:
        lo = 5.2 + (dx / 2 if row % 2 else 0)
        while lo <= 16.6:
            out.append({'lat': float('%.3f' % la), 'lon': float('%.3f' % lo)})
            lo += dx
        la += dy
        row += 1
    return out


def urls():
    berg, tal = [], []
    chunks = [ORTE[i:i + 30] for i in range(0, len(ORTE), 30)]
    for ch in chunks:
        berg += [chunk_url(ch, True, 'berg', VARS), pl_url(ch), chunk_url(ch, True, 'berg', VARS2)]
        tal += [chunk_url(ch, True, 'tal', VARS), chunk_url(ch, True, 'tal', VARS2)]
    g = grid()
    berg += [grid_url(g[i:i + 100]) for i in range(0, len(g), 100)]
    return berg, tal


def hole(u):
    for versuch in range(6):
        try:
            req = urllib.request.Request(u, headers={'User-Agent': 'SkiRadar-Wetterpaket (github.com/lasselemmer2/skiradar)', 'Accept-Encoding': 'gzip'})
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
                if r.headers.get('Content-Encoding') == 'gzip':
                    raw = gzip.decompress(raw)
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            grund = ''
            try:
                grund = json.loads(e.read()).get('reason', '')
            except Exception:
                pass
            if e.code == 429 or 'limit' in grund.lower():
                if 'daily' in grund.lower():
                    sys.exit('Tageslimit von Open-Meteo erreicht: ' + grund)
                warte = 65 * (versuch + 1)
                print('  Limit (%s) – warte %d s' % (grund or e.code, warte), flush=True)
                time.sleep(warte)
                continue
            if 500 <= e.code < 600:
                time.sleep(20)
                continue
            sys.exit('HTTP %d: %s' % (e.code, grund))
        except Exception as e:  # Netzfehler
            print('  Fehler %s – neuer Versuch' % e, flush=True)
            time.sleep(15)
    sys.exit('Abruf mehrfach fehlgeschlagen: ' + u[:120])


def pruefe(u, d):
    lst = d if isinstance(d, list) else [d]
    assert lst and all('hourly' in x and x['hourly'].get('time') for x in lst), 'leere Antwort: ' + u[:100]


def main():
    nur_liste = '--liste' in sys.argv
    berg, tal = urls()
    if nur_liste:
        print(json.dumps({'berg': berg, 'tal': tal}, ensure_ascii=False))
        return
    ziel = sys.argv[1] if len(sys.argv) > 1 else '.'
    os.makedirs(ziel, exist_ok=True)
    for name, lst in (('berg', berg), ('tal', tal)):
        r = {}
        for k, u in enumerate(lst):
            print('%s %d/%d' % (name, k + 1, len(lst)), flush=True)
            d = hole(u)
            pruefe(u, d)
            r[u] = d
            time.sleep(4)   # sanft zum kostenlosen Dienst (Limit pro Minute)
        paket = {'v': 1, 'ts': int(time.time()), 'quelle': 'Open-Meteo.com (CC BY 4.0)', 'r': r}
        pfad = os.path.join(ziel, 'wetter-%s.json.gz' % name)
        with gzip.open(pfad, 'wt', encoding='utf-8', compresslevel=9) as f:
            json.dump(paket, f, separators=(',', ':'))
        print('%s: %d Antworten, %.1f MB' % (pfad, len(r), os.path.getsize(pfad) / 1e6), flush=True)


if __name__ == '__main__':
    main()
