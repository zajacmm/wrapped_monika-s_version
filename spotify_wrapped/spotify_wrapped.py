
import glob
import json
import os
from collections import Counter, defaultdict
from datetime import datetime

import plotly.graph_objects as go

# KONFIGURACJA

# Rok do analizy
YEAR = 2026

# Folder z rozpakowanymi plikami JSON od Spotify
DATA_FOLDER = "spotify_data"

# Próg (w ms), poniżej którego odtworzenie liczymy jako "pominięte / niepełne"
# 30 sekund to typowy próg używany przez sam Spotify Wrapped
MIN_MS_TO_COUNT_AS_PLAY = 30_000

OUTPUT_FILE = f"moj_wrapped_{YEAR}.html"


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

def compute_stats(entries):
    total_songs_played = len(entries)
    total_ms = sum(e["ms_played"] for e in entries)
    total_minutes = total_ms / 1000 / 60
    total_hours = total_minutes / 60

    unique_tracks = {e["spotify_track_uri"] for e in entries if e.get("spotify_track_uri")}
    unique_artists = {e["master_metadata_album_artist_name"] for e in entries
                       if e.get("master_metadata_album_artist_name")}

    # Top utwory (wg liczby odtworzeń)
    track_counter = Counter(
        (e["master_metadata_track_name"], e["master_metadata_album_artist_name"])
        for e in entries
    )
    top_tracks = track_counter.most_common(10)

    # Top artyści (wg liczby odtworzeń)
    artist_counter = Counter(e["master_metadata_album_artist_name"] for e in entries)
    top_artists = artist_counter.most_common(10)

    # Top albumy (wg liczby odtworzeń utworów z danego albumu)
    album_counter = Counter(
        (e["master_metadata_album_album_name"], e["master_metadata_album_artist_name"])
        for e in entries
        if e.get("master_metadata_album_album_name")
    )
    top_albums = album_counter.most_common(10)

    # Top artyści wg czasu słuchania (minuty)
    artist_minutes = defaultdict(float)
    for e in entries:
        artist_minutes[e["master_metadata_album_artist_name"]] += e["ms_played"] / 1000 / 60
    top_artists_by_time = sorted(artist_minutes.items(), key=lambda x: x[1], reverse=True)[:10]

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
        "top_artists_by_time": top_artists_by_time,
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

        artist_counter = Counter(e["master_metadata_album_artist_name"] for e in entries)
        top_artist = artist_counter.most_common(1)[0] if artist_counter else ("brak danych", 0)

        track_counter = Counter(
            (e["master_metadata_track_name"], e["master_metadata_album_artist_name"])
            for e in entries
        )
        top_track = track_counter.most_common(1)[0] if track_counter else (("brak danych", ""), 0)

        album_counter = Counter(
            (e["master_metadata_album_album_name"], e["master_metadata_album_artist_name"])
            for e in entries
            if e.get("master_metadata_album_album_name")
        )
        top_album = album_counter.most_common(1)[0] if album_counter else (("brak danych", ""), 0)

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

def build_report(stats, year, yearly_summary, output_path):
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
        x=[a[1] for a in stats["top_artists"]][::-1],
        y=[a[0] for a in stats["top_artists"]][::-1],
        orientation="h", marker=dict(color=green),
    ))
    fig_artists.update_layout(
        title="🎤 Top 10 artystów (wg liczby odtworzeń)",
        plot_bgcolor="#121212", paper_bgcolor="#121212",
        font=dict(color="white", size=13), height=450,
        xaxis_title="Liczba odtworzeń",
    )

    tracks_html = "".join(
        f"<li><span class='rank'>#{i+1}</span> <b>{name}</b> — {artist} "
        f"<span class='count'>({count}x)</span></li>"
        for i, ((name, artist), count) in enumerate(stats["top_tracks"])
    )

    albums_html = "".join(
        f"<li><span class='rank'>#{i+1}</span> <b>{album}</b> — {artist} "
        f"<span class='count'>({count} odtworzeń utworów)</span></li>"
        for i, ((album, artist), count) in enumerate(stats["top_albums"])
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
            <td>{s['top_artist'][0]} <span class='count'>({s['top_artist'][1]}x)</span></td>
            <td>{s['top_track'][0][0]} — {s['top_track'][0][1]} <span class='count'>({s['top_track'][1]}x)</span></td>
            <td>{s['top_album'][0][0]} <span class='count'>({s['top_album'][1]}x)</span></td>
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
        if prev["top_artist"][0] != curr["top_artist"][0]:
            yoy_comment += (
                f"<li>🔄 Twój top artysta zmienił się z "
                f"<b>{prev['top_artist'][0]}</b> ({year - 1}) na "
                f"<b>{curr['top_artist'][0]}</b> ({year})</li>"
            )
        else:
            yoy_comment += (
                f"<li>🎯 <b>{curr['top_artist'][0]}</b> to Twój top artysta "
                f"drugi rok z rzędu!</li>"
            )

    top_day_str = (
        f"{stats['top_day'][0].strftime('%d.%m.%Y')} ({stats['top_day'][1]} utworów)"
        if stats["top_day"][0] else "brak danych"
    )

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<title>Mój Spotify Wrapped {year}</title>
<style>
    body {{ background:#121212; color:white; font-family:'Segoe UI',Arial,sans-serif; margin:0; }}
    .header {{ background:linear-gradient(135deg,#1DB954,#121212); padding:60px 20px; text-align:center; }}
    .header h1 {{ font-size:3em; margin:0; }}
    .header p {{ opacity:.8; margin-top:10px; }}
    .container {{ max-width:900px; margin:0 auto; padding:40px 20px; }}
    .section {{ margin-bottom:60px; }}
    .stat-boxes {{ display:flex; gap:20px; flex-wrap:wrap; justify-content:center; margin:40px 0; }}
    .stat-box {{ background:#181818; border-radius:12px; padding:25px 35px; text-align:center; min-width:180px; }}
    .stat-box .num {{ font-size:2.2em; font-weight:bold; color:#1DB954; }}
    .stat-box .label {{ opacity:.7; margin-top:5px; font-size:.9em; }}
    ul {{ list-style:none; padding:0; }}
    li {{ background:#181818; margin:8px 0; padding:14px 20px; border-radius:8px; }}
    .rank {{ color:#1DB954; font-weight:bold; margin-right:10px; }}
    .count {{ opacity:.6; float:right; }}
    h2 {{ border-left:4px solid #1DB954; padding-left:12px; }}
    footer {{ text-align:center; opacity:.5; padding:30px; font-size:.85em; }}
    table td, table th {{ padding:12px; border-bottom:1px solid #282828; }}
    table td {{ font-size:.9em; }}
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

def main():
    print(f"🎧 Analiza roku {YEAR}\n")

    entries = load_streaming_history(DATA_FOLDER)
    entries_year = filter_by_year(entries, YEAR)

    print(f"\n🔎 Odtworzeń w {YEAR} roku (po odfiltrowaniu krótkich/niepełnych): {len(entries_year)}")

    if not entries_year:
        raise SystemExit(f"\n❌ Brak danych dla roku {YEAR} w Twoich plikach.\n")

    stats = compute_stats(entries_year)

    print("📈 Liczę statystyki dla wszystkich lat obecnych w danych...")
    yearly_summary = compute_yearly_overview(entries)
    print(f"   Znaleziono dane z lat: {', '.join(str(y) for y in sorted(yearly_summary))}")

    print("\n🛠️  Generuję raport...")
    output_path = build_report(stats, YEAR, yearly_summary, OUTPUT_FILE)

    print(f"\n✅ Gotowe! Raport zapisany jako: {os.path.abspath(output_path)}")
    print(f"   Otwórz go w przeglądarce, żeby zobaczyć swój Wrapped {YEAR}.")


if __name__ == "__main__":
    main()