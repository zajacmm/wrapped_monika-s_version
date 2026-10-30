
import json
import glob
import os
import html
from collections import Counter, defaultdict
from datetime import datetime, timedelta


# Ścieżki liczone względem położenia skryptu, niezależnie od katalogu uruchomienia.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FOLDER = os.path.join(SCRIPT_DIR, '..', 'spotify_data')

# Zakres lat do analizy (włącznie)
YEAR_FROM = 2022
YEAR_TO = 2026

# Artysta, którego dotyczy raport (dokładna nazwa jak w danych Spotify)
ARTIST_NAME = "Taylor Swift"

# Próg (w milisekundach), od którego odsłuch liczy się jako "pełny"
# (Spotify sam stosuje podobną logikę ~30s przy raportowaniu odtworzeń)
REAL_PLAY_THRESHOLD_MS = 30_000

# Liczba dni "wstecz" od najnowszego wpisu w danych, traktowana jako
# "obecna era" 
CURRENT_ERA_WINDOW_DAYS = 90

# Plik wyjściowy
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "twoj_eras_tour_spotify_1.html")

# Przybliżone przesunięcie strefy czasowej względem UTC używane tylko
# do wykresu "pora dnia" (dane Spotify są w UTC). Dla Polski to +1 (zima)
# / +2 (lato) — dla uproszczenia przyjmujemy stałe +2h. 
LOCAL_TZ_OFFSET_HOURS = 2


# MAPA ER — kojarzy nazwę albumu z danych Spotify z "erą" Taylor Swift

ERA_ORDER = [
    'Debut', 'Fearless', 'Fearless (TV)', 'Speak Now', 'Speak Now (TV)',
    'Red', 'Red (TV)', '1989', '1989 (TV)', 'reputation', 'Lover',
    'folklore', 'evermore', 'Midnights', 'TTPD', 'Showgirl',
]

ERA_LABELS_PL = {
    'Debut': 'Taylor Swift',
    'Fearless': 'Fearless',
    'Fearless (TV)': "Fearless (Taylor's Version)",
    'Speak Now': 'Speak Now',
    'Speak Now (TV)': "Speak Now (Taylor's Version)",
    'Red': 'Red',
    'Red (TV)': "Red (Taylor's Version)",
    '1989': '1989',
    '1989 (TV)': "1989 (Taylor's Version)",
    'reputation': 'reputation',
    'Lover': 'Lover',
    'folklore': 'folklore',
    'evermore': 'evermore',
    'Midnights': 'Midnights',
    'TTPD': 'THE TORTURED POETS DEPARTMENT',
    'Showgirl': 'The Life of a Showgirl'
}

ERA_COLORS = {
    'Debut': '#7fae60',
    'Fearless': '#e8c777',
    'Fearless (TV)': '#e8c777',
    'Speak Now': '#a878c9',
    'Speak Now (TV)': '#a878c9',
    'Red': '#b3413e',
    'Red (TV)': '#b3413e',
    '1989': '#a9d4e8',
    '1989 (TV)': '#a9d4e8',
    'reputation': '#5a5a5a',
    'Lover': '#e8a3c0',
    'folklore': '#9a9584',
    'evermore': '#b06a3a',
    'Midnights': '#4a5a8a',
    'TTPD': '#d9d3c7',
    'Showgirl': '#e0932e',
    'Other': '#888888',
}

# Nazwa albumu (dokładnie jak w polu master_metadata_album_album_name)
# -> nazwa ery. 
ALBUM_TO_ERA = {
    'Taylor Swift': 'Debut',
    'The Taylor Swift Holiday Collection': 'Debut',
    'Christmas Tree Farm': 'Debut',

    'Fearless - Big Machine Radio Release Special': 'Fearless',
    "Fearless (Taylor's Version)": 'Fearless (TV)',
    "Eyes Open (Taylor's Version)": 'Fearless (TV)',
    "Safe & Sound (Taylor's Version)": 'Fearless (TV)',
    'Love Story (Taylor’s Version)': 'Fearless (TV)',
    "Love Story (Taylor's Version)": 'Fearless (TV)',

    'Speak Now': 'Speak Now',
    "Speak Now (Taylor's Version)": 'Speak Now (TV)',
    'Speak Now World Tour Live': 'Speak Now (TV)',
    'If This Was A Movie (Taylor’s Version)': 'Speak Now (TV)',

    'Red': 'Red',
    'The Hunger Games: Songs From District 12 And Beyond': 'Red',
    "Red (Taylor's Version)": 'Red (TV)',
    'All Too Well (Sad Girl Autumn Version) - Recorded at Long Pond Studios': 'Red (TV)',

    '1989': '1989',
    "1989 (Taylor's Version)": '1989 (TV)',
    "Wildest Dreams (Taylor's Version)": '1989 (TV)',
    'This Love (Taylor’s Version)': '1989 (TV)',

    'reputation': 'reputation',
    'reputation Stadium Tour Surprise Song Playlist': 'reputation',
    'Bad Blood': 'reputation',

    'Lover': 'Lover',
    "Lover (Remix) [feat. Shawn Mendes]": 'Lover',
    'The Man': 'Lover',
    'The Archer': 'Lover',
    'You Need To Calm Down': 'Lover',
    'Daylight': 'Lover',
    'All Of The Girls You Loved Before': 'Lover',
    'The Cruelest Summer': 'Lover',

    'folklore': 'folklore',
    'folklore: the long pond studio sessions (from the Disney+ special)': 'folklore',
    'folklore: the long pond studio sessions (from the Disney+ special) - deluxe edition': 'folklore',
    'cardigan': 'folklore',
    'the lakes': 'folklore',
    'Carolina': 'folklore',

    'evermore': 'evermore',
    'willow': 'evermore',

    'Midnights': 'Midnights',
    'Bejeweled': 'Midnights',
    'Lavender Haze': 'Midnights',
    'Anti-Hero': 'Midnights',
    "You're Losing Me (From The Vault)": 'Midnights',

    'THE TORTURED POETS DEPARTMENT': 'TTPD',
    'THE TORTURED POETS DEPARTMENT: THE ANTHOLOGY': 'TTPD',
    'Fortnight': 'TTPD',
    'I Can Do It With a Broken Heart': 'TTPD',

    'The Life of a Showgirl': 'Showgirl',
    'The Life of a Showgirl + Acoustic Collection': 'Showgirl',
    'The Fate of Ophelia': 'Showgirl',
    'Opalite': 'Showgirl',
    'I Knew It, I Knew You': 'Showgirl',
    'The Life of a Showgirl: The Encore': 'Showgirl',
}

WEEKDAY_ORDER_PL = ['Poniedziałek', 'Wtorek', 'Środa', 'Czwartek', 'Piątek', 'Sobota', 'Niedziela']
WEEKDAY_SHORT_PL = ['Pon', 'Wt', 'Śr', 'Czw', 'Pt', 'Sob', 'Nd']
MONTH_SHORT_PL = {'01': 'sty', '02': 'lut', '03': 'mar', '04': 'kwi', '05': 'maj', '06': 'cze',
                   '07': 'lip', '08': 'sie', '09': 'wrz', '10': 'paź', '11': 'lis', '12': 'gru'}


def get_era(album_name):
    return ALBUM_TO_ERA.get(album_name, 'Other')


# 1. WCZYTYWANIE DANYCH

def load_records(data_folder, artist_name, year_from, year_to):
    pattern = os.path.join(data_folder, "Streaming_History_Audio_*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"Nie znaleziono plików 'Streaming_History_Audio_*.json' w: {data_folder}\n"
            f"Sprawdź ścieżkę DATA_FOLDER na górze skryptu."
        )

    records = []
    for fn in files:
        with open(fn, encoding='utf-8') as f:
            data = json.load(f)
        for d in data:
            if d.get('master_metadata_album_artist_name') != artist_name:
                continue
            ts = d.get('ts')
            if not ts:
                continue
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            if not (year_from <= dt.year <= year_to):
                continue
            d['_dt'] = dt
            d['_year'] = dt.year
            d['_era'] = get_era(d.get('master_metadata_album_album_name'))
            records.append(d)

    if not records:
        raise ValueError(
            f"Nie znaleziono żadnych odsłuchań artysty '{artist_name}' w latach "
            f"{year_from}-{year_to}. Sprawdź ARTIST_NAME i zakres lat."
        )
    return records


# 2. ANALIZA

def era_order_sort(items):
    return sorted(items, key=lambda x: ERA_ORDER.index(x['era']) if x['era'] in ERA_ORDER else 999)


def analyze(records, year_from, year_to, real_play_threshold_ms, current_era_window_days, tz_offset_hours):
    real = [r for r in records if r['ms_played'] >= real_play_threshold_ms]
    if not real:
        raise ValueError("Brak odsłuchów dłuższych niż próg REAL_PLAY_THRESHOLD_MS — obniż próg.")

    years = list(range(year_from, year_to + 1))
    per_year = {}
    for y in years:
        yr = [r for r in real if r['_year'] == y]
        if not yr:
            continue
        yr_ms = sum(r['ms_played'] for r in yr)
        era_counter = Counter(r['_era'] for r in yr)
        song_counter = Counter()
        for r in yr:
            name = r.get('master_metadata_track_name')
            if name:
                song_counter[name] += 1
        era_total = sum(c for e, c in era_counter.items() if e != 'Other')
        era_breakdown = [
            {'era': e, 'count': c, 'pct': round(c / era_total * 100, 1) if era_total else 0,
             'color': ERA_COLORS.get(e, '#888')}
            for e, c in era_counter.most_common() if e != 'Other'
        ]
        per_year[y] = {
            'plays': len(yr),
            'minutes': round(yr_ms / 60000),
            'hours': round(yr_ms / 3600000, 1),
            'top_era': era_counter.most_common(1)[0][0] if era_counter else None,
            'era_breakdown': era_breakdown,
            'top_songs': [{'name': n, 'count': c} for n, c in song_counter.most_common(5)],
        }

    # All-time era breakdown
    era_counter_all = Counter()
    era_ms_all = defaultdict(int)
    for r in real:
        era_counter_all[r['_era']] += 1
        era_ms_all[r['_era']] += r['ms_played']
    era_total_all = sum(c for e, c in era_counter_all.items() if e != 'Other')
    alltime_era_breakdown = [
        {'era': e, 'count': c, 'minutes': round(era_ms_all[e] / 60000),
         'pct': round(c / era_total_all * 100, 1) if era_total_all else 0,
         'color': ERA_COLORS.get(e, '#888')}
        for e, c in era_counter_all.most_common() if e != 'Other'
    ]

    # Current era (last N days)
    max_date = max(r['_dt'] for r in records)
    cutoff = max_date - timedelta(days=current_era_window_days)
    recent = [r for r in real if r['_dt'] >= cutoff]
    recent_era_counter = Counter(r['_era'] for r in recent)
    recent_song_counter = Counter()
    for r in recent:
        name = r.get('master_metadata_track_name')
        if name:
            recent_song_counter[name] += 1
    current_era_list = [{'era': e, 'count': c} for e, c in recent_era_counter.most_common(5) if e != 'Other']
    current_top_songs = [{'name': n, 'count': c} for n, c in recent_song_counter.most_common(8)]

    # All-time top songs
    song_counter_all = Counter()
    song_album = {}
    song_ms = defaultdict(int)
    for r in real:
        name = r.get('master_metadata_track_name')
        if name:
            song_counter_all[name] += 1
            song_album[name] = r.get('master_metadata_album_album_name')
            song_ms[name] += r['ms_played']
    alltime_top_songs = [
        {'name': n, 'count': c, 'album': song_album[n], 'minutes': round(song_ms[n] / 60000)}
        for n, c in song_counter_all.most_common(15)
    ]

    # Hour of day / weekday
    hour_counter = Counter()
    weekday_counter = Counter()
    for r in real:
        local_hour = (r['_dt'].hour + tz_offset_hours) % 24
        hour_counter[local_hour] += 1
        weekday_counter[WEEKDAY_ORDER_PL[r['_dt'].weekday()]] += 1

    # Skip / shuffle rate (na wszystkich rekordach, nie tylko "realnych")
    skipped_count = sum(1 for r in records if r.get('skipped'))
    skip_rate = round(skipped_count / len(records) * 100, 1) if records else 0
    shuffle_count = sum(1 for r in real if r.get('shuffle'))
    shuffle_rate = round(shuffle_count / len(real) * 100, 1) if real else 0

    # Taylor's Version vs oryginały (heurystyka po nazwie albumu)
    tv_plays = sum(
        1 for r in real
        if r.get('master_metadata_album_album_name') and
        ("Taylor's Version" in r['master_metadata_album_album_name'] or
         "Taylor’s Version" in r['master_metadata_album_album_name'])
    )

    # Monthly trend
    monthly = Counter()
    for r in real:
        key = f"{r['_year']}-{r['_dt'].month:02d}"
        monthly[key] += 1
    monthly_sorted = sorted(monthly.items())

    # Most obsessive single day (most repeats of one song in one day)
    daily_song = defaultdict(Counter)
    for r in real:
        day_key = r['_dt'].strftime('%Y-%m-%d')
        name = r.get('master_metadata_track_name')
        if name:
            daily_song[day_key][name] += 1
    max_obsession = None
    for day, counter in daily_song.items():
        song, cnt = counter.most_common(1)[0]
        if max_obsession is None or cnt > max_obsession[2]:
            max_obsession = (day, song, cnt)

    # Longest listening day (total minutes)
    daily_minutes = defaultdict(int)
    for r in records:
        day_key = r['_dt'].strftime('%Y-%m-%d')
        daily_minutes[day_key] += r['ms_played']
    top_day = max(daily_minutes.items(), key=lambda x: x[1])

    unique_songs = len(set(r.get('master_metadata_track_name') for r in real if r.get('master_metadata_track_name')))

    all_dt = sorted(r['_dt'] for r in records)
    total_ms = sum(r['ms_played'] for r in records)

    return {
        'total_plays': len(records),
        'real_plays': len(real),
        'total_hours': round(total_ms / 3600000, 1),
        'total_days': round(total_ms / 3600000 / 24, 1),
        'per_year': per_year,
        'alltime_era_breakdown': alltime_era_breakdown,
        'current_era_list': current_era_list,
        'current_top_songs': current_top_songs,
        'alltime_top_songs': alltime_top_songs,
        'hour_counter': dict(hour_counter),
        'weekday_counter': dict(weekday_counter),
        'skip_rate': skip_rate,
        'shuffle_rate': shuffle_rate,
        'tv_plays': tv_plays,
        'monthly': monthly_sorted,
        'max_obsession': max_obsession,
        'top_day': [top_day[0], round(top_day[1] / 60000)],
        'unique_songs': unique_songs,
        'first_listen': all_dt[0],
        'last_listen': all_dt[-1],
    }


# 3. GENEROWANIE HTML

def esc(s):
    return html.escape(str(s), quote=True)


def ribbon_html(era_breakdown, min_pct_label=4.0):
    ordered = era_order_sort(era_breakdown)
    segs = []
    for e in ordered:
        w = e['pct']
        label = ERA_LABELS_PL.get(e['era'], e['era'])
        show_label = w >= min_pct_label
        segs.append(
            f'<div class="ribbon-seg" style="flex-grow:{max(w,0.15)};background:{e["color"]}" '
            f'title="{esc(label)} — {e["count"]} odsłuchań ({w}%)">'
            + (f'<span>{esc(e["era"])}</span>' if show_label else '')
            + '</div>'
        )
    return '<div class="ribbon">' + ''.join(segs) + '</div>'


def legend_html(era_breakdown):
    ordered = era_order_sort(era_breakdown)
    chips = []
    for e in ordered:
        chips.append(f'<span class="chip"><i style="background:{e["color"]}"></i>{esc(e["era"])} · {e["pct"]}%</span>')
    return '<div class="legend">' + ''.join(chips) + '</div>'


YEAR_NIGHT_ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII']


def build_years_section(stats, year_from, year_to):
    blocks = []
    for idx, y in enumerate(range(year_from, year_to + 1)):
        yd = stats['per_year'].get(y)
        if not yd:
            continue
        night_label = f"NOC {YEAR_NIGHT_ROMAN[idx] if idx < len(YEAR_NIGHT_ROMAN) else idx+1}"
        top_era_label = ERA_LABELS_PL.get(yd['top_era'], yd['top_era'])
        songs_html = ''.join(
            f'<li><span class="rank">{i+1:02d}</span><span class="sname">{esc(s["name"])}</span>'
            f'<span class="scount">{s["count"]}×</span></li>'
            for i, s in enumerate(yd['top_songs'])
        )
        blocks.append(f'''
    <article class="night">
      <div class="night-head">
        <span class="night-eyebrow">{night_label} · {y}</span>
        <h3 class="night-title">Era przewodnia: {esc(top_era_label)}</h3>
      </div>
      <div class="night-stats">
        <div><strong>{yd['hours']:.0f}</strong><span>godzin</span></div>
        <div><strong>{yd['plays']}</strong><span>odsłuchań</span></div>
      </div>
      {ribbon_html(yd['era_breakdown'])}
      {legend_html(yd['era_breakdown'])}
      <ol class="setlist-mini">{songs_html}</ol>
    </article>
    ''')
    return '\n'.join(blocks)


def build_leaderboard(stats):
    rows = []
    if not stats['alltime_era_breakdown']:
        return ''
    max_min = max(e['minutes'] for e in stats['alltime_era_breakdown'])
    for i, e in enumerate(stats['alltime_era_breakdown']):
        label = ERA_LABELS_PL.get(e['era'], e['era'])
        w = round(e['minutes'] / max_min * 100, 1) if max_min else 0
        h, m = divmod(e['minutes'], 60)
        rows.append(f'''
    <div class="lb-row">
      <span class="lb-rank">{i+1:02d}</span>
      <span class="lb-name">{esc(e['era'])}<small>{esc(label)}</small></span>
      <div class="lb-bar-track"><div class="lb-bar" style="width:{w}%;background:{e['color']}"></div></div>
      <span class="lb-val">{h}h {m}m<small>{e['pct']}%</small></span>
    </div>''')
    return ''.join(rows)


def build_top15(stats):
    rows = []
    for i, s in enumerate(stats['alltime_top_songs']):
        era_guess = None
        for e in ERA_ORDER:
            if ERA_LABELS_PL.get(e) == s['album']:
                era_guess = e
                break
        color = ERA_COLORS.get(era_guess, '#8a8478')
        rows.append(f'''
    <li class="setlist-row" style="--accent:{color}">
      <span class="sl-num">{i+1:02d}</span>
      <span class="sl-name">{esc(s['name'])}<small>{esc(s['album'] or '')}</small></span>
      <span class="sl-count">{s['count']}<small>odsłuchań</small></span>
      <span class="sl-min">{s['minutes']}<small>min</small></span>
    </li>''')
    return ''.join(rows)


def build_current_era(stats):
    cur_list = stats['current_era_list']
    if not cur_list:
        return {'top_era': {'era': '—'}, 'second': None, 'bars': '', 'songs': ''}
    cur_max = max(c['count'] for c in cur_list)
    bars = ''.join(
        f'<div class="cur-bar-row"><span>{esc(c["era"])}</span>'
        f'<div class="cur-bar-track"><div class="cur-bar" style="width:{round(c["count"]/cur_max*100,1)}%;'
        f'background:{ERA_COLORS.get(c["era"],"#888")}"></div></div><span class="cur-count">{c["count"]}</span></div>'
        for c in cur_list
    )
    songs = ''.join(f'<span class="tag">{esc(s["name"])} <b>{s["count"]}×</b></span>' for s in stats['current_top_songs'][:6])
    return {'top_era': cur_list[0], 'second': cur_list[1] if len(cur_list) > 1 else None, 'bars': bars, 'songs': songs}


def build_hour_chart(stats):
    hours = {int(k): v for k, v in stats['hour_counter'].items()}
    max_hour = max(hours.values()) if hours else 1
    return ''.join(
        f'<div class="hbar" style="height:{round(hours.get(h,0)/max_hour*100,1)}%" '
        f'title="{h}:00 — {hours.get(h,0)} odsłuchań"><span>{h}</span></div>'
        for h in range(24)
    )


def build_weekday_chart(stats):
    wd = stats['weekday_counter']
    max_wd = max(wd.values()) if wd else 1
    return ''.join(
        f'<div class="wbar-row"><span class="wd-label">{WEEKDAY_SHORT_PL[i]}</span>'
        f'<div class="wbar-track"><div class="wbar" style="width:{round(wd.get(d,0)/max_wd*100,1)}%"></div></div>'
        f'<span class="wd-val">{wd.get(d,0)}</span></div>'
        for i, d in enumerate(WEEKDAY_ORDER_PL)
    )


def build_month_chart(stats):
    monthly = stats['monthly']
    if not monthly:
        return ''
    max_month = max(v for _, v in monthly)
    bars = []
    for k, v in monthly:
        show_label = k.endswith(('01', '07'))
        label = f'<span>{MONTH_SHORT_PL[k[5:7]]} \'{k[2:4]}</span>' if show_label else ''
        h = round(v / max_month * 100, 1) if max_month else 0
        bars.append(f'<div class="mbar" style="height:{h}%" title="{k} — {v} odsłuchań">{label}</div>')
    return ''.join(bars)


CSS = '''
:root {
  --bg: #0b0b10; --bg-alt: #121218; --card: #17171f; --card-2: #1c1c25;
  --hair: rgba(244,239,227,0.10); --hair-strong: rgba(244,239,227,0.18);
  --text: #f4efe3; --text-dim: #b8b2a2; --text-dimmer: #7c766a;
  --gold: #e0932e; --gold-light: #f0c896; --rose: #e8a3c0; --lav: #4a5a8a;
  --max-w: 980px;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--bg);
  background-image:
    radial-gradient(ellipse 900px 500px at 15% -10%, rgba(224,147,46,0.10), transparent 60%),
    radial-gradient(ellipse 700px 500px at 90% 10%, rgba(74,90,138,0.14), transparent 60%);
  color: var(--text); font-family: 'Work Sans', sans-serif; font-weight: 400; line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
h1, h2, h3, .display { font-family: 'Playfair Display', serif; margin: 0; }
.mono { font-family: 'Space Mono', monospace; }
.wrap { max-width: var(--max-w); margin: 0 auto; padding: 0 24px; }
a { color: inherit; }
.hero { position: relative; padding: 96px 24px 70px; text-align: center; border-bottom: 1px solid var(--hair); overflow: hidden; }
.hero::before { content: ""; position: absolute; inset: 0;
  background: repeating-linear-gradient(115deg, rgba(244,239,227,0.025) 0px, rgba(244,239,227,0.025) 1px, transparent 1px, transparent 64px);
  pointer-events: none; }
.hero-eyebrow { font-family: 'Space Mono', monospace; letter-spacing: 0.35em; font-size: 11px; color: var(--gold-light);
  text-transform: uppercase; margin-bottom: 22px; }
.hero-eyebrow::before, .hero-eyebrow::after { content: "✦"; margin: 0 12px; opacity: 0.7; }
.hero h1 { font-size: clamp(40px, 8vw, 84px); font-weight: 800; line-height: 1.02; letter-spacing: -0.01em; }
.hero h1 em { font-style: italic; font-weight: 600; color: var(--gold); }
.hero-sub { margin-top: 20px; font-size: 17px; color: var(--text-dim); max-width: 560px; margin-left: auto; margin-right: auto; }
.hero-number { margin-top: 46px; display: flex; justify-content: center; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.hero-number .big { font-family: 'Playfair Display', serif; font-weight: 800; font-style: italic; font-size: clamp(70px, 16vw, 150px);
  line-height: 1; background: linear-gradient(180deg, var(--gold-light), var(--gold) 70%);
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.hero-number .lbl { font-family: 'Space Mono', monospace; font-size: 15px; letter-spacing: 0.08em; color: var(--text-dim);
  text-transform: uppercase; padding-bottom: 14px; }
.hero-meta { margin-top: 12px; font-family: 'Space Mono', monospace; font-size: 13px; color: var(--text-dimmer); }
.tickets { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 14px; padding: 46px 24px;
  max-width: var(--max-w); margin: 0 auto; }
.ticket { position: relative; background: var(--card); border: 1px dashed var(--hair-strong); border-radius: 10px;
  padding: 18px 16px; text-align: left; }
.ticket::before, .ticket::after { content: ""; position: absolute; width: 14px; height: 14px; background: var(--bg);
  border-radius: 50%; top: 50%; transform: translateY(-50%); }
.ticket::before { left: -8px; } .ticket::after { right: -8px; }
.ticket .t-val { font-family: 'Space Mono', monospace; font-size: 24px; font-weight: 700; color: var(--gold-light); display: block; }
.ticket .t-lbl { font-size: 12px; color: var(--text-dim); margin-top: 4px; display: block; }
section { padding: 70px 24px; border-top: 1px solid var(--hair); }
.section-inner { max-width: var(--max-w); margin: 0 auto; }
.section-eyebrow { font-family: 'Space Mono', monospace; font-size: 11px; letter-spacing: 0.28em; text-transform: uppercase;
  color: var(--gold); margin-bottom: 10px; }
.section-title { font-size: clamp(28px, 4.5vw, 42px); font-weight: 700; margin-bottom: 8px; }
.section-title em { color: var(--gold); font-style: italic; }
.section-desc { color: var(--text-dim); max-width: 620px; font-size: 15.5px; margin-bottom: 40px; }
.spotlight { background: linear-gradient(155deg, rgba(224,147,46,0.14), rgba(23,23,31,0.4) 55%); border: 1px solid var(--hair-strong);
  border-radius: 18px; padding: 40px; }
.spotlight-top { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 20px; margin-bottom: 28px; }
.spotlight-era { font-size: clamp(30px,5vw,46px); font-weight: 700; }
.spotlight-note { color: var(--text-dim); font-size: 14px; max-width: 320px; }
.cur-bar-row { display: grid; grid-template-columns: 110px 1fr 40px; align-items: center; gap: 12px; margin-bottom: 10px; font-size: 13.5px; }
.cur-bar-track { background: rgba(244,239,227,0.08); border-radius: 6px; height: 10px; overflow: hidden; }
.cur-bar { height: 100%; border-radius: 6px; }
.cur-count { text-align: right; font-family: 'Space Mono', monospace; color: var(--text-dim); }
.tag-row { margin-top: 26px; display: flex; flex-wrap: wrap; gap: 8px; }
.tag { background: rgba(244,239,227,0.07); border: 1px solid var(--hair-strong); border-radius: 20px; padding: 6px 14px;
  font-size: 13px; color: var(--text-dim); }
.tag b { color: var(--gold-light); font-weight: 600; margin-left: 4px; }
.ribbon { display: flex; width: 100%; height: 34px; border-radius: 6px; overflow: hidden; margin: 20px 0 14px;
  border: 1px solid rgba(0,0,0,0.3); }
.ribbon-seg { display: flex; align-items: center; justify-content: center; min-width: 4px; position: relative;
  border-right: 1px solid rgba(0,0,0,0.25); }
.ribbon-seg span { font-size: 9.5px; font-family: 'Space Mono', monospace; color: rgba(10,10,10,0.72); font-weight: 700;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 0 4px; }
.legend { display: flex; flex-wrap: wrap; gap: 10px 16px; margin-bottom: 22px; }
.chip { display: flex; align-items: center; font-size: 12px; color: var(--text-dim); }
.chip i { width: 9px; height: 9px; border-radius: 50%; display: inline-block; margin-right: 6px; }
.night { background: var(--card); border: 1px solid var(--hair); border-radius: 16px; padding: 32px 32px 28px; margin-bottom: 22px; }
.night-eyebrow { font-family: 'Space Mono', monospace; font-size: 11px; letter-spacing: 0.2em; color: var(--gold); text-transform: uppercase; }
.night-title { font-size: 26px; font-weight: 700; margin-top: 8px; }
.night-stats { display: flex; gap: 30px; margin: 20px 0 4px; }
.night-stats strong { font-family: 'Space Mono', monospace; font-size: 22px; color: var(--gold-light); display:block; }
.night-stats span { font-size: 11px; color: var(--text-dimmer); text-transform: uppercase; letter-spacing: 0.06em; }
.setlist-mini { list-style: none; margin: 18px 0 0; padding: 0; border-top: 1px solid var(--hair); }
.setlist-mini li { display: flex; align-items: center; gap: 14px; padding: 10px 0; border-bottom: 1px solid var(--hair); font-size: 14.5px; }
.setlist-mini .rank { font-family: 'Space Mono', monospace; color: var(--text-dimmer); font-size: 12px; width: 20px; }
.setlist-mini .sname { flex: 1; }
.setlist-mini .scount { font-family: 'Space Mono', monospace; color: var(--gold-light); font-size: 13px; }
.lb-row { display: grid; grid-template-columns: 34px 1fr 1fr 90px; align-items: center; gap: 14px; padding: 11px 0;
  border-bottom: 1px solid var(--hair); font-size: 14px; }
.lb-rank { font-family: 'Space Mono', monospace; color: var(--text-dimmer); }
.lb-name small { display: block; color: var(--text-dimmer); font-size: 11px; margin-top: 2px; }
.lb-bar-track { background: rgba(244,239,227,0.06); border-radius: 5px; height: 9px; overflow: hidden; }
.lb-bar { height: 100%; border-radius: 5px; }
.lb-val { text-align: right; font-family: 'Space Mono', monospace; color: var(--gold-light); }
.lb-val small { display: block; color: var(--text-dimmer); font-size: 10.5px; font-family: 'Work Sans', sans-serif; }
.setlist-board { list-style: none; margin: 0; padding: 0; }
.setlist-row { --accent: #e0932e; display: grid; grid-template-columns: 46px 1fr 90px 70px; align-items: center; gap: 16px;
  padding: 16px 18px; border-left: 3px solid var(--accent); background: var(--card); border-radius: 8px; margin-bottom: 8px; }
.sl-num { font-family: 'Playfair Display', serif; font-style: italic; font-weight: 700; font-size: 22px; color: var(--accent); }
.sl-name { font-size: 15.5px; font-weight: 500; }
.sl-name small { display: block; color: var(--text-dimmer); font-size: 12px; font-weight: 400; margin-top: 2px; }
.sl-count, .sl-min { text-align: right; font-family: 'Space Mono', monospace; font-size: 15px; color: var(--text); }
.sl-count small, .sl-min small { display: block; font-size: 9.5px; color: var(--text-dimmer); font-family: 'Work Sans', sans-serif;
  text-transform: uppercase; }
.stats-grid { display: grid; grid-template-columns: 1.3fr 1fr; gap: 20px; }
@media (max-width: 760px) { .stats-grid { grid-template-columns: 1fr; } }
.stat-card { background: var(--card); border: 1px solid var(--hair); border-radius: 16px; padding: 26px 28px; }
.stat-card h4 { font-family: 'Space Mono', monospace; font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase;
  color: var(--text-dim); margin: 0 0 18px; }
.hour-chart { display: flex; align-items: flex-end; gap: 3px; height: 110px; }
.hbar { flex: 1; background: linear-gradient(180deg, var(--gold), rgba(224,147,46,0.25)); border-radius: 3px 3px 0 0;
  min-height: 3px; position: relative; }
.hbar span { position: absolute; bottom: -18px; left: 50%; transform: translateX(-50%); font-size: 8px; color: var(--text-dimmer);
  font-family: 'Space Mono', monospace; }
.hour-chart-wrap { padding-bottom: 22px; }
.month-chart { display: flex; align-items: flex-end; gap: 2px; height: 100px; margin-top: 6px; }
.mbar { flex: 1; background: rgba(74,90,138,0.55); border-radius: 2px 2px 0 0; min-height: 2px; position: relative; }
.mbar span { position: absolute; bottom: -16px; left: 0; font-size: 8px; color: var(--text-dimmer);
  font-family: 'Space Mono', monospace; white-space: nowrap; }
.month-chart-wrap { padding-bottom: 20px; }
.wbar-row { display: grid; grid-template-columns: 34px 1fr 34px; align-items: center; gap: 10px; margin-bottom: 9px; font-size: 12.5px; }
.wbar-track { background: rgba(244,239,227,0.06); border-radius: 5px; height: 9px; overflow: hidden; }
.wbar { height: 100%; background: var(--rose); border-radius: 5px; }
.wd-val { text-align: right; font-family: 'Space Mono', monospace; color: var(--text-dim); }
.duo-bar { display: flex; height: 40px; border-radius: 8px; overflow: hidden; margin: 14px 0; }
.duo-bar div:first-child { background: var(--gold); }
.duo-bar div:last-child { background: rgba(244,239,227,0.1); }
.duo-legend { display: flex; justify-content: space-between; font-size: 12.5px; color: var(--text-dim); }
.callout { background: var(--card-2); border: 1px solid var(--hair); border-radius: 14px; padding: 20px 22px; margin-top: 16px; }
.callout .cal-num { font-family: 'Playfair Display', serif; font-style: italic; font-weight: 700; font-size: 30px; color: var(--gold-light); }
.callout p { margin: 6px 0 0; font-size: 13.5px; color: var(--text-dim); }
footer { text-align: center; padding: 60px 24px 80px; color: var(--text-dimmer); font-size: 13px; border-top: 1px solid var(--hair); }
footer .sig { font-family: 'Playfair Display', serif; font-style: italic; font-size: 20px; color: var(--text-dim); margin-bottom: 10px; }
'''


def build_html(stats, artist_name, year_from, year_to):
    cur = build_current_era(stats)
    years_section = build_years_section(stats, year_from, year_to)
    leaderboard_html = build_leaderboard(stats)
    top15_html = build_top15(stats)
    hour_bars = build_hour_chart(stats)
    wd_bars = build_weekday_chart(stats)
    month_bars = build_month_chart(stats)

    real_plays = stats['real_plays']
    tv_pct = round(stats['tv_plays'] / real_plays * 100, 1) if real_plays else 0
    orig_pct = round(100 - tv_pct, 1)

    obsession_day, obsession_song, obsession_cnt = stats['max_obsession'] if stats['max_obsession'] else ('—', '—', 0)
    obsession_day_fmt = datetime.strptime(obsession_day, '%Y-%m-%d').strftime('%d.%m.%Y') if obsession_day != '—' else '—'
    top_day, top_day_min = stats['top_day']
    top_day_fmt = datetime.strptime(top_day, '%Y-%m-%d').strftime('%d.%m.%Y')
    top_day_h, top_day_m = divmod(top_day_min, 60)

    current_note = ("Nowiutkie wydanie depcze jej po piętach — walka o Twoje uszy trwa."
                     if cur['second'] and cur['second']['era'] == 'Showgirl'
                     else "To Twoja obecna obsesja słuchowa.")

    return f'''<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Twój Eras Tour · Spotify Wrapped {year_from}–{year_to}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,500;0,600;0,700;0,800;1,600&family=Work+Sans:wght@300;400;500;600;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>

<header class="hero">
  <div class="hero-eyebrow">The Eras Tour · Twoja wersja</div>
  <h1>Twój prywatny <em>Eras&nbsp;Tour</em></h1>
  <p class="hero-sub">Pełna trasa koncertowa {esc(artist_name)} przez Twoją historię odsłuchań na Spotify — od {year_from} do {year_to}.</p>
  <div class="hero-number">
    <span class="big">{stats['total_hours']:.0f}</span>
    <span class="lbl">godzin<br>z {esc(artist_name.split()[0])}</span>
  </div>
  <div class="hero-meta">to {stats['total_days']} dni nieprzerwanego słuchania · {stats['total_plays']:,} odsłuchań ogółem</div>
</header>

<div class="tickets">
  <div class="ticket"><span class="t-val">{real_plays:,}</span><span class="t-lbl">pełnych odsłuchań (30s+)</span></div>
  <div class="ticket"><span class="t-val">{stats['unique_songs']}</span><span class="t-lbl">różnych utworów</span></div>
  <div class="ticket"><span class="t-val">{stats['skip_rate']}%</span><span class="t-lbl">wskaźnik pomijania</span></div>
  <div class="ticket"><span class="t-val">{stats['shuffle_rate']}%</span><span class="t-lbl">odtwarzane losowo</span></div>
  <div class="ticket"><span class="t-val">{stats['first_listen'].strftime('%d.%m.%Y')}</span><span class="t-lbl">pierwszy odsłuch w danych</span></div>
  <div class="ticket"><span class="t-val">{stats['last_listen'].strftime('%d.%m.%Y')}</span><span class="t-lbl">ostatni odsłuch w danych</span></div>
</div>

<section id="current-era">
  <div class="section-inner">
    <div class="section-eyebrow">Na scenie teraz</div>
    <h2 class="section-title">Twoja obecna <em>era</em></h2>
    <p class="section-desc">Na podstawie ostatnich {CURRENT_ERA_WINDOW_DAYS} dni odsłuchów — kto właśnie dostaje najwięcej Twojej uwagi.</p>
    <div class="spotlight">
      <div class="spotlight-top">
        <div><div class="spotlight-era">{esc(cur['top_era']['era'])}</div></div>
        <div class="spotlight-note">{current_note}</div>
      </div>
      {cur['bars']}
      <div class="tag-row">{cur['songs']}</div>
    </div>
  </div>
</section>

<section id="years">
  <div class="section-inner">
    <div class="section-eyebrow">Setlista trasy</div>
    <h2 class="section-title">Ery na przestrzeni <em>lat</em></h2>
    <p class="section-desc">Każdy rok to inna noc trasy — zobacz, jak zmieniała się Twoja era przewodnia rok po roku.</p>
    {years_section}
  </div>
</section>

<section id="leaderboard">
  <div class="section-inner">
    <div class="section-eyebrow">Ranking wszech czasów</div>
    <h2 class="section-title">Wszystkie ery, <em>jedna tabela</em></h2>
    <p class="section-desc">Łączny czas słuchania każdej ery w latach {year_from}–{year_to}, od najmocniejszej do najcichszej.</p>
    <div class="lb-list">{leaderboard_html}</div>
  </div>
</section>

<section id="top15">
  <div class="section-inner">
    <div class="section-eyebrow">Główny setlist</div>
    <h2 class="section-title">Top 15 utworów <em>wszech czasów</em></h2>
    <p class="section-desc">Piosenki, które grałaś najczęściej przez ostatnie lata.</p>
    <ol class="setlist-board">{top15_html}</ol>
  </div>
</section>

<section id="stats">
  <div class="section-inner">
    <div class="section-eyebrow">Backstage</div>
    <h2 class="section-title">Swiftie <em>statystyki</em></h2>
    <p class="section-desc">Nawyki słuchowe, o których mogłaś nie wiedzieć.</p>
    <div class="stats-grid">
      <div class="stat-card">
        <h4>Pora dnia — kiedy słuchasz</h4>
        <div class="hour-chart-wrap"><div class="hour-chart">{hour_bars}</div></div>
      </div>
      <div class="stat-card">
        <h4>Dni tygodnia</h4>
        {wd_bars}
      </div>
      <div class="stat-card" style="grid-column: 1 / -1;">
        <h4>Trend miesięczny (odsłuchy / miesiąc, {year_from}–{year_to})</h4>
        <div class="month-chart-wrap"><div class="month-chart">{month_bars}</div></div>
      </div>
      <div class="stat-card">
        <h4>Taylor's Version vs. Oryginały</h4>
        <div class="duo-bar"><div style="flex-grow:{tv_pct}"></div><div style="flex-grow:{orig_pct}"></div></div>
        <div class="duo-legend"><span>🎗️ Taylor's Version — {tv_pct}%</span><span>Oryginały — {orig_pct}%</span></div>
        <div class="callout"><p>Udział nagrań odzyskanych przez Taylor w Twoich odsłuchach.</p></div>
      </div>
      <div class="stat-card">
        <h4>Rekordy obsesji</h4>
        <div class="callout">
          <span class="cal-num">{obsession_cnt}×</span>
          <p><strong>„{esc(obsession_song)}”</strong> odtworzone {obsession_cnt} razy jednego dnia ({obsession_day_fmt}).</p>
        </div>
        <div class="callout">
          <span class="cal-num">{top_day_h}h {top_day_m}m</span>
          <p>Twój najdłuższy dzień: {top_day_fmt} — tyle czasu poświęciłaś muzyce jednego dnia.</p>
        </div>
      </div>
    </div>
  </div>
</section>

<footer>
  <div class="sig">...ready for it?</div>
  Raport wygenerowany na podstawie Twojej rozszerzonej historii odsłuchań Spotify ({year_from}–{year_to}) · tylko {esc(artist_name)} 💛
</footer>

</body>
</html>
'''


# 4. MAIN

def main():
    print(f"Wczytuję dane z: {DATA_FOLDER}")
    records = load_records(DATA_FOLDER, ARTIST_NAME, YEAR_FROM, YEAR_TO)
    print(f"Znaleziono {len(records)} odsłuchań artysty '{ARTIST_NAME}' w latach {YEAR_FROM}-{YEAR_TO}.")

    print("Liczę statystyki...")
    stats = analyze(records, YEAR_FROM, YEAR_TO, REAL_PLAY_THRESHOLD_MS,
                     CURRENT_ERA_WINDOW_DAYS, LOCAL_TZ_OFFSET_HOURS)

    print("Buduję raport HTML...")
    out_html = build_html(stats, ARTIST_NAME, YEAR_FROM, YEAR_TO)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(out_html)

    print(f"\nGotowe! Otwórz plik: {os.path.abspath(OUTPUT_FILE)}")
    print(f"   Łącznie: {stats['total_hours']:.0f}h ({stats['total_plays']:,} odsłuchań)")


if __name__ == "__main__":
    main()