
import json
import glob
import os
import sys
import zipfile
import tempfile
import shutil
import argparse
from collections import defaultdict
from datetime import datetime

YEAR_MIN = 2021
YEAR_MAX = 2026


DATA_PATH = "spotify_data"

# ----------------------------------------------------------------------
# Kanoniczne albumy Olivii Rodrigo
# Spotify potrafi zapisywać te same utwory pod różnymi nazwami "albumu"
# (np. jako pojedynczy singiel przed premierą, wersję deluxe, live itp.).
# Poniżej ręcznie zdefiniowane 3 prawdziwe albumy - wszystko inne
# (single, covery, wersje live, ścieżki dźwiękowe) trafia do "Single / Inne".
# ----------------------------------------------------------------------
SINGLES_BUCKET = "Single / Inne"

CANONICAL_ALBUMS = {
    "SOUR": [
        "1 step forward, 3 steps back", "brutal", "deja vu", "drivers license",
        "enough for you", "favorite crime", "good 4 u", "happier", "hope ur ok",
        "jealousy, jealousy", "traitor",
    ],
    "GUTS": [
        "all-american bitch", "bad idea right?", "ballad of a homeschooled girl",
        "get him back!", "girl i've always been", "lacy", "logical",
        "love is embarrassing", "making the bed", "obsessed", "pretty isn't pretty",
        "scared of my guitar", "so american", "stranger", "teenage dream",
        "the grudge", "vampire",
    ],
    "you seem pretty sad for a girl so in love": [
        "begged", "cigarette smoke", "drop dead", "expectations", "honeybee",
        "less", "maggots for brains", "my way", "purple", "stupid song",
        "the cure", "u + me = <3", "what's wrong with me",
    ],
}


def _normalize_track_name(name):
    """Normalizuje nazwę utworu do porównania - usuwa dopiski typu ' - Live',
    ujednolica apostrofy, obcina do podstawowej nazwy utworu."""
    if not name:
        return ""
    n = name.lower().replace("’", "'").replace("‘", "'")
    # odetnij dopiski po myślniku lub ukośniku (live, cover, "from ...", itp.)
    for sep in [" - ", " / "]:
        if sep in n:
            n = n.split(sep)[0]
    return n.strip()


def _build_track_to_album_map():
    m = {}
    for album, tracks in CANONICAL_ALBUMS.items():
        for t in tracks:
            m[_normalize_track_name(t)] = album
    return m


TRACK_TO_ALBUM = _build_track_to_album_map()


def canonical_album_for(track_name):
    """Zwraca jeden z 3 prawdziwych albumów Olivii Rodrigo dla danego utworu,
    a jeśli utwór nie należy do żadnego z nich (singiel, cover, live, OST) -
    zwraca etykietę zbiorczą dla singli/pozostałych."""
    key = _normalize_track_name(track_name)
    return TRACK_TO_ALBUM.get(key, SINGLES_BUCKET)


# Wczytywanie danych

def find_audio_history_files(root_dir):
    """Znajduje wszystkie pliki Streaming_History_Audio_*.json w folderze (rekurencyjnie)."""
    pattern = os.path.join(root_dir, "**", "Streaming_History_Audio_*.json")
    files = glob.glob(pattern, recursive=True)
    return sorted(files)


def load_records(input_path):
    """Ładuje wszystkie rekordy odtworzeń z folderu lub pliku zip eksportu Spotify."""
    tmp_dir = None
    try:
        if os.path.isfile(input_path) and input_path.lower().endswith(".zip"):
            tmp_dir = tempfile.mkdtemp(prefix="spotify_data_")
            with zipfile.ZipFile(input_path, "r") as z:
                z.extractall(tmp_dir)
            search_dir = tmp_dir
        else:
            search_dir = input_path

        files = find_audio_history_files(search_dir)
        if not files:
            raise FileNotFoundError(
                f"Nie znaleziono plików 'Streaming_History_Audio_*.json' w: {input_path}"
            )

        records = []
        for fp in files:
            with open(fp, encoding="utf-8") as f:
                records.extend(json.load(f))
        return records
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# Filtrowanie i statystyki

def filter_artist_years(records, artist_name, year_min=YEAR_MIN, year_max=YEAR_MAX):
    artist_lower = artist_name.strip().lower()
    out = []
    for r in records:
        a = r.get("master_metadata_album_artist_name")
        ts = r.get("ts")
        if not a or not ts:
            continue
        if a.strip().lower() != artist_lower:
            continue
        try:
            year = int(ts[:4])
        except ValueError:
            continue
        if year_min <= year <= year_max:
            out.append(r)
    return out


def ms_to_minutes(ms):
    return ms / 60000.0


def compute_stats(records, artist_name):
    total_ms = sum(r.get("ms_played", 0) for r in records)
    total_plays = len(records)

    # "prawdziwe" odsłuchania - dłuższe niż 30 sek, żeby odsiać przypadkowe skipy
    real_plays = [r for r in records if r.get("ms_played", 0) >= 30000]

    songs = defaultdict(lambda: {"ms": 0, "plays": 0, "album": "", "uri": ""})
    albums = defaultdict(lambda: {"ms": 0, "plays": 0, "tracks": set()})
    years = defaultdict(lambda: {"ms": 0, "plays": 0})
    months = defaultdict(lambda: {"ms": 0, "plays": 0})
    year_top_song = defaultdict(lambda: defaultdict(lambda: {"ms": 0, "plays": 0}))
    year_top_album = defaultdict(lambda: defaultdict(lambda: {"ms": 0, "plays": 0}))
    hour_counts = defaultdict(int)
    weekday_counts = defaultdict(int)
    skip_count = 0
    first_ts = None
    last_ts = None

    for r in records:
        ms = r.get("ms_played", 0)
        track = r.get("master_metadata_track_name") or "Nieznany utwór"
        ts = r.get("ts")
        uri = r.get("spotify_track_uri") or ""

        # zamiast surowej nazwy albumu ze Spotify, używamy kanonicznego albumu
        # (SOUR / GUTS / you seem pretty sad... / Single / Inne)
        album = canonical_album_for(track)

        dt = None
        if ts:
            try:
                dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                dt = None

        if dt:
            if first_ts is None or dt < first_ts:
                first_ts = dt
            if last_ts is None or dt > last_ts:
                last_ts = dt
            year = dt.year
            month_key = f"{dt.year}-{dt.month:02d}"
            years[year]["ms"] += ms
            years[year]["plays"] += 1
            months[month_key]["ms"] += ms
            months[month_key]["plays"] += 1
            hour_counts[dt.hour] += 1
            weekday_counts[dt.weekday()] += 1

            year_top_song[year][track]["ms"] += ms
            year_top_song[year][track]["plays"] += 1
            year_top_album[year][album]["ms"] += ms
            year_top_album[year][album]["plays"] += 1

        key = track
        songs[key]["ms"] += ms
        songs[key]["plays"] += 1
        songs[key]["album"] = album
        songs[key]["uri"] = uri

        albums[album]["ms"] += ms
        albums[album]["plays"] += 1
        albums[album]["tracks"].add(track)

        if r.get("skipped"):
            skip_count += 1

    # ranking piosenek: po liczbie odtworzeń (nie po czasie trwania)
    top_songs = sorted(
        [{"track": k, "album": v["album"], "ms": v["ms"], "plays": v["plays"]}
         for k, v in songs.items()],
        key=lambda x: x["plays"], reverse=True
    )

    # osobno 3 prawdziwe albumy...
    top_albums = sorted(
        [{"album": k, "ms": v["ms"], "plays": v["plays"], "tracks": len(v["tracks"])}
         for k, v in albums.items() if k in CANONICAL_ALBUMS],
        key=lambda x: x["ms"], reverse=True
    )

    # ...a osobno single/covery/OST, ranking po odtworzeniach
    top_singles = sorted(
        [{"track": k, "ms": v["ms"], "plays": v["plays"]}
         for k, v in songs.items() if v["album"] == SINGLES_BUCKET],
        key=lambda x: x["plays"], reverse=True
    )

    yearly = []
    for y in range(YEAR_MIN, YEAR_MAX + 1):
        d = years.get(y, {"ms": 0, "plays": 0})
        top_song_y = max(year_top_song[y].items(), key=lambda kv: kv[1]["plays"], default=(None, {"ms": 0}))
        top_album_y = max(
            ((alb, v) for alb, v in year_top_album[y].items() if alb in CANONICAL_ALBUMS),
            key=lambda kv: kv[1]["ms"], default=(None, {"ms": 0})
        )
        yearly.append({
            "year": y,
            "ms": d["ms"],
            "plays": d["plays"],
            "minutes": round(ms_to_minutes(d["ms"]), 1),
            "top_song": top_song_y[0],
            "top_album": top_album_y[0],
        })

    month_labels = sorted(months.keys())
    monthly_trend = [
        {"month": m, "minutes": round(ms_to_minutes(months[m]["ms"]), 1), "plays": months[m]["plays"]}
        for m in month_labels
    ]

    hour_dist = [hour_counts.get(h, 0) for h in range(24)]
    weekday_names = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
    weekday_dist = [weekday_counts.get(i, 0) for i in range(7)]
    fav_hour = hour_dist.index(max(hour_dist)) if any(hour_dist) else None
    fav_weekday = weekday_names[weekday_dist.index(max(weekday_dist))] if any(weekday_dist) else None

    return {
        "artist": artist_name,
        "total_ms": total_ms,
        "total_minutes": round(ms_to_minutes(total_ms), 1),
        "total_hours": round(ms_to_minutes(total_ms) / 60.0, 1),
        "total_plays": total_plays,
        "real_plays": len(real_plays),
        "unique_songs": len(songs),
        "unique_albums": len([a for a in albums if a in CANONICAL_ALBUMS]),
        "skip_count": skip_count,
        "skip_rate": round(100 * skip_count / total_plays, 1) if total_plays else 0,
        "top_songs": top_songs[:20],
        "top_albums": top_albums,
        "top_singles": top_singles[:10],
        "yearly": yearly,
        "monthly_trend": monthly_trend,
        "hour_dist": hour_dist,
        "weekday_names": weekday_names,
        "weekday_dist": weekday_dist,
        "fav_hour": fav_hour,
        "fav_weekday": fav_weekday,
        "first_listen": first_ts.strftime("%d.%m.%Y") if first_ts else None,
        "last_listen": last_ts.strftime("%d.%m.%Y") if last_ts else None,
        "year_range": f"{YEAR_MIN}-{YEAR_MAX}",
    }

# Renderowanie HTML

def esc(s):
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def fmt_minutes(m):
    h = int(m // 60)
    mm = int(m % 60)
    if h:
        return f"{h} godz. {mm} min"
    return f"{mm} min"


def render_html(stats, out_path):
    top_songs_rows = ""
    for i, s in enumerate(stats["top_songs"], start=1):
        top_songs_rows += f"""
        <tr>
          <td class="rank">#{i}</td>
          <td class="song-title">{esc(s['track'])}<span class="song-album">{esc(s['album'])}</span></td>
          <td class="num">{s['plays']}</td>
          <td class="num">{fmt_minutes(ms_to_minutes(s['ms']))}</td>
        </tr>"""

    top_singles_rows = ""
    for i, s in enumerate(stats["top_singles"], start=1):
        top_singles_rows += f"""
        <tr>
          <td class="rank">#{i}</td>
          <td class="song-title">{esc(s['track'])}</td>
          <td class="num">{s['plays']}</td>
          <td class="num">{fmt_minutes(ms_to_minutes(s['ms']))}</td>
        </tr>"""

    top_albums_rows = ""
    max_album_ms = stats["top_albums"][0]["ms"] if stats["top_albums"] else 1
    for i, a in enumerate(stats["top_albums"], start=1):
        pct = round(100 * a["ms"] / max_album_ms) if max_album_ms else 0
        top_albums_rows += f"""
        <div class="album-bar-row">
          <div class="album-bar-label">
            <span class="album-rank">#{i}</span>
            <span class="album-name">{esc(a['album'])}</span>
            <span class="album-meta">{a['plays']} odtworzeń · {fmt_minutes(ms_to_minutes(a['ms']))}</span>
          </div>
          <div class="album-bar-track"><div class="album-bar-fill" style="width:{pct}%"></div></div>
        </div>"""

    yearly_cards = ""
    for y in stats["yearly"]:
        yearly_cards += f"""
        <div class="year-card">
          <div class="year-num">{y['year']}</div>
          <div class="year-stat"><span>{y['plays']}</span> odtworzeń</div>
          <div class="year-stat"><span>{fmt_minutes(y['minutes'])}</span></div>
          <div class="year-top">
            <div class="year-top-label">Top utwór</div>
            <div class="year-top-value">{esc(y['top_song']) if y['top_song'] else '—'}</div>
          </div>
          <div class="year-top">
            <div class="year-top-label">Top album</div>
            <div class="year-top-value">{esc(y['top_album']) if y['top_album'] else '—'}</div>
          </div>
        </div>"""

    month_labels_js = json.dumps([m["month"] for m in stats["monthly_trend"]])
    month_minutes_js = json.dumps([m["minutes"] for m in stats["monthly_trend"]])
    year_labels_js = json.dumps([y["year"] for y in stats["yearly"]])
    year_minutes_js = json.dumps([y["minutes"] for y in stats["yearly"]])
    album_labels_js = json.dumps([a["album"] for a in stats["top_albums"][:8]])
    album_minutes_js = json.dumps([round(ms_to_minutes(a["ms"]), 1) for a in stats["top_albums"][:8]])
    hour_labels_js = json.dumps([f"{h}:00" for h in range(24)])
    hour_dist_js = json.dumps(stats["hour_dist"])
    weekday_labels_js = json.dumps(stats["weekday_names"])
    weekday_dist_js = json.dumps(stats["weekday_dist"])

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(stats['artist'])} · Raport słuchania {stats['year_range']}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Permanent+Marker&family=Special+Elite&family=Archivo+Black&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root {{
  --bg: #100416;
  --bg2: #1b0726;
  --panel: #1f0a2b;
  --purple-deep: #4b1477;
  --purple: #8b3fd4;
  --purple-bright: #b06bff;
  --lavender: #d9b8ff;
  --lilac: #e9d5ff;
  --pink: #ff6ec7;
  --ink: #f3e9ff;
  --muted: #b199c9;
  --line: rgba(217, 184, 255, 0.18);
}}

* {{ box-sizing: border-box; }}

body {{
  margin: 0;
  background:
    radial-gradient(ellipse 80% 50% at 20% -10%, rgba(176, 107, 255, 0.35), transparent),
    radial-gradient(ellipse 60% 40% at 90% 10%, rgba(255, 110, 199, 0.15), transparent),
    linear-gradient(180deg, var(--bg) 0%, var(--bg2) 100%);
  color: var(--ink);
  font-family: 'Space Grotesk', sans-serif;
  min-height: 100vh;
  padding-bottom: 60px;
}}

.grain {{
  position: fixed; inset: 0; pointer-events: none; z-index: 999;
  opacity: 0.05; mix-blend-mode: overlay;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}}

header.hero {{
  position: relative;
  padding: 90px 24px 70px;
  text-align: center;
  overflow: hidden;
  border-bottom: 2px solid var(--purple);
}}

header.hero::before {{
  content: "";
  position: absolute; inset: 0;
  background: repeating-linear-gradient(115deg, rgba(217,184,255,0.05) 0 2px, transparent 2px 40px);
  pointer-events: none;
}}

.eyebrow {{
  font-family: 'Special Elite', monospace;
  letter-spacing: 6px;
  text-transform: uppercase;
  color: var(--pink);
  font-size: 13px;
  margin-bottom: 18px;
}}

h1.title {{
  font-family: 'Permanent Marker', cursive;
  font-size: clamp(48px, 9vw, 108px);
  margin: 0;
  color: var(--lilac);
  text-shadow: 0 0 25px rgba(176,107,255,0.65), 3px 3px 0 var(--purple-deep);
  line-height: 1;
  transform: rotate(-2deg);
}}

.subtitle {{
  font-family: 'Special Elite', monospace;
  color: var(--muted);
  margin-top: 22px;
  font-size: 16px;
  letter-spacing: 1px;
}}

.hero-stats {{
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 14px;
  margin-top: 44px;
}}

.hero-stat {{
  background: rgba(139,63,212,0.15);
  border: 1px solid var(--purple);
  border-radius: 4px;
  padding: 18px 26px;
  min-width: 150px;
  transform: rotate(var(--r, 0deg));
}}
.hero-stat:nth-child(2){{ --r: 1deg; }}
.hero-stat:nth-child(3){{ --r: -1deg; }}
.hero-stat:nth-child(4){{ --r: 0.6deg; }}

.hero-stat .num {{
  font-family: 'Archivo Black', sans-serif;
  font-size: 34px;
  color: var(--purple-bright);
  display: block;
}}
.hero-stat .lab {{
  font-size: 12px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 2px;
  margin-top: 4px;
}}

main {{
  max-width: 1080px;
  margin: 0 auto;
  padding: 0 24px;
}}

section {{
  margin-top: 90px;
}}

.section-head {{
  display: flex;
  align-items: baseline;
  gap: 16px;
  margin-bottom: 30px;
  border-bottom: 1px dashed var(--line);
  padding-bottom: 16px;
}}

.section-num {{
  font-family: 'Permanent Marker', cursive;
  font-size: 22px;
  color: var(--pink);
}}

h2 {{
  font-family: 'Archivo Black', sans-serif;
  font-size: clamp(26px, 4vw, 38px);
  margin: 0;
  color: var(--lilac);
  text-transform: uppercase;
  letter-spacing: 1px;
}}

.panel {{
  background: linear-gradient(160deg, rgba(75,20,119,0.35), rgba(31,10,43,0.6));
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 30px;
  backdrop-filter: blur(6px);
}}

.chart-wrap {{
  position: relative;
  height: 320px;
}}

table {{
  width: 100%;
  border-collapse: collapse;
}}
th {{
  text-align: left;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 2px;
  color: var(--muted);
  padding: 10px 12px;
  border-bottom: 2px solid var(--purple);
}}
td {{
  padding: 14px 12px;
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
}}
tr:hover td {{ background: rgba(176,107,255,0.06); }}
.rank {{
  font-family: 'Permanent Marker', cursive;
  color: var(--pink);
  font-size: 18px;
  width: 50px;
}}
.singles-note {{
  color: var(--muted);
  font-size: 13px;
  font-style: italic;
  margin: 0 0 18px;
}}
.empty-row {{
  text-align: center;
  color: var(--muted);
  padding: 24px;
}}
.song-title {{
  font-weight: 600;
  color: var(--ink);
  display: block;
}}
.song-album {{
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-top: 2px;
  font-style: italic;
}}
.num {{
  text-align: right;
  color: var(--lavender);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}}

.album-bar-row {{ margin-bottom: 24px; }}
.album-bar-label {{
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}}
.album-rank {{
  font-family: 'Permanent Marker', cursive;
  color: var(--pink);
}}
.album-name {{
  font-weight: 700;
  color: var(--ink);
  font-size: 17px;
}}
.album-meta {{
  color: var(--muted);
  font-size: 12px;
  margin-left: auto;
}}
.album-bar-track {{
  height: 14px;
  background: rgba(217,184,255,0.08);
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--line);
}}
.album-bar-fill {{
  height: 100%;
  background: linear-gradient(90deg, var(--purple-deep), var(--purple-bright), var(--pink));
  border-radius: 8px;
}}

.year-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 20px;
}}
.year-card {{
  background: rgba(75,20,119,0.25);
  border: 1px solid var(--purple);
  border-radius: 10px;
  padding: 22px;
  position: relative;
}}
.year-card::after {{
  content: "";
  position: absolute; top: 14px; right: 14px;
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--pink);
  box-shadow: 0 0 10px var(--pink);
}}
.year-num {{
  font-family: 'Archivo Black', sans-serif;
  font-size: 30px;
  color: var(--purple-bright);
}}
.year-stat {{
  color: var(--muted);
  font-size: 13px;
  margin-top: 4px;
}}
.year-stat span {{
  color: var(--lilac);
  font-weight: 700;
  font-size: 15px;
}}
.year-top {{
  margin-top: 14px;
  border-top: 1px dashed var(--line);
  padding-top: 10px;
}}
.year-top-label {{
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--pink);
}}
.year-top-value {{
  font-size: 14px;
  color: var(--ink);
  margin-top: 3px;
  font-weight: 600;
}}

.two-col {{
  display: grid;
  grid-template-columns: 1.3fr 1fr;
  gap: 24px;
}}
@media (max-width: 800px) {{
  .two-col {{ grid-template-columns: 1fr; }}
}}

.fun-facts {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 18px;
}}
.fact-card {{
  background: rgba(255,110,199,0.08);
  border: 1px solid rgba(255,110,199,0.35);
  border-radius: 10px;
  padding: 20px;
  text-align: center;
}}
.fact-card .icon {{ font-size: 26px; }}
.fact-card .val {{
  font-family: 'Archivo Black', sans-serif;
  font-size: 22px;
  color: var(--pink);
  margin-top: 8px;
}}
.fact-card .lab {{
  color: var(--muted);
  font-size: 12px;
  margin-top: 4px;
  text-transform: uppercase;
  letter-spacing: 1px;
}}

footer {{
  text-align: center;
  margin-top: 100px;
  padding: 30px;
  color: var(--muted);
  font-family: 'Special Elite', monospace;
  font-size: 12px;
  border-top: 1px solid var(--line);
}}
footer .stamp {{
  font-family: 'Permanent Marker', cursive;
  color: var(--purple-bright);
  font-size: 16px;
  margin-bottom: 6px;
}}
</style>
</head>
<body>
<div class="grain"></div>

<header class="hero">
  <div class="eyebrow">raport słuchania · {stats['year_range']}</div>
  <h1 class="title">{esc(stats['artist'])}</h1>
  <div class="subtitle">&mdash; teenage dream, purple palette, pisane w GUTS style &mdash;</div>
  <div class="hero-stats">
    <div class="hero-stat"><span class="num">{f"{stats['total_plays']:,}".replace(",", " ")}</span><span class="lab">odtworzeń</span></div>
    <div class="hero-stat"><span class="num">{stats['total_hours']:,}</span><span class="lab">godzin</span></div>
    <div class="hero-stat"><span class="num">{stats['unique_songs']}</span><span class="lab">utworów</span></div>
    <div class="hero-stat"><span class="num">{stats['unique_albums']}</span><span class="lab">albumów</span></div>
  </div>
</header>

<main>

  <section>
    <div class="section-head"><span class="section-num">01</span><h2>Trend słuchania w czasie</h2></div>
    <div class="panel chart-wrap"><canvas id="trendChart"></canvas></div>
  </section>

  <section>
    <div class="section-head"><span class="section-num">02</span><h2>Rok po roku</h2></div>
    <div class="year-grid">
      {yearly_cards}
    </div>
  </section>

  <section>
    <div class="section-head"><span class="section-num">03</span><h2>Top albumy</h2></div>
    <div class="two-col">
      <div class="panel">
        {top_albums_rows}
      </div>
      <div class="panel chart-wrap">
        <canvas id="albumChart"></canvas>
      </div>
    </div>
  </section>

  <section>
    <div class="section-head"><span class="section-num">04</span><h2>Top 20 piosenek</h2></div>
    <div class="panel">
      <table>
        <thead><tr><th></th><th>Utwór</th><th class="num">Odtworzenia</th><th class="num">Czas</th></tr></thead>
        <tbody>
          {top_songs_rows}
        </tbody>
      </table>
    </div>
  </section>

  <section>
    <div class="section-head"><span class="section-num">05</span><h2>Single &amp; inne (poza albumami)</h2></div>
    <div class="panel">
      <p class="singles-note">Utwory wydane jako single, covery, wersje live lub ścieżki dźwiękowe - nie wliczone do 3 albumów powyżej.</p>
      <table>
        <thead><tr><th></th><th>Utwór</th><th class="num">Odtworzenia</th><th class="num">Czas</th></tr></thead>
        <tbody>
          {top_singles_rows if top_singles_rows else '<tr><td colspan="4" class="empty-row">Brak singli poza albumami w tym okresie.</td></tr>'}
        </tbody>
      </table>
    </div>
  </section>

  <section>
    <div class="section-head"><span class="section-num">06</span><h2>Nawyki słuchania</h2></div>
    <div class="two-col">
      <div class="panel chart-wrap"><canvas id="hourChart"></canvas></div>
      <div class="panel chart-wrap"><canvas id="weekdayChart"></canvas></div>
    </div>
  </section>

  <section>
    <div class="section-head"><span class="section-num">07</span><h2>Ciekawostki</h2></div>
    <div class="fun-facts">
      <div class="fact-card"><div class="icon">🎧</div><div class="val">{stats['skip_rate']}%</div><div class="lab">wskaźnik pomijania</div></div>
      <div class="fact-card"><div class="icon">🕒</div><div class="val">{f"{stats['fav_hour']}:00" if stats['fav_hour'] is not None else '—'}</div><div class="lab">ulubiona godzina</div></div>
      <div class="fact-card"><div class="icon">📅</div><div class="val">{esc(stats['fav_weekday']) or '—'}</div><div class="lab">ulubiony dzień tygodnia</div></div>
      <div class="fact-card"><div class="icon">🟣</div><div class="val">{esc(stats['first_listen']) or '—'}</div><div class="lab">pierwsze odtworzenie w okresie</div></div>
      <div class="fact-card"><div class="icon">💜</div><div class="val">{esc(stats['last_listen']) or '—'}</div><div class="lab">ostatnie odtworzenie</div></div>
    </div>
  </section>

</main>

<footer>
  <div class="stamp">good 4 u &middot; guts era &middot; purple hearts only</div>
  raport wygenerowany na podstawie Twojej historii Spotify ({stats['year_range']})
</footer>

<script>
const purple = 'rgba(139,63,212,0.85)';
const purpleBright = 'rgba(176,107,255,0.95)';
const pink = 'rgba(255,110,199,0.9)';
const lilac = '#e9d5ff';
const muted = '#b199c9';
const gridColor = 'rgba(217,184,255,0.12)';

// Bezpieczne tworzenie wykresu - jeśli jeden się wysypie (albo Chart.js
// w ogóle się nie załaduje z CDN, np. brak internetu), nie blokuje to
// renderowania pozostałych wykresów na stronie.
function safeChart(canvasId, config) {{
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  try {{
    if (typeof Chart === 'undefined') {{
      throw new Error('Biblioteka Chart.js się nie załadowała (sprawdź połączenie z internetem).');
    }}
    new Chart(canvas, config);
  }} catch (err) {{
    console.error('Błąd wykresu ' + canvasId + ':', err);
    const wrap = canvas.closest('.chart-wrap') || canvas.parentElement;
    if (wrap) {{
      wrap.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#b199c9;font-size:13px;text-align:center;padding:20px;">'
        + '⚠️ Nie udało się załadować wykresu.<br>Sprawdź połączenie z internetem (wykresy wymagają Chart.js z CDN) i odśwież stronę.</div>';
    }}
  }}
}}

if (typeof Chart !== 'undefined') {{
  Chart.defaults.color = muted;
  Chart.defaults.font.family = "'Space Grotesk', sans-serif";
}}

safeChart('trendChart', {{
  type: 'line',
  data: {{
    labels: {month_labels_js},
    datasets: [{{
      label: 'Minuty słuchania / miesiąc',
      data: {month_minutes_js},
      borderColor: purpleBright,
      backgroundColor: 'rgba(176,107,255,0.18)',
      fill: true,
      tension: 0.35,
      pointRadius: 2,
      pointBackgroundColor: pink,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ labels: {{ color: lilac }} }} }},
    scales: {{
      x: {{ grid: {{ color: gridColor }}, ticks: {{ maxTicksLimit: 12 }} }},
      y: {{ grid: {{ color: gridColor }} }}
    }}
  }}
}});

safeChart('albumChart', {{
  type: 'bar',
  data: {{
    labels: {album_labels_js},
    datasets: [{{
      label: 'Minuty',
      data: {album_minutes_js},
      backgroundColor: purple,
      borderRadius: 6,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ color: gridColor }} }},
      y: {{ grid: {{ display: false }}, ticks: {{ color: lilac, font: {{size: 11}} }} }}
    }}
  }}
}});

safeChart('hourChart', {{
  type: 'bar',
  data: {{
    labels: {hour_labels_js},
    datasets: [{{
      label: 'Odtworzenia wg godziny',
      data: {hour_dist_js},
      backgroundColor: pink,
      borderRadius: 4,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }}, title: {{ display: true, text: 'Pora dnia', color: lilac }} }},
    scales: {{
      x: {{ grid: {{ display: false }}, ticks: {{ maxTicksLimit: 12 }} }},
      y: {{ grid: {{ color: gridColor }} }}
    }}
  }}
}});

safeChart('weekdayChart', {{
  type: 'polarArea',
  data: {{
    labels: {weekday_labels_js},
    datasets: [{{
      data: {weekday_dist_js},
      backgroundColor: ['#4b1477','#5e1c94','#722bb3','#8b3fd4','#a558e6','#c17bff','#ff6ec7'],
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ position: 'bottom', labels: {{ color: lilac, font: {{size: 10}} }} }},
      title: {{ display: true, text: 'Dzień tygodnia', color: lilac }} }},
    scales: {{ r: {{ grid: {{ color: gridColor }}, ticks: {{ display: false }} }} }}
  }}
}});
</script>

</body>
</html>
"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

# Main

def main():
    parser = argparse.ArgumentParser(description="Generator raportu słuchania Spotify")
    parser.add_argument("input_path", nargs="?", default=DATA_PATH,
                         help="Ścieżka do folderu z danymi lub pliku ZIP eksportu Spotify")
    parser.add_argument("--artist", default="Olivia Rodrigo", help="Nazwa artysty (domyślnie: Olivia Rodrigo)")
    parser.add_argument("--out", default="guts_tour_wrapped.html", help="Nazwa pliku wyjściowego HTML")
    parser.add_argument("--year-min", type=int, default=YEAR_MIN)
    parser.add_argument("--year-max", type=int, default=YEAR_MAX)
    args = parser.parse_args()

    if not args.input_path:
        print("Brak ścieżki do danych. Ustaw zmienną DATA_PATH na górze pliku")
        print("albo podaj ścieżkę jako argument: python generate_olivia_report.py <ścieżka>")
        sys.exit(1)

    print(f"Wczytuję dane z: {args.input_path}")
    records = load_records(args.input_path)
    print(f"Wczytano {len(records)} rekordów odtworzeń.")

    filtered = filter_artist_years(records, args.artist, args.year_min, args.year_max)
    print(f"Znaleziono {len(filtered)} odtworzeń artysty '{args.artist}' w latach {args.year_min}-{args.year_max}.")

    if not filtered:
        print("Brak danych dla podanego artysty/zakresu lat. Sprawdź pisownię nazwy artysty.")
        sys.exit(1)

    stats = compute_stats(filtered, args.artist)
    render_html(stats, args.out)
    print(f"Gotowe! Raport zapisany jako: {args.out}")


if __name__ == "__main__":
    main()