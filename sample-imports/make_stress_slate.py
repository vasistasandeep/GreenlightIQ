"""Generate a larger stress-test slate (CSV) for the Asset Studio Batch Slate tab.

Deterministic (fixed seed) so re-running produces the identical file. Emits N
mostly-valid rows across every asset type, currency, territory mix, and genre,
with a small, fixed set of deliberately invalid rows so the accepted/rejected
summary is exercised at volume.

Usage:  python make_stress_slate.py [N]   (default N = 300)
Writes: stress-slate.csv next to this script.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ASSET_TYPES = ["ORIGINAL_SERIES", "ORIGINAL_FILM", "LICENSED_LIBRARY", "CO_PRODUCTION"]
CURRENCIES = ["USD", "INR", "EUR", "GBP"]
GENRES = ["sci-fi", "drama", "thriller", "comedy", "romance", "horror",
          "action", "documentary", "fantasy", "crime"]
TERRITORY_POOL = ["US", "GB", "DE", "FR", "IN", "CA", "AU", "JP", "BR", "ES"]
WORDS_A = ["Silent", "Crimson", "Last", "Hidden", "Broken", "Golden", "Northern",
           "Velvet", "Echo", "Midnight", "Paper", "Iron", "Neon", "Quiet", "Wild"]
WORDS_B = ["Harbor", "Protocol", "Lanes", "Reruns", "Horizon", "Tide", "City",
           "Signal", "Garden", "Circuit", "Diaries", "Road", "Season", "Empire"]


def rand_title(rng: random.Random, used: set[str]) -> str:
    for _ in range(50):
        name = f"{rng.choice(WORDS_A)} {rng.choice(WORDS_B)}"
        suffix = rng.choice(["", "", "", f" Vol. {rng.randint(1, 9)}", " II", " Reborn"])
        candidate = (name + suffix).strip()
        if candidate not in used:
            used.add(candidate)
            return candidate
    # Fallback: guarantee uniqueness.
    name = f"Project {len(used) + 1}"
    used.add(name)
    return name


def rand_cost(rng: random.Random, asset_type: str) -> str:
    if asset_type == "LICENSED_LIBRARY":
        return f"{rng.uniform(300_000, 3_000_000):.2f}"
    if asset_type == "ORIGINAL_FILM":
        return f"{rng.uniform(5_000_000, 60_000_000):.2f}"
    return f"{rng.uniform(15_000_000, 90_000_000):.2f}"  # series / co-production


def rand_territories(rng: random.Random) -> str:
    k = rng.randint(1, 4)
    return ";".join(rng.sample(TERRITORY_POOL, k))


def rand_hours(rng: random.Random, asset_type: str) -> str:
    if asset_type == "LICENSED_LIBRARY":
        return f"{rng.uniform(40_000_000, 80_000_000):.2f}"
    if asset_type == "ORIGINAL_FILM":
        return f"{rng.uniform(25_000_000, 60_000_000):.2f}"
    return f"{rng.uniform(120_000_000, 260_000_000):.2f}"


def main(n: int) -> None:
    rng = random.Random(42)  # fixed seed -> reproducible file
    header = ("title_name,asset_type,acquisition_cost_or_budget,native_currency,"
              "target_territories,genre_tag,projected_viewing_hours")
    rows = [header]
    used: set[str] = set()

    for _ in range(n):
        atype = rng.choice(ASSET_TYPES)
        title = rand_title(rng, used)
        rows.append(",".join([
            title,
            atype,
            rand_cost(rng, atype),
            rng.choice(CURRENCIES),
            rand_territories(rng),
            rng.choice(GENRES),
            rand_hours(rng, atype),
        ]))

    # A fixed handful of invalid rows so partial-acceptance is exercised.
    rows.append("Reject - no price,ORIGINAL_FILM,,USD,US,drama,30000000.00")
    rows.append("Reject - bad type,SPECIAL,5000000.00,USD,US,drama,25000000.00")
    rows.append("Reject - cost too high,ORIGINAL_SERIES,1500000000.00,USD,US,drama,200000000.00")
    rows.append(",LICENSED_LIBRARY,900000.00,EUR,DE,comedy,50000000.00")  # missing title

    out = Path(__file__).with_name("stress-slate.csv")
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"Wrote {out}: {n} valid rows + 4 deliberate rejects = {len(rows) - 1} data rows.")


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    main(count)