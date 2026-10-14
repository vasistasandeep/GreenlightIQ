"""Generate a SonyLIV-style demo slate for the Asset Studio Batch Slate tab.

Produces `sonyliv-slate.csv` and `sonyliv-slate.json` with INVENTED titles (no
real SonyLIV IP) that mirror the content mix of a real OTT 2026 content calendar:
live sports (cricket / football / tennis / WWE / UFC / kabaddi / golf / F-E),
Hindi and regional-language originals and movies, reality shows, live events /
awards, and licensed library. The mix exercises the churn model's genre and
content-format drivers across Indian-language genres, INR-heavy currencies, and
Indian territories.

Deterministic (fixed seed) so re-running produces identical files. Stdlib only.

Columns (ingest fields; genre_tag + content_format ride in the snapshot and are
used at valuation time): title_name, asset_type, acquisition_cost_or_budget,
native_currency, target_territories, genre_tag, content_format,
projected_viewing_hours.
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
RNG = random.Random("cineroi-sonyliv-slate-v1")

# (title, asset_type, currency, territories, genre, content_format, cost_range, hours_range)
# asset_type is constrained to the 4 engine values; content_format carries the
# OTT format signal (live-sports, reality-competition, etc.).
IN = ["IN"]
IN_SEA = ["IN", "SEA"]
GLOBAL = ["IN", "GB", "US"]

LIVE_SPORTS = [
    ("Bharat T20 Smash {yr}", "cricket"),
    ("Subcontinent Premier Cricket {yr}", "cricket"),
    ("Metro Football League {yr}", "football"),
    ("Grand Slam Mumbai Open {yr}", "tennis"),
    ("Pro Kabaddi Clash {yr}", "kabaddi"),
    ("National Badminton Masters {yr}", "badminton"),
    ("Desi Golf Invitational {yr}", "golf"),
    ("Electric GP India {yr}", "motorsport"),
]
LIVE_EVENTS = [
    ("Ring Kings Live: {city}", "wwe"),
    ("Cage Fury Night: {city}", "ufc"),
    ("Screen Legends Awards {yr}", "awards"),
    ("Monsoon Music Fest Live {yr}", "music"),
]
REALITY = [
    ("Crorepati Chronicles S{n}", "reality"),
    ("Kitchen Kings S{n}", "reality"),
    ("Dance Dangal S{n}", "reality"),
    ("Startup Shark Tank Desi S{n}", "reality"),
    ("Comedy Clash Live S{n}", "reality"),
]
ORIGINALS = [
    ("The Ledger Keepers S{n}", "crime", "Hindi"),
    ("Mumbai Noir S{n}", "crime-biopic", "Hindi"),
    ("Chambal Shadows S{n}", "thriller", "Hindi"),
    ("Kaveri Tides S{n}", "drama", "Tamil"),
    ("Deccan Files S{n}", "thriller", "Telugu"),
    ("Konkan Diaries S{n}", "drama", "Marathi"),
    ("Backwater Secrets S{n}", "mystery", "Malayalam"),
    ("City of Spies S{n}", "action", "Hindi"),
    ("Gullak Lane S{n}", "comedy", "Hindi"),
]
FILMS = [
    ("Paper Boats", "drama", "Malayalam"),
    ("Last Local", "thriller", "Marathi"),
    ("Saffron Sky", "romance", "Hindi"),
    ("The Auditor", "crime", "Tamil"),
    ("Monsoon Wedding Redux", "romance", "Hindi"),
    ("Neon Bazaar", "action", "Telugu"),
    ("Silent Harbour", "mystery", "Malayalam"),
]
DOCS = [
    ("Making of a Champion", "documentary"),
    ("The Spice Route", "documentary"),
    ("Cricket Nation", "documentary"),
]
LIBRARY = [
    ("Golden Era Classics Vol. {n}", "comedy"),
    ("Retro Masala Nights Vol. {n}", "drama"),
    ("Evergreen Melodies Vol. {n}", "music"),
]

CITIES = ["Mumbai", "Delhi", "Bengaluru", "Chennai", "Kolkata", "Hyderabad"]


def _cost(lo: int, hi: int) -> str:
    # INR crore-scale costs, rounded to lakhs.
    v = RNG.randint(lo, hi) * 100000
    return f"{v}.00"


def _hours(lo: int, hi: int) -> str:
    return f"{RNG.randint(lo, hi) * 1000000}.00"


def _terr() -> list[str]:
    return RNG.choice([IN, IN, IN_SEA, GLOBAL])


def build() -> list[dict]:
    rows: list[dict] = []
    yr = 2026

    def add(name, atype, genre, fmt, cost, hours, cur="INR", terr=None):
        rows.append({
            "title_name": name,
            "asset_type": atype,
            "acquisition_cost_or_budget": cost,
            "native_currency": cur,
            "target_territories": terr or _terr(),
            "genre_tag": genre,
            "content_format": fmt,
            "projected_viewing_hours": hours,
        })

    # Live sports (big budgets, huge hours) - LICENSED_LIBRARY asset is how live
    # rights are typically filed; the content_format carries the live signal.
    for tmpl, genre in LIVE_SPORTS:
        add(tmpl.format(yr=yr), "LICENSED_LIBRARY", genre, "live-sports",
            _cost(2000, 9000), _hours(120, 320), "INR", _terr())
    # Live events (WWE/UFC/awards/music).
    for tmpl, genre in LIVE_EVENTS:
        add(tmpl.format(yr=yr, city=RNG.choice(CITIES)), "LICENSED_LIBRARY", genre,
            "live-event", _cost(300, 2500), _hours(10, 60), "INR", _terr())
    # Reality / competition series.
    for tmpl, genre in REALITY:
        add(tmpl.format(n=RNG.randint(2, 9)), "ORIGINAL_SERIES", genre,
            "reality-competition", _cost(400, 2200), _hours(40, 160), "INR", IN)
    # Originals (scripted series) across languages.
    for tmpl, genre, lang in ORIGINALS:
        add(f"{tmpl.format(n=RNG.randint(1, 5))} ({lang})", "ORIGINAL_SERIES", genre,
            "scripted-series", _cost(600, 3500), _hours(60, 220), "INR", _terr())
    # Films (originals).
    for name, genre, lang in FILMS:
        add(f"{name} ({lang})", "ORIGINAL_FILM", genre, "original-film",
            _cost(150, 1200), _hours(20, 60), "INR", _terr())
    # Documentaries.
    for name, genre in DOCS:
        add(name, "ORIGINAL_FILM", genre, "documentary",
            _cost(80, 400), _hours(8, 30), "INR", IN)
    # Licensed library bundles.
    for tmpl, genre in LIBRARY:
        add(tmpl.format(n=RNG.randint(3, 12)), "LICENSED_LIBRARY", genre, "library",
            _cost(60, 500), _hours(40, 120), "INR", _terr())
    return rows


CSV_COLS = [
    "title_name", "asset_type", "acquisition_cost_or_budget", "native_currency",
    "target_territories", "genre_tag", "content_format", "projected_viewing_hours",
]


def write_csv(rows: list[dict]) -> None:
    path = HERE / "sonyliv-slate.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLS)
        for r in rows:
            w.writerow([
                r["title_name"], r["asset_type"], r["acquisition_cost_or_budget"],
                r["native_currency"], ";".join(r["target_territories"]),
                r["genre_tag"], r["content_format"], r["projected_viewing_hours"],
            ])
    print(f"wrote {path} ({len(rows)} rows)")


def write_json(rows: list[dict]) -> None:
    path = HERE / "sonyliv-slate.json"
    path.write_text(json.dumps({"titles": rows}, indent=2), encoding="utf-8")
    print(f"wrote {path} ({len(rows)} rows)")


if __name__ == "__main__":
    rows = build()
    write_csv(rows)
    write_json(rows)