
import glob
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import plotly.graph_objects as go

# KONFIGURACJA

# Rok do analizy — jeśli zostawione None, skrypt zapyta w konsoli
YEAR = 2026

# Folder z rozpakowanymi plikami JSON od Spotify
DATA_FOLDER = "spotify_data"

# Próg (w ms), poniżej którego odtworzenie liczymy jako "pominięte / niepełne"
# 30 sekund to typowy próg używany przez sam Spotify Wrapped
MIN_MS_TO_COUNT_AS_PLAY = 30_000

OUTPUT_FILE = f"taylors_version_wrapped_{YEAR}.html"


# WCZYTYWANIE DANYCH

def load_streaming_history(folder):
    """Wczytuje i łączy wszystkie pliki Streaming_History_Audio_*.json."""
    pattern = os.path.join(folder, "Streaming_History_Audio_*.json")
    files = sorted(glob.glob(pattern))

    if not files:
        raise SystemExit(
            f"\n❌ Nie znaleziono plików w '{folder}'.\n"
            f"Upewnij się, że rozpakowałaś ZIP-a od Spotify i ustawiłaś "
            f"poprawną ścieżkę w DATA_FOLDER.\n"
        )

    print(f"📂 Znaleziono {len(files)} plik(ów) z historią odtwarzania:")
    all_entries = []
    for path in files:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
            all_entries.extend(entries)
        print(f"   - {os.path.basename(path)} ({len(entries)} wpisów)")

    print(f"\n📊 Łącznie wczytano {len(all_entries)} wpisów (wszystkie lata)")
    return all_entries


def filter_by_year(entries, year):
    """Zostawia tylko odtworzenia z danego roku, z realnym czasem słuchania."""
    filtered = []
    for e in entries:
        ts = e.get("ts")
        if not ts:
            continue
        try:
            dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
        if dt.year != year:
            continue
        if e.get("ms_played", 0) < MIN_MS_TO_COUNT_AS_PLAY:
            continue
        if not e.get("master_metadata_track_name"):
            continue  # pomijamy podcasty/audiobooki bez nazwy utworu
        e["_dt"] = dt
        filtered.append(e)
    return filtered


# LICZENIE STATYSTYK

# Mapowanie albumów Taylor Swift na jej "ery" (nazwa + kolor motywu)
# Dopasowanie po fragmencie nazwy albumu (małe litery), żeby złapać
# też różne wydania (Taylor's Version, Deluxe, itd.)
TAYLOR_ERAS = [
    ("taylor swift",              ("Debiutancka Era", "#7CAE7A")),
    ("fearless",                  ("Fearless Era", "#D4A843")),
    ("speak now",                 ("Speak Now Era", "#9B59B6")),
    ("red",                       ("Red Era", "#B7312C")),
    ("1989",                      ("1989 Era", "#A8D0E6")),
    ("reputation",                ("reputation Era", "#2B2B2B")),
    ("lover",                     ("Lover Era", "#F8A5C2")),
    ("folklore",                  ("folklore Era", "#8C8C8C")),
    ("evermore",                  ("evermore Era", "#B5651D")),
    ("midnights",                 ("Midnights Era", "#1B2A4A")),
    ("tortured poets",            ("The Tortured Poets Department Era", "#D9D9D9")),
    ("life of a showgirl",        ("The Life of a Showgirl Era", "#FFB627")),
]

# Oficjalne długości albumów (w minutach) — do liczenia "pełnych przesłuchań".
# Kolejność ma znaczenie: sprawdzamy od najbardziej specyficznych nazw (np.
# "1989 (Taylor's Version)") do bardziej ogólnych ("1989"), żeby nie pomylić
# oryginałów z re-recordingami. Wartości dla oryginalnych (nie-TV) wydań
# "Fearless", "Speak Now", "Red" i "1989" są przybliżone (standardowe edycje).
ALBUM_DURATIONS_MINUTES = [
    ("life of a showgirl",                      41 + 40 / 60),   # 41:40
    ("tortured poets department: the anthology", 122.0),          # ~2h02m (31 utw.)
    ("tortured poets department",                65 + 8 / 60),   # 65:08 (16 utw.)
    ("midnights (3am",                           66 + 40 / 60),  # 3am Edition (przybliżenie)
    ("midnights",                                44 + 2 / 60),   # 44:02 standard
    ("evermore",                                 60 + 38 / 60),  # 60:38
    ("folklore",                                 63 + 29 / 60),  # 63:29
    ("lover",                                    61 + 48 / 60),  # 61:48
    ("1989 (taylor's version)",                  76 + 28 / 60),  # 76:28
    ("1989",                                     48 + 57 / 60),  # ~48:57 (przybliżenie, oryginał)
    ("reputation",                               55 + 45 / 60),  # 55:45
    ("red (taylor's version)",                   131 + 37 / 60), # ~131:37 (przybliżenie)
    ("red",                                      65 + 9 / 60),   # ~65:09 (przybliżenie, oryginał)
    ("speak now (taylor's version)",             104 + 33 / 60), # 104:33
    ("speak now",                                67.0),          # ~67:00 (przybliżenie, oryginał)
    ("fearless (taylor's version)",              106.0),         # ~106:00 (przybliżenie)
    ("fearless",                                 53 + 16 / 60),  # ~53:16 (przybliżenie, oryginał)
    ("taylor swift",                             40 + 28 / 60),  # 40:28 (debiut)
]


def match_taylor_era(album_name):
    """Zwraca (nazwa_ery, kolor) na podstawie nazwy albumu, albo None.
    Dopasowanie na granicach całych słów (\\b), żeby uniknąć fałszywych
    trafień typu "red" wewnątrz słowa "toRTUREd" (Tortured Poets Department)."""
    if not album_name:
        return None
    name_lower = album_name.lower()
    for key, era in TAYLOR_ERAS:
        if re.search(r"\b" + re.escape(key) + r"\b", name_lower):
            return era
    return None


def match_album_duration(album_name):
    """Zwraca przybliżoną długość albumu w minutach, albo None jeśli nieznana.
    Tak jak w match_taylor_era — dopasowanie na granicach całych słów."""
    if not album_name:
        return None
    name_lower = album_name.lower()
    for key, minutes in ALBUM_DURATIONS_MINUTES:
        if re.search(r"\b" + re.escape(key) + r"\b", name_lower):
            return minutes
    return None


def compute_artist_stats(entries, artist_name):
    """Liczy top albumy i utwory dla JEDNEGO konkretnego artysty
    (dopasowanie dokładne, bez rozróżniania wielkości liter), a dla
    Taylor Swift dodatkowo: ranking Er wg minut słuchania, pełne
    przesłuchania albumów i najdłuższy "binge" (patrz compute_binge).

    WSZYSTKO poniżej liczone jest konsekwentnie wg MINUT SŁUCHANIA
    (tak jak realny Spotify Wrapped) — z liczbą odtworzeń dołączoną
    jako dodatkowy kontekst, a nie jako osobne kryterium sortowania.
    Dzięki temu "Moja Era", ranking Er i top 5 albumów zawsze się
    ze sobą zgadzają."""
    artist_entries = [
        e for e in entries
        if (e.get("master_metadata_album_artist_name") or "").lower() == artist_name.lower()
    ]

    if not artist_entries:
        return None

    total_songs = len(artist_entries)
    total_minutes = sum(e["ms_played"] for e in artist_entries) / 1000 / 60

    # --- Top utwory wg minut słuchania ---
    track_minutes = defaultdict(float)
    track_plays = Counter()
    for e in artist_entries:
        key = (e["master_metadata_track_name"], e.get("master_metadata_album_album_name") or "—")
        track_minutes[key] += e["ms_played"] / 1000 / 60
        track_plays[key] += 1
    top_tracks = [
        {"name": name, "album": album, "minutes": minutes, "plays": track_plays[(name, album)]}
        for (name, album), minutes in sorted(track_minutes.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    # --- Minuty i odtworzenia słuchania per album ---
    album_minutes = defaultdict(float)
    album_plays = Counter()
    for e in artist_entries:
        album = e.get("master_metadata_album_album_name")
        if not album:
            continue
        album_minutes[album] += e["ms_played"] / 1000 / 60
        album_plays[album] += 1

    albums_by_minutes = sorted(album_minutes.items(), key=lambda x: x[1], reverse=True)

    # Top albumy — ranking wg minut słuchania, z liczbą odtworzeń jako kontekst
    top_albums = [
        {"album": album, "minutes": minutes, "plays": album_plays[album]}
        for album, minutes in albums_by_minutes[:10]
    ]

    # --- Ranking WSZYSTKICH Er wg % czasu słuchania ---
    era_minutes = defaultdict(float)
    era_color_map = {}
    for album_name, minutes in album_minutes.items():
        era = match_taylor_era(album_name)
        if era:
            era_name, era_color = era
            era_minutes[era_name] += minutes
            era_color_map[era_name] = era_color

    era_ranking = []
    for era_name, minutes in sorted(era_minutes.items(), key=lambda x: x[1], reverse=True):
        pct = (minutes / total_minutes * 100) if total_minutes else 0
        era_ranking.append({
            "era": era_name,
            "color": era_color_map[era_name],
            "minutes": minutes,
            "pct": pct,
        })

    # "Moja Era" = era z NAJWYŻSZĄ ŁĄCZNĄ liczbą minut spośród WSZYSTKICH
    # jej albumów/wydań (czyli po prostu #1 z era_ranking) — to samo źródło
    # prawdy co ranking Er, więc te dwie sekcje ZAWSZE się zgadzają.
    dominant_era = None
    top_era_top_album = None
    if era_ranking:
        top_era = era_ranking[0]
        dominant_era = (top_era["era"], top_era["color"])
        # Album z tej właśnie Ery, na który poszło najwięcej minut
        for album_name, minutes in albums_by_minutes:
            era = match_taylor_era(album_name)
            if era and era[0] == top_era["era"]:
                top_era_top_album = album_name
                break

    # --- Top 5 piosenek z topowego albumu topowej Ery ---
    top_era_top_tracks = []
    if top_era_top_album:
        era_album_track_minutes = defaultdict(float)
        era_album_track_plays = Counter()
        for e in artist_entries:
            if e.get("master_metadata_album_album_name") != top_era_top_album:
                continue
            name = e["master_metadata_track_name"]
            era_album_track_minutes[name] += e["ms_played"] / 1000 / 60
            era_album_track_plays[name] += 1
        top_era_top_tracks = [
            {"name": name, "minutes": minutes, "plays": era_album_track_plays[name]}
            for name, minutes in sorted(era_album_track_minutes.items(), key=lambda x: x[1], reverse=True)[:5]
        ]

    # --- Pełne przesłuchania albumu: minuty_słuchania / długość_albumu ---
    full_listens = []
    for album_name, minutes in album_minutes.items():
        duration = match_album_duration(album_name)
        if duration:
            full_listens.append({
                "album": album_name,
                "minutes_listened": minutes,
                "album_duration": duration,
                "full_listens": minutes / duration,
            })
    full_listens.sort(key=lambda x: x["full_listens"], reverse=True)

    return {
        "total_songs": total_songs,
        "total_minutes": total_minutes,
        "top_tracks": top_tracks,
        "top_albums": top_albums,
        "dominant_era": dominant_era,
        "top_era_top_album": top_era_top_album,
        "top_era_top_tracks": top_era_top_tracks,
        "era_ranking": era_ranking,
        "full_listens": full_listens,
    }


def compute_binge(entries_year, artist_name, gap_threshold_minutes=30):
    """Znajduje najdłuższą nieprzerwaną 'sesję' słuchania danego artysty:
    ciąg kolejnych (chronologicznie) odtworzeń WYŁĄCZNIE tego artysty, gdzie
    przerwa między końcem jednego utworu a początkiem następnego nie
    przekracza `gap_threshold_minutes` (żeby nie liczyć jako 'jednej sesji'
    słuchania rozdzielonego np. dniami ciszy). Zwraca informacje o najdłuższym
    takim ciągu (wg łącznego czasu słuchania), albo None."""
    target = artist_name.lower()
    sorted_entries = sorted(entries_year, key=lambda e: e["_dt"])

    def eval_run(run):
        if not run:
            return None
        total_ms = sum(e["ms_played"] for e in run)
        return {
            "minutes": total_ms / 1000 / 60,
            "track_count": len(run),
            "start": run[0]["_dt"],
            "end": run[-1]["_dt"],
        }

    best = None
    current_run = []
    prev_end = None

    for e in sorted_entries:
        artist = (e.get("master_metadata_album_artist_name") or "").lower()
        is_target = artist == target

        gap_ok = True
        if prev_end is not None:
            gap_minutes = (e["_dt"] - prev_end).total_seconds() / 60
            gap_ok = gap_minutes <= gap_threshold_minutes

        if is_target and gap_ok:
            current_run.append(e)
        else:
            candidate = eval_run(current_run)
            if candidate and (best is None or candidate["minutes"] > best["minutes"]):
                best = candidate
            current_run = [e] if is_target else []

        prev_end = e["_dt"] + timedelta(milliseconds=e["ms_played"])

    candidate = eval_run(current_run)
    if candidate and (best is None or candidate["minutes"] > best["minutes"]):
        best = candidate

    return best


def compute_stats(entries):
    total_songs_played = len(entries)
    total_ms = sum(e["ms_played"] for e in entries)
    total_minutes = total_ms / 1000 / 60
    total_hours = total_minutes / 60

    unique_tracks = {e["spotify_track_uri"] for e in entries if e.get("spotify_track_uri")}
    unique_artists = {e["master_metadata_album_artist_name"] for e in entries
                       if e.get("master_metadata_album_artist_name")}

    # --- Wszystko poniżej liczone WG MINUT SŁUCHANIA (tak jak realny Spotify
    # Wrapped), z liczbą odtworzeń dołączoną jako dodatkowy kontekst ---

    track_minutes = defaultdict(float)
    track_plays = Counter()
    for e in entries:
        key = (e["master_metadata_track_name"], e["master_metadata_album_artist_name"])
        track_minutes[key] += e["ms_played"] / 1000 / 60
        track_plays[key] += 1
    top_tracks = [
        {"name": name, "artist": artist, "minutes": minutes, "plays": track_plays[(name, artist)]}
        for (name, artist), minutes in sorted(track_minutes.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    artist_minutes = defaultdict(float)
    artist_plays = Counter()
    for e in entries:
        a = e["master_metadata_album_artist_name"]
        artist_minutes[a] += e["ms_played"] / 1000 / 60
        artist_plays[a] += 1
    top_artists = [
        {"artist": artist, "minutes": minutes, "plays": artist_plays[artist]}
        for artist, minutes in sorted(artist_minutes.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    album_minutes = defaultdict(float)
    album_plays = Counter()
    for e in entries:
        if not e.get("master_metadata_album_album_name"):
            continue
        key = (e["master_metadata_album_album_name"], e["master_metadata_album_artist_name"])
        album_minutes[key] += e["ms_played"] / 1000 / 60
        album_plays[key] += 1
    top_albums = [
        {"album": album, "artist": artist, "minutes": minutes, "plays": album_plays[(album, artist)]}
        for (album, artist), minutes in sorted(album_minutes.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    # Rozkład wg miesiąca
    monthly_counter = Counter(e["_dt"].month for e in entries)
    months_pl = ["Sty", "Lut", "Mar", "Kwi", "Maj", "Cze",
                 "Lip", "Sie", "Wrz", "Paź", "Lis", "Gru"]
    monthly_data = [monthly_counter.get(m, 0) for m in range(1, 13)]

    # Rozkład wg godziny dnia
    hourly_counter = Counter(e["_dt"].hour for e in entries)
    hourly_data = [hourly_counter.get(h, 0) for h in range(24)]

    # Rozkład wg dnia tygodnia
    weekday_counter = Counter(e["_dt"].weekday() for e in entries)
    weekdays_pl = ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Nd"]
    weekday_data = [weekday_counter.get(d, 0) for d in range(7)]

    # Skip rate
    skipped_count = sum(1 for e in entries if e.get("skipped"))
    skip_rate = (skipped_count / total_songs_played * 100) if total_songs_played else 0

    # Ulubiona platforma
    platform_counter = Counter(e.get("platform", "nieznana") for e in entries)
    top_platform = platform_counter.most_common(1)[0] if platform_counter else ("brak danych", 0)

    # Dzień z największą liczbą odtworzeń
    day_counter = Counter(e["_dt"].date() for e in entries)
    top_day = day_counter.most_common(1)[0] if day_counter else (None, 0)

    return {
        "total_songs_played": total_songs_played,
        "total_minutes": total_minutes,
        "total_hours": total_hours,
        "unique_tracks": len(unique_tracks),
        "unique_artists": len(unique_artists),
        "top_tracks": top_tracks,
        "top_artists": top_artists,
        "top_albums": top_albums,
        "monthly_data": monthly_data,
        "months_pl": months_pl,
        "hourly_data": hourly_data,
        "weekday_data": weekday_data,
        "weekdays_pl": weekdays_pl,
        "skip_rate": skip_rate,
        "top_platform": top_platform,
        "top_day": top_day,
    }


def compute_yearly_overview(all_entries):
    """Liczy podstawowe statystyki dla KAŻDEGO roku obecnego w danych
    (żeby móc pokazać ewolucję gustu muzycznego na przestrzeni lat)."""

    # Grupujemy wpisy wg roku (z tym samym filtrem co filter_by_year,
    # ale dla wszystkich lat naraz)
    by_year = defaultdict(list)
    for e in all_entries:
        ts = e.get("ts")
        if not ts:
            continue
        try:
            dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
        if e.get("ms_played", 0) < MIN_MS_TO_COUNT_AS_PLAY:
            continue
        if not e.get("master_metadata_track_name"):
            continue
        e["_dt"] = dt
        by_year[dt.year].append(e)

    yearly_summary = {}
    for year, entries in sorted(by_year.items()):
        total_songs = len(entries)
        total_hours = sum(e["ms_played"] for e in entries) / 1000 / 60 / 60

        artist_minutes = defaultdict(float)
        artist_plays = Counter()
        for e in entries:
            a = e["master_metadata_album_artist_name"]
            if not a:
                continue
            artist_minutes[a] += e["ms_played"] / 1000 / 60
            artist_plays[a] += 1
        if artist_minutes:
            top_artist_name = max(artist_minutes, key=artist_minutes.get)
            top_artist = {"name": top_artist_name, "minutes": artist_minutes[top_artist_name], "plays": artist_plays[top_artist_name]}
        else:
            top_artist = {"name": "brak danych", "minutes": 0, "plays": 0}

        track_minutes = defaultdict(float)
        track_plays = Counter()
        for e in entries:
            key = (e["master_metadata_track_name"], e["master_metadata_album_artist_name"])
            track_minutes[key] += e["ms_played"] / 1000 / 60
            track_plays[key] += 1
        if track_minutes:
            top_track_key = max(track_minutes, key=track_minutes.get)
            top_track = {"name": top_track_key[0], "artist": top_track_key[1],
                         "minutes": track_minutes[top_track_key], "plays": track_plays[top_track_key]}
        else:
            top_track = {"name": "brak danych", "artist": "", "minutes": 0, "plays": 0}

        album_minutes = defaultdict(float)
        album_plays = Counter()
        for e in entries:
            album = e.get("master_metadata_album_album_name")
            if not album:
                continue
            album_minutes[album] += e["ms_played"] / 1000 / 60
            album_plays[album] += 1
        if album_minutes:
            top_album_name = max(album_minutes, key=album_minutes.get)
            top_album = {"name": top_album_name, "minutes": album_minutes[top_album_name], "plays": album_plays[top_album_name]}
        else:
            top_album = {"name": "brak danych", "minutes": 0, "plays": 0}

        unique_artists = {e["master_metadata_album_artist_name"] for e in entries
                           if e.get("master_metadata_album_artist_name")}

        yearly_summary[year] = {
            "total_songs": total_songs,
            "total_hours": total_hours,
            "unique_artists": len(unique_artists),
            "top_artist": top_artist,
            "top_track": top_track,
            "top_album": top_album,
        }

    return yearly_summary


# GENEROWANIE RAPORTU HTML

def build_report(stats, year, yearly_summary, taylor_stats, binge_stats, output_path):
    green = "#1DB954"

    fig_months = go.Figure(go.Bar(
        x=stats["months_pl"], y=stats["monthly_data"], marker=dict(color=green)
    ))
    fig_months.update_layout(
        title=f"📅 Odtworzenia w poszczególnych miesiącach {year}",
        plot_bgcolor="#121212", paper_bgcolor="#121212",
        font=dict(color="white", size=13), height=400,
    )

    fig_hours = go.Figure(go.Bar(
        x=[f"{h}:00" for h in range(24)], y=stats["hourly_data"], marker=dict(color=green)
    ))
    fig_hours.update_layout(
        title="🕐 O której porze dnia słuchasz najwięcej",
        plot_bgcolor="#121212", paper_bgcolor="#121212",
        font=dict(color="white", size=13), height=400,
    )

    fig_weekday = go.Figure(go.Bar(
        x=stats["weekdays_pl"], y=stats["weekday_data"], marker=dict(color=green)
    ))
    fig_weekday.update_layout(
        title="📆 Który dzień tygodnia jest Twoim ulubionym",
        plot_bgcolor="#121212", paper_bgcolor="#121212",
        font=dict(color="white", size=13), height=400,
    )

    fig_artists = go.Figure(go.Bar(
        x=[a["minutes"] for a in stats["top_artists"]][::-1],
        y=[a["artist"] for a in stats["top_artists"]][::-1],
        orientation="h", marker=dict(color=green),
    ))
    fig_artists.update_layout(
        title="🎤 Top 10 artystów (wg minut słuchania)",
        plot_bgcolor="#121212", paper_bgcolor="#121212",
        font=dict(color="white", size=13), height=450,
        xaxis_title="Minuty słuchania",
    )

    tracks_html = "".join(
        f"<li><span class='rank'>#{i+1}</span> <b>{t['name']}</b> — {t['artist']} "
        f"<span class='count'>{t['minutes']:.0f} min · {t['plays']}x</span></li>"
        for i, t in enumerate(stats["top_tracks"])
    )

    albums_html = "".join(
        f"<li><span class='rank'>#{i+1}</span> <b>{a['album']}</b> — {a['artist']} "
        f"<span class='count'>{a['minutes']:.0f} min · {a['plays']}x</span></li>"
        for i, a in enumerate(stats["top_albums"])
    )

    # --- Wykres: liczba odtworzeń w kolejnych latach ---
    years_sorted = sorted(yearly_summary.keys())
    fig_years_songs = go.Figure(go.Bar(
        x=[str(y) for y in years_sorted],
        y=[yearly_summary[y]["total_songs"] for y in years_sorted],
        marker=dict(color=[green if y == year else "#535353" for y in years_sorted]),
    ))
    fig_years_songs.update_layout(
        title="📈 Liczba odtworzonych piosenek w kolejnych latach",
        plot_bgcolor="#121212", paper_bgcolor="#121212",
        font=dict(color="white", size=13), height=400,
    )

    # --- Wykres: godziny słuchania w kolejnych latach ---
    fig_years_hours = go.Figure(go.Scatter(
        x=[str(y) for y in years_sorted],
        y=[yearly_summary[y]["total_hours"] for y in years_sorted],
        mode="lines+markers",
        line=dict(color=green, width=3),
        marker=dict(size=10, color=green),
        fill="tozeroy",
        fillcolor="rgba(29,185,84,0.15)",
    ))
    fig_years_hours.update_layout(
        title="⏱️ Godziny słuchania na przestrzeni lat",
        plot_bgcolor="#121212", paper_bgcolor="#121212",
        font=dict(color="white", size=13), height=400,
    )

    # --- Tabela: top artysta/utwór/album per rok ---
    yearly_rows_html = ""
    for y in years_sorted:
        s = yearly_summary[y]
        highlight = "background:#1DB95422;" if y == year else ""
        yearly_rows_html += f"""
        <tr style="{highlight}">
            <td><b>{y}</b></td>
            <td>{s['top_artist']['name']} <span class='count'>{s['top_artist']['minutes']:.0f} min</span></td>
            <td>{s['top_track']['name']} — {s['top_track']['artist']} <span class='count'>{s['top_track']['minutes']:.0f} min</span></td>
            <td>{s['top_album']['name']} <span class='count'>{s['top_album']['minutes']:.0f} min</span></td>
            <td>{s['total_songs']:,}</td>
            <td>{s['total_hours']:.0f}h</td>
        </tr>"""

    # --- Ciekawostka: zmiana rok do roku ---
    yoy_comment = ""
    if year in yearly_summary and (year - 1) in yearly_summary:
        prev = yearly_summary[year - 1]
        curr = yearly_summary[year]
        diff_songs = curr["total_songs"] - prev["total_songs"]
        diff_pct = (diff_songs / prev["total_songs"] * 100) if prev["total_songs"] else 0
        kierunek = "więcej" if diff_songs >= 0 else "mniej"
        yoy_comment = (
            f"<li>📊 W porównaniu do {year - 1} roku, w {year} słuchałaś "
            f"<b>{abs(diff_pct):.0f}% {kierunek}</b> piosenek "
            f"({abs(diff_songs):,} {kierunek})</li>"
        )
        if prev["top_artist"]["name"] != curr["top_artist"]["name"]:
            yoy_comment += (
                f"<li>🔄 Twój top artysta zmienił się z "
                f"<b>{prev['top_artist']['name']}</b> ({year - 1}) na "
                f"<b>{curr['top_artist']['name']}</b> ({year})</li>"
            )
        else:
            yoy_comment += (
                f"<li>🎯 <b>{curr['top_artist']['name']}</b> to Twój top artysta "
                f"drugi rok z rzędu!</li>"
            )

    top_day_str = (
        f"{stats['top_day'][0].strftime('%d.%m.%Y')} ({stats['top_day'][1]} utworów)"
        if stats["top_day"][0] else "brak danych"
    )

    # --- Sekcja Taylor Swift "W jakiej jesteś Erze" ---
    taylor_section_html = ""
    if taylor_stats:
        era = taylor_stats["dominant_era"]
        era_name = era[0] if era else "Nieznana Era"
        era_color = era[1] if era else "#F8A5C2"

        taylor_tracks_html = "".join(
            f"<li><span class='rank'>#{i+1}</span> <b>{t['name']}</b> "
            f"<span class='era-tag' style='color:{era_color};'>· {t['album']}</span> "
            f"<span class='count'>{t['minutes']:.0f} min · {t['plays']}x</span></li>"
            for i, t in enumerate(taylor_stats["top_tracks"][:5])
        )

        taylor_albums_html = "".join(
            f"<li><span class='rank'>#{i+1}</span> <b>{a['album']}</b> "
            f"<span class='count'>{a['minutes']:.0f} min · {a['plays']}x</span></li>"
            for i, a in enumerate(taylor_stats["top_albums"][:5])
        )

        fig_taylor_albums = go.Figure(go.Bar(
            x=[a["minutes"] for a in taylor_stats["top_albums"][:6]][::-1],
            y=[a["album"] for a in taylor_stats["top_albums"][:6]][::-1],
            orientation="h",
            marker=dict(color=era_color),
        ))
        fig_taylor_albums.update_layout(
            title="💿 Twoje najczęściej słuchane albumy TS (wg minut)",
            plot_bgcolor="#1a1625", paper_bgcolor="#1a1625",
            font=dict(color="white", size=13), height=350,
            xaxis_title="Minuty słuchania",
        )

        # --- Top 5 piosenek z topowego albumu topowej Ery ---
        top_era_tracks_html = "".join(
            f"<li><span class='rank'>#{i+1}</span> <b>{t['name']}</b> "
            f"<span class='count'>{t['minutes']:.0f} min · {t['plays']}x</span></li>"
            for i, t in enumerate(taylor_stats["top_era_top_tracks"])
        )
        top_era_section_html = ""
        if taylor_stats["top_era_top_tracks"]:
            top_era_section_html = f"""
        <div class="top-era-tracks">
            <h3>🎤 Top 5 piosenek z Twojej Top Ery — {taylor_stats['top_era_top_album']}</h3>
            <ul class="taylor-list">{top_era_tracks_html}</ul>
        </div>"""

        # --- Ranking Er wg % czasu słuchania ---
        era_rows_html = ""
        for i, e in enumerate(taylor_stats["era_ranking"]):
            is_top = i == 0
            crown = "👑 " if is_top else ""
            era_rows_html += f"""
            <div class="era-row {'era-row-top' if is_top else ''}">
                <div class="era-row-label">
                    <span class="era-dot" style="background:{e['color']};"></span>
                    <span>{crown}{e['era']}</span>
                </div>
                <div class="era-row-bar-track">
                    <div class="era-row-bar" style="width:{e['pct']:.1f}%; background:{e['color']};"></div>
                </div>
                <div class="era-row-pct">{e['pct']:.1f}%</div>
            </div>"""

        # --- Najdłuższy Taylor Binge ---
        binge_html = ""
        if binge_stats:
            hours = int(binge_stats["minutes"] // 60)
            minutes = int(binge_stats["minutes"] % 60)
            duration_str = f"{hours}h {minutes}min" if hours else f"{minutes}min"
            binge_html = f"""
        <div class="binge-card">
            <div class="binge-icon">🔥</div>
            <div>
                <div class="binge-title">Najdłuższy Taylor Binge</div>
                <div class="binge-value">{duration_str} <span class="binge-sub">({binge_stats['track_count']} piosenek non-stop)</span></div>
                <div class="binge-when">zaczęło się {binge_stats['start'].strftime('%d.%m.%Y o %H:%M')}</div>
            </div>
        </div>"""

        # --- Pełne przesłuchania albumów ---
        full_listens_html = ""
        for fl in taylor_stats["full_listens"][:8]:
            full_listens_html += f"""
            <li>
                <b>{fl['album']}</b>
                <span class="count">{fl['full_listens']:.1f}x cały album</span>
                <div class="fl-sub">{fl['minutes_listened']:.0f} min słuchania ÷ {fl['album_duration']:.0f} min albumu</div>
            </li>"""

        taylor_section_html = f"""
    <div class="section taylor-section" style="--era-color:{era_color};">
        <div class="taylor-header">
            <span class="taylor-badge">✨ SWIFTIE STATS ✨</span>
            <h2 class="taylor-title">W jakiej jesteś Erze?</h2>
            <div class="era-name">{era_name}</div>
            <p class="taylor-sub">
                {taylor_stats['total_songs']:,} odtworzeń · {taylor_stats['total_minutes']:,.0f} minut w {year} roku
                · Era wybrana na podstawie albumu, na który poszło najwięcej minut słuchania
            </p>
        </div>

        {binge_html}

        <div class="era-ranking">
            <h3>🏆 Ranking Twoich Er (wg % czasu słuchania)</h3>
            {era_rows_html}
        </div>

        {top_era_section_html}

        <div class="taylor-grid">
            <div class="taylor-col">
                <h3>🎧 Top 5 piosenek</h3>
                <ul class="taylor-list">{taylor_tracks_html}</ul>
            </div>
            <div class="taylor-col">
                <h3>💿 Top 5 albumów (wg minut)</h3>
                <ul class="taylor-list">{taylor_albums_html}</ul>
            </div>
        </div>

        <div class="taylor-chart">
            {fig_taylor_albums.to_html(full_html=False, include_plotlyjs=False)}
        </div>

        <div class="full-listens">
            <h3>📀 Ile razy "przesłuchałaś" cały album</h3>
            <p class="fl-note">Liczone na podstawie łącznych minut słuchania danego albumu
            podzielonych przez jego oficjalną długość — nie każdego utworu z osobna.</p>
            <ul class="taylor-list">{full_listens_html}</ul>
        </div>
    </div>
"""

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<title>Mój Spotify Wrapped {year}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
    * {{ box-sizing:border-box; }}
    body {{
        background:#0a0a0a;
        color:#f5f5f5;
        font-family:'Inter',Arial,sans-serif;
        margin:0;
        line-height:1.5;
    }}
    h1, h2, h3, .stat-box .num {{ font-family:'Poppins',sans-serif; }}

    .header {{
        background:
            radial-gradient(circle at 20% 20%, rgba(29,185,84,.35), transparent 45%),
            radial-gradient(circle at 80% 0%, rgba(29,185,84,.25), transparent 40%),
            linear-gradient(160deg, #0a0a0a 0%, #0f1f14 60%, #0a0a0a 100%);
        padding:80px 20px 70px;
        text-align:center;
        border-bottom:1px solid #1f1f1f;
    }}
    .header h1 {{
        font-size:3.2em;
        font-weight:800;
        margin:0;
        background:linear-gradient(90deg,#1DB954,#7CE495);
        -webkit-background-clip:text;
        -webkit-text-fill-color:transparent;
        background-clip:text;
        letter-spacing:-1px;
    }}
    .header p {{ opacity:.55; margin-top:12px; font-size:.95em; letter-spacing:.3px; }}

    .container {{ max-width:940px; margin:0 auto; padding:50px 20px 20px; }}
    .section {{ margin-bottom:70px; }}

    .stat-boxes {{ display:flex; gap:16px; flex-wrap:wrap; justify-content:center; margin:40px 0; }}
    .stat-box {{
        background:linear-gradient(160deg,#181818,#111);
        border:1px solid #232323;
        border-radius:16px;
        padding:26px 32px;
        text-align:center;
        min-width:170px;
        transition:transform .2s ease, border-color .2s ease;
    }}
    .stat-box:hover {{ transform:translateY(-3px); border-color:#1DB95455; }}
    .stat-box .num {{ font-size:2.3em; font-weight:700; color:#1DB954; }}
    .stat-box .label {{ opacity:.6; margin-top:6px; font-size:.85em; }}

    ul {{ list-style:none; padding:0; }}
    li {{
        background:linear-gradient(90deg,#161616,#131313);
        border:1px solid #212121;
        margin:8px 0;
        padding:14px 20px;
        border-radius:10px;
        transition:border-color .2s ease;
    }}
    li:hover {{ border-color:#1DB95444; }}
    .rank {{ color:#1DB954; font-weight:700; margin-right:10px; }}
    .count {{ opacity:.55; float:right; font-size:.9em; }}

    h2 {{
        font-weight:700;
        font-size:1.5em;
        border-left:4px solid #1DB954;
        padding-left:14px;
        margin-bottom:24px;
    }}
    footer {{ text-align:center; opacity:.4; padding:40px 20px; font-size:.8em; }}

    table {{ border-collapse:collapse; width:100%; }}
    table td, table th {{ padding:13px 12px; border-bottom:1px solid #202020; }}
    table td {{ font-size:.88em; }}
    table th {{ font-family:'Poppins',sans-serif; }}

    /* --- Sekcja Taylor Swift --- */
    .taylor-section {{
        background:
            radial-gradient(circle at 15% 10%, color-mix(in srgb, var(--era-color) 35%, transparent), transparent 55%),
            radial-gradient(circle at 85% 90%, color-mix(in srgb, var(--era-color) 25%, transparent), transparent 50%),
            linear-gradient(160deg,#151020,#0a0a0a);
        border:1px solid color-mix(in srgb, var(--era-color) 40%, #222);
        border-radius:24px;
        padding:50px 40px;
        text-align:center;
    }}
    .taylor-badge {{
        display:inline-block;
        font-size:.75em;
        letter-spacing:2px;
        color:var(--era-color);
        border:1px solid var(--era-color);
        border-radius:20px;
        padding:6px 16px;
        margin-bottom:18px;
        font-weight:600;
    }}
    .taylor-title {{
        font-size:2em;
        margin:0 0 6px;
        border:none;
        padding:0;
        font-weight:800;
    }}
    .era-name {{
        font-size:1.6em;
        font-weight:700;
        color:var(--era-color);
        margin:10px 0 6px;
        font-family:'Poppins',sans-serif;
    }}
    .taylor-sub {{ opacity:.6; font-size:.9em; margin-bottom:35px; }}
    .taylor-grid {{
        display:grid;
        grid-template-columns:1fr 1fr;
        gap:24px;
        text-align:left;
        margin-bottom:20px;
    }}
    .taylor-col h3 {{ font-size:1em; opacity:.85; margin-bottom:14px; }}
    .taylor-list li {{ background:rgba(255,255,255,.04); border-color:rgba(255,255,255,.08); }}
    .era-tag {{ font-size:.82em; opacity:.85; }}
    .taylor-chart {{ text-align:left; margin-top:10px; }}

    /* --- Ranking Er --- */
    .era-ranking {{ text-align:left; margin:30px 0; }}
    .era-ranking h3 {{ font-size:1em; opacity:.85; margin-bottom:16px; text-align:center; }}
    .era-row {{
        display:flex; align-items:center; gap:12px; margin:8px 0;
        background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.06);
        border-radius:10px; padding:10px 14px;
    }}
    .era-row-top {{ border-color:var(--era-color); background:rgba(255,255,255,.06); }}
    .era-row-label {{ display:flex; align-items:center; gap:8px; min-width:210px; font-size:.88em; }}
    .era-dot {{ width:10px; height:10px; border-radius:50%; flex-shrink:0; }}
    .era-row-bar-track {{ flex:1; height:8px; background:rgba(255,255,255,.08); border-radius:6px; overflow:hidden; }}
    .era-row-bar {{ height:100%; border-radius:6px; }}
    .era-row-pct {{ min-width:48px; text-align:right; font-size:.85em; opacity:.75; font-weight:600; }}

    /* --- Binge --- */
    .binge-card {{
        display:flex; align-items:center; gap:18px; text-align:left;
        background:linear-gradient(90deg, rgba(255,138,0,.15), rgba(255,138,0,.03));
        border:1px solid rgba(255,138,0,.35); border-radius:14px;
        padding:18px 22px; margin:24px 0;
    }}
    .binge-icon {{ font-size:2.2em; }}
    .binge-title {{ font-size:.8em; opacity:.7; letter-spacing:.5px; text-transform:uppercase; }}
    .binge-value {{ font-size:1.4em; font-weight:700; font-family:'Poppins',sans-serif; margin-top:2px; }}
    .binge-sub {{ font-size:.65em; font-weight:400; opacity:.7; }}
    .binge-when {{ font-size:.82em; opacity:.6; margin-top:3px; }}

    /* --- Pełne przesłuchania --- */
    .full-listens {{ text-align:left; margin-top:30px; }}
    .full-listens h3 {{ font-size:1em; opacity:.85; margin-bottom:6px; text-align:center; }}
    .fl-note {{ font-size:.78em; opacity:.5; text-align:center; margin-bottom:16px; }}
    .fl-sub {{ font-size:.75em; opacity:.5; margin-top:3px; }}

    .top-era-tracks {{ text-align:left; margin:30px 0; }}
    .top-era-tracks h3 {{ font-size:1em; opacity:.85; margin-bottom:14px; text-align:center; }}
    @media (max-width:640px) {{
        .taylor-grid {{ grid-template-columns:1fr; }}
        .header h1 {{ font-size:2.2em; }}
    }}
</style>
</head>
<body>

<div class="header">
    <h1>🎵 Mój Spotify Wrapped {year}</h1>
    <p>Wygenerowano {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>
</div>

<div class="container">

    <div class="stat-boxes">
        <div class="stat-box">
            <div class="num">{stats['total_songs_played']:,}</div>
            <div class="label">Odtworzonych piosenek</div>
        </div>
        <div class="stat-box">
            <div class="num">{stats['unique_tracks']:,}</div>
            <div class="label">Unikalnych utworów</div>
        </div>
        <div class="stat-box">
            <div class="num">{stats['unique_artists']:,}</div>
            <div class="label">Różnych artystów</div>
        </div>
        <div class="stat-box">
            <div class="num">{stats['total_hours']:,.0f}</div>
            <div class="label">Godzin słuchania</div>
        </div>
        <div class="stat-box">
            <div class="num">{stats['skip_rate']:.1f}%</div>
            <div class="label">Wskaźnik pomijania</div>
        </div>
    </div>

    <div class="section">
        <h2>Top 10 utworów</h2>
        <ul>{tracks_html}</ul>
    </div>

    {taylor_section_html}

    <div class="section">
        <h2>💿 Top 10 albumów</h2>
        <ul>{albums_html}</ul>
    </div>

    <div class="section">
        {fig_artists.to_html(full_html=False, include_plotlyjs="cdn")}
    </div>

    <div class="section">
        {fig_months.to_html(full_html=False, include_plotlyjs=False)}
    </div>

    <div class="section">
        {fig_hours.to_html(full_html=False, include_plotlyjs=False)}
    </div>

    <div class="section">
        {fig_weekday.to_html(full_html=False, include_plotlyjs=False)}
    </div>

    <div class="section">
        <h2>Ciekawostki</h2>
        <ul>
            <li>🏆 Najwięcej słuchałaś w dniu: <b>{top_day_str}</b></li>
            <li>📱 Najczęściej używana platforma: <b>{stats['top_platform'][0]}</b> ({stats['top_platform'][1]} odtworzeń)</li>
            {yoy_comment}
        </ul>
    </div>

    <div class="section">
        <h2>📊 Twoja muzyczna historia — {years_sorted[0]}–{years_sorted[-1]}</h2>
        {fig_years_songs.to_html(full_html=False, include_plotlyjs=False)}
        {fig_years_hours.to_html(full_html=False, include_plotlyjs=False)}
    </div>

    <div class="section">
        <h2>🗓️ Rok po roku: co grało najczęściej</h2>
        <div style="overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse; background:#181818; border-radius:8px; overflow:hidden;">
            <thead>
                <tr style="background:#1DB954; color:#121212;">
                    <th style="padding:12px; text-align:left;">Rok</th>
                    <th style="padding:12px; text-align:left;">Top artysta</th>
                    <th style="padding:12px; text-align:left;">Top utwór</th>
                    <th style="padding:12px; text-align:left;">Top album</th>
                    <th style="padding:12px; text-align:left;">Piosenek</th>
                    <th style="padding:12px; text-align:left;">Godzin</th>
                </tr>
            </thead>
            <tbody>
                {yearly_rows_html}
            </tbody>
        </table>
        </div>
    </div>

</div>

<footer>Dane wygenerowane na podstawie Twojego pliku Extended Streaming History ze Spotify.</footer>

</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


# MAIN

def ask_for_year(available_years):
    """Pyta użytkownika w konsoli, który rok przeanalizować."""
    years_str = ", ".join(str(y) for y in available_years)
    print(f"\n📅 Dostępne lata w Twoich danych: {years_str}")
    while True:
        choice = input(f"Który rok chcesz przeanalizować? (Enter = {available_years[-1]}): ").strip()
        if choice == "":
            return available_years[-1]
        if choice.isdigit() and int(choice) in available_years:
            return int(choice)
        print(f"❌ Nieprawidłowy rok. Wybierz jeden z: {years_str}")


def main():
    entries = load_streaming_history(DATA_FOLDER)

    # Wykrywamy, jakie lata w ogóle są dostępne w danych
    available_years = sorted({
        datetime.strptime(e["ts"], "%Y-%m-%dT%H:%M:%SZ").year
        for e in entries if e.get("ts")
    })

    year = YEAR if YEAR is not None else ask_for_year(available_years)
    print(f"\n🎧 Analiza roku {year}\n")

    entries_year = filter_by_year(entries, year)

    print(f"🔎 Odtworzeń w {year} roku (po odfiltrowaniu krótkich/niepełnych): {len(entries_year)}")

    if not entries_year:
        raise SystemExit(f"\n❌ Brak danych dla roku {year} w Twoich plikach.\n")

    stats = compute_stats(entries_year)

    print("📈 Liczę statystyki dla wszystkich lat obecnych w danych...")
    yearly_summary = compute_yearly_overview(entries)
    print(f"   Znaleziono dane z lat: {', '.join(str(y) for y in sorted(yearly_summary))}")

    print("💜 Liczę statystyki Taylor Swift...")
    taylor_stats = compute_artist_stats(entries_year, "Taylor Swift")
    if taylor_stats:
        print(f"   Znaleziono {taylor_stats['total_songs']} odtworzeń Taylor Swift w {year}")
    else:
        print("   Brak odtworzeń Taylor Swift w tym roku — sekcja zostanie pominięta")

    binge_stats = compute_binge(entries_year, "Taylor Swift") if taylor_stats else None
    if binge_stats:
        print(f"   Najdłuższy Taylor Binge: {binge_stats['minutes']:.0f} min, {binge_stats['track_count']} piosenek")

    print("\n🛠️  Generuję raport...")
    output_file = f"taylors_version_wrapped_{year}.html"
    output_path = build_report(stats, year, yearly_summary, taylor_stats, binge_stats, output_file)

    print(f"\n✅ Gotowe! Raport zapisany jako: {os.path.abspath(output_path)}")
    print(f"   Otwórz go w przeglądarce, żeby zobaczyć swój Wrapped {year}.")


if __name__ == "__main__":
    main()