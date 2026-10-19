"""Generate the deterministic mock-seed SQL file (``02_seed_data.sql``).

Requirement 17.7 asks for initialization scripts that load mock seed data.
Hand-authoring 1536-dimension VECTOR literals is impractical, so this generator
emits a plain, reviewable, idempotent SQL file with:

  * one user per User_Role (DATA_ANALYST, CONTENT_BUYER, CHIEF_CONTENT_OFFICER,
    CFO) (R20.1),
  * one initial ACTIVE model version whose coupled weights sum to exactly 1.00
    (R12.2, R26.1),
  * a set of dated USD exchange rates (R21.4),
  * a handful of titles across every asset_type, each with an active
    title_version, a metadata_vectors row (1536-dim Narrative_DNA), and a
    financial_projections row stamped with the active model version,
  * license_terms for each title (R22), and
  * subscriber cluster preference vectors (1536-dim) for the Vector_Search_Engine
    (design R3), inserted into the seed-provided ``subscriber_clusters`` table.

Vectors are generated with a fixed RNG seed so the output is byte-stable across
runs — re-running the generator produces an identical SQL file, which keeps the
seed data reproducible and reviewable in version control.

Usage::

    python database/seed/generate_seed_sql.py            # writes 02_seed_data.sql
    python database/seed/generate_seed_sql.py --check     # fail if out of date

This script has no third-party dependencies and does not touch a database.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import uuid
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

# Import the pure churn domain so the seed and the Guardrails_Engine share one
# implementation (calculable-churn-model R9.2/R9.5). The module is stdlib-only
# (Decimal/dataclasses/typing) so this adds no heavy dependency and keeps the
# generator runnable as `python database/seed/generate_seed_sql.py`.
_BACKEND = Path(__file__).resolve().parent.parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.domain.churn import (  # noqa: E402
    DEFAULT_CHURN_MODEL_PARAMS,
    ChurnFeatures,
    calculate_churn_mitigation,
)
from app.domain.content_eval import (  # noqa: E402
    DEFAULT_CONTENT_EVAL_PARAMS,
    parse_content_eval_params,
)

DIMS = 1536
HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "02_seed_data.sql"

# Fixed namespace so UUIDs (and therefore the whole file) are deterministic.
_NS = uuid.UUID("8e4d3bce-30ce-4826-892f-951109055154")


def det_uuid(label: str) -> uuid.UUID:
    """A stable UUID derived from a label (uuid5 over a fixed namespace)."""
    return uuid.uuid5(_NS, label)


def unit_vector(label: str) -> list[float]:
    """A deterministic 1536-dim unit vector with every component in [-1, 1].

    Seeded by ``label`` so each named entity always gets the same vector. The
    vector is L2-normalized, which keeps every component within [-1.0, 1.0]
    (R2.1 bound) and makes cosine similarity well-behaved for R3 search.
    """
    rng = random.Random(f"cineroi-seed::{label}")
    raw = [rng.uniform(-1.0, 1.0) for _ in range(DIMS)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


def vec_literal(vec: list[float]) -> str:
    """Render a Python float list as a pgvector literal: '[v1,v2,...]'."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def q(value: str) -> str:
    """Single-quote and escape a string for a SQL literal."""
    return "'" + value.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Seed definitions (plain Python data; the SQL is rendered from these).
# ---------------------------------------------------------------------------

USERS = [
    # (label, display_name, role, authorized_territories)
    ("user-analyst", "Dana Analyst", "DATA_ANALYST", ["US", "GB"]),
    ("user-buyer", "Carl Buyer", "CONTENT_BUYER", ["US", "IN", "GB"]),
    ("user-cco", "Chris Content-Officer", "CHIEF_CONTENT_OFFICER", ["US", "IN", "GB", "DE"]),
    ("user-cfo", "Fran Finance", "CFO", ["US", "IN", "GB", "DE", "FR"]),
]

def _churn_model_params_json() -> dict:
    """Serialize :data:`DEFAULT_CHURN_MODEL_PARAMS` into the JSON object stored
    under ``guardrail_params["churn_model"]`` (calculable-churn-model R9.2).

    Derived programmatically from the imported domain defaults so the embedded
    seed JSON can never drift from the engine's parameters. Decimals are emitted
    as strings for exactness; ``parse_params`` coerces each via ``Decimal(str(x))``.
    """
    p = DEFAULT_CHURN_MODEL_PARAMS
    return {
        "intercept": str(p.intercept),
        "asset_offsets": {k: str(v) for k, v in p.asset_offsets.items()},
        "pedigree_weight": str(p.pedigree_weight),
        "scale_weight": str(p.scale_weight),
        "exclusivity_lift": str(p.exclusivity_lift),
        "telemetry_weight": str(p.telemetry_weight),
        "min_churn": str(p.min_churn),
        "max_churn": str(p.max_churn),
        # Genre driver + neutral defaults (calculable-churn-model Addendum A).
        "genre_offsets": {k: str(v) for k, v in p.genre_offsets.items()},
        "genre_default": str(p.genre_default),
        "telemetry_neutral": str(p.telemetry_neutral),
        # Content-format lifts (calculable-churn-model Addendum B, R17).
        "format_offsets": {k: str(v) for k, v in p.format_offsets.items()},
        "format_default": str(p.format_default),
    }


def _content_eval_params_json() -> dict:
    """Serialize the illustrative :data:`DEFAULT_CONTENT_EVAL_PARAMS` into the JSON
    object stored under ``guardrail_params["content_eval"]`` (content-eval-model
    R5.1, design Component 9).

    Derived programmatically from the imported domain defaults so the embedded
    seed JSON can never drift from the model's illustrative parameters. Decimals
    are emitted as strings for exactness; the churn-style full-fallback parsers
    coerce each value back.

    The block carries ONLY illustrative state:

    * ``version_label`` == ``"illustrative"`` and ``fit_dataset_version`` == ``null``
      (``None``) -> NO active fitted version, so every driver resolves through the
      deterministic/illustrative fallback exactly as before this feature existed.
    * ``link_churn_to_ltv`` == ``false`` -> the modeled churn is never folded into
      the LTV numerator, so ``churn_reduction_value`` keeps today's behavior.

    Because no fitted version is active and the link is off, the block is INERT at
    seed time: it is carried in ``guardrail_params`` for later use and changes no
    seeded projection, driver, churn value, or verdict (Property 12).
    """
    p = DEFAULT_CONTENT_EVAL_PARAMS
    vh = p.viewing_hours
    wte = p.watch_time_elasticity
    alr = p.ad_load_receptivity
    return {
        "version_label": p.version_label,
        "fit_dataset_version": p.fit_dataset_version,  # None -> JSON null
        "dominant_label_type": p.dominant_label_type,
        "link_churn_to_ltv": p.link_churn_to_ltv,
        "viewing_hours": {
            "intercept": str(vh.intercept),
            "betas": {k: str(v) for k, v in vh.betas.items()},
            "floor": str(vh.floor),
            "objective": vh.objective,
        },
        "engagement": {
            "watch_time_elasticity": {
                "intercept": str(wte.intercept),
                "runtime_weight": str(wte.runtime_weight),
                "serialization_lift": str(wte.serialization_lift),
                "rating_weight": str(wte.rating_weight),
                "franchise_lift": str(wte.franchise_lift),
                "min_value": str(wte.min_value),
                "max_value": str(wte.max_value),
                "genre_offsets": {k: str(v) for k, v in wte.genre_offsets.items()},
                "genre_default": str(wte.genre_default),
                "format_lifts": {k: str(v) for k, v in wte.format_lifts.items()},
                "format_default": str(wte.format_default),
            },
            "ad_load_receptivity": {
                "centre": str(alr.centre),
                "rating_weight": str(alr.rating_weight),
                "runtime_weight": str(alr.runtime_weight),
                "franchise_lift": str(alr.franchise_lift),
                "min_value": str(alr.min_value),
                "max_value": str(alr.max_value),
                "genre_offsets": {k: str(v) for k, v in alr.genre_offsets.items()},
                "genre_default": str(alr.genre_default),
            },
        },
    }


# Initial active model version — weights sum to exactly 1.00 (R12.2, R26.1).
MODEL_VERSION = {
    "label": "model-version-initial",
    "talent_pedigree_weight": "0.60",
    "narrative_trope_weight": "0.40",
    "guardrail_params": {
        "cpvh_ceiling_premium_original": 0.18,
        "cpvh_ceiling_library_filler": 0.05,
        "ltv_to_cost_min": 3.2,
        "churn_mitigation_min_pct": 1.5,
        "payback_target_months": [9, 12],
        # Illustrative churn-model coefficients, versioned with the active model
        # (calculable-churn-model R3.1/R9.2). Carried forward unchanged on
        # calibration forks; read by the engine via parse_params.
        "churn_model": _churn_model_params_json(),
        # Illustrative content_eval params (content-eval-model R5.1, design
        # Component 9). NO fitted version active (version_label "illustrative",
        # fit_dataset_version null) and link_churn_to_ltv off, so the block is
        # inert at seed time: carried forward for later use, changing no seeded
        # projection, driver, churn value, or verdict (Property 12). Carried
        # forward unchanged on calibration forks; read via parse_content_eval_params.
        "content_eval": _content_eval_params_json(),
    },
}

# Dated USD normalization rates (R21.4). to_currency is always USD (base).
EXCHANGE_RATES = [
    # (from, to, rate, rate_date)
    ("USD", "USD", "1.00000000", "2024-01-02"),
    ("INR", "USD", "0.01200000", "2024-01-02"),
    ("EUR", "USD", "1.09000000", "2024-01-02"),
    ("GBP", "USD", "1.27000000", "2024-01-02"),
]

TITLES = [
    # label, name, asset_type, cost, currency, territories, genre, viewing_hours,
    # is_historical, cpvh, ltv, churn_pct, payback_months, recommendation
    (
        "title-aurora", "Aurora Protocol", "ORIGINAL_SERIES", "42000000.00", "USD",
        ["US", "GB", "DE"], "sci-fi", "250000000.00", False,
        "0.1680", "3.80", "2.10", 11, "GREENLIGHT",
    ),
    (
        "title-monsoon", "Monsoon Lanes", "CO_PRODUCTION", "18000000.00", "INR",
        ["IN", "GB"], "drama", "140000000.00", False,
        "0.1286", "3.35", "1.80", 12, "GREENLIGHT",
    ),
    (
        "title-ledger", "The Ledger", "ORIGINAL_FILM", "9500000.00", "USD",
        ["US"], "thriller", "40000000.00", False,
        "0.2375", "2.90", "1.60", 15, "NEGOTIATE_HARD",
    ),
    (
        "title-reruns", "Vintage Reruns Vol. 7", "LICENSED_LIBRARY", "1200000.00", "EUR",
        ["DE", "FR"], "comedy", "60000000.00", False,
        "0.0200", "4.10", "0.90", 8, "PASS",
    ),
    (
        "title-echoes", "Echoes of 2019", "ORIGINAL_SERIES", "30000000.00", "USD",
        ["US", "GB"], "drama", "180000000.00", True,
        "0.1667", "3.50", "2.00", 10, "GREENLIGHT",
    ),
    # --- SonyLIV-style OTT catalog (invented titles; INR; Indian territories) ---
    # Churn is the model's output (neutral telemetry); cpvh/ltv/payback produce
    # the stated verdict. kaveri/paperboats use SEA to avoid the drama/IN telemetry
    # row (keeps their churn neutral and the verified value).
    (
        "title-sl-ipl", "Bharat T20 Smash 2026", "LICENSED_LIBRARY", "820000000.00", "INR",
        ["IN"], "cricket", "296000000.00", False,
        "0.0480", "3.90", "2.23", 10, "GREENLIGHT",
    ),
    (
        "title-sl-crorepati", "Crorepati Chronicles S7", "ORIGINAL_SERIES", "180000000.00", "INR",
        ["IN"], "reality", "130000000.00", False,
        "0.1500", "3.60", "2.32", 11, "GREENLIGHT",
    ),
    (
        "title-sl-mumbainoir", "Mumbai Noir S2 (Hindi)", "ORIGINAL_SERIES", "240000000.00", "INR",
        ["IN", "SEA"], "crime-biopic", "110000000.00", False,
        "0.1600", "3.80", "2.01", 12, "GREENLIGHT",
    ),
    (
        "title-sl-football", "Metro Football League 2026", "LICENSED_LIBRARY", "780000000.00", "INR",
        ["IN", "SEA"], "football", "272000000.00", False,
        "0.0490", "3.40", "1.86", 12, "GREENLIGHT",
    ),
    (
        "title-sl-ringkings", "Ring Kings Live Chennai", "LICENSED_LIBRARY", "320000000.00", "INR",
        ["IN", "SEA"], "wwe", "35000000.00", False,
        "0.0520", "3.50", "1.88", 11, "NEGOTIATE_HARD",
    ),
    (
        "title-sl-kaveri", "Kaveri Tides S1 (Tamil)", "ORIGINAL_SERIES", "150000000.00", "INR",
        ["SEA"], "drama", "90000000.00", False,
        "0.1900", "3.10", "1.80", 14, "NEGOTIATE_HARD",
    ),
    (
        "title-sl-deccan", "Deccan Files S1 (Telugu)", "ORIGINAL_SERIES", "130000000.00", "INR",
        ["IN"], "thriller", "80000000.00", False,
        "0.1700", "3.00", "1.49", 13, "PASS",
    ),
    (
        "title-sl-paperboats", "Paper Boats (Malayalam)", "ORIGINAL_FILM", "90000000.00", "INR",
        ["SEA"], "drama", "42000000.00", False,
        "0.2000", "2.80", "1.43", 14, "PASS",
    ),
    (
        "title-sl-spiceroute", "The Spice Route", "ORIGINAL_FILM", "60000000.00", "INR",
        ["IN"], "documentary", "20000000.00", False,
        "0.1900", "3.30", "0.96", 12, "PASS",
    ),
    (
        "title-sl-classics", "Golden Era Classics Vol. 7", "LICENSED_LIBRARY", "50000000.00", "INR",
        ["IN"], "comedy", "60000000.00", False,
        "0.0300", "4.20", "0.69", 8, "PASS",
    ),
]

# Seeded acquisition deal stage per title (deal-stage lifecycle). Chosen to span
# the pipeline so the dashboard shows a realistic mix of stages.
DEAL_STAGE_BY_TITLE = {
    "title-aurora": "APPROVED",       # strong GREENLIGHT, deal approved
    "title-monsoon": "IN_NEGOTIATION",
    "title-ledger": "EVALUATED",      # NEGOTIATE_HARD, still being worked
    "title-reruns": "SCREENING",
    "title-echoes": "CLOSED_WON",     # historical, deal done
    "title-sl-ipl": "APPROVED",
    "title-sl-crorepati": "APPROVED",
    "title-sl-mumbainoir": "IN_NEGOTIATION",
    "title-sl-football": "SCREENING",
    "title-sl-ringkings": "EVALUATED",
    "title-sl-kaveri": "EVALUATED",
    "title-sl-deccan": "SCREENING",
    "title-sl-paperboats": "SCREENING",
    "title-sl-spiceroute": "SCREENING",
    "title-sl-classics": "PASSED",
}


LICENSE_TERMS = [
    # title_label, duration_months, exclusive, windowing_rules, milestones
    ("title-aurora", 36, True,
     {"windows": [{"type": "exclusive", "months": 24}, {"type": "non_exclusive", "months": 12}]},
     [{"month": 0, "amount": 21000000.0}, {"month": 12, "amount": 21000000.0}]),
    ("title-monsoon", 24, False,
     {"windows": [{"type": "non_exclusive", "months": 24}]},
     [{"month": 0, "amount": 9000000.0}, {"month": 6, "amount": 9000000.0}]),
    ("title-ledger", 18, True,
     {"windows": [{"type": "exclusive", "months": 18}]},
     [{"month": 0, "amount": 9500000.0}]),
    ("title-reruns", 12, False,
     {"windows": [{"type": "non_exclusive", "months": 12}]},
     [{"month": 0, "amount": 1200000.0}]),
    ("title-echoes", 24, True,
     {"windows": [{"type": "exclusive", "months": 24}]},
     [{"month": 0, "amount": 15000000.0}, {"month": 12, "amount": 15000000.0}]),
    # SonyLIV-style titles. Live sports/events are shorter-term exclusive rights;
    # series 24m, films 18m, library 12m. Single milestone at signing (keeps the
    # payback input simple and consistent with the stored payback_horizon).
    ("title-sl-ipl", 12, True,
     {"windows": [{"type": "exclusive", "months": 12}]},
     [{"month": 0, "amount": 9840000.0}]),
    ("title-sl-crorepati", 24, True,
     {"windows": [{"type": "exclusive", "months": 24}]},
     [{"month": 0, "amount": 2160000.0}]),
    ("title-sl-mumbainoir", 24, True,
     {"windows": [{"type": "exclusive", "months": 24}]},
     [{"month": 0, "amount": 2880000.0}]),
    ("title-sl-football", 12, False,
     {"windows": [{"type": "non_exclusive", "months": 12}]},
     [{"month": 0, "amount": 9360000.0}]),
    ("title-sl-ringkings", 12, True,
     {"windows": [{"type": "exclusive", "months": 12}]},
     [{"month": 0, "amount": 3840000.0}]),
    ("title-sl-kaveri", 24, True,
     {"windows": [{"type": "exclusive", "months": 24}]},
     [{"month": 0, "amount": 1800000.0}]),
    ("title-sl-deccan", 24, False,
     {"windows": [{"type": "non_exclusive", "months": 24}]},
     [{"month": 0, "amount": 1560000.0}]),
    ("title-sl-paperboats", 18, True,
     {"windows": [{"type": "exclusive", "months": 18}]},
     [{"month": 0, "amount": 1080000.0}]),
    ("title-sl-spiceroute", 18, False,
     {"windows": [{"type": "non_exclusive", "months": 18}]},
     [{"month": 0, "amount": 720000.0}]),
    ("title-sl-classics", 12, False,
     {"windows": [{"type": "non_exclusive", "months": 12}]},
     [{"month": 0, "amount": 600000.0}]),
]

# Market telemetry per (genre_tag, territory) pair, covering every pair the
# seed titles target (R13.2). Values are plausible demo signals:
#   social_sentiment_index         - display-only buzz index (not weighted).
#   chart_velocity_score           - chart momentum; lifts LTV weight by score/100.
#   licensing_inflation_multiplier - ad-inventory cost vs baseline; the CPM weight.
# source_available=TRUE marks a fresh (non-stale) poll.
TELEMETRY = [
    # (genre, territory, sentiment, velocity, inflation)
    ("sci-fi", "US", "0.72", "6.0", "1.08"),
    ("sci-fi", "GB", "0.65", "4.5", "1.04"),
    ("sci-fi", "DE", "0.58", "3.0", "1.02"),
    ("drama", "US", "0.61", "3.5", "1.05"),
    ("drama", "GB", "0.57", "2.5", "1.03"),
    ("drama", "IN", "0.69", "7.0", "0.98"),
    ("thriller", "US", "0.63", "5.0", "1.06"),
    ("comedy", "DE", "0.52", "2.0", "1.01"),
    ("comedy", "FR", "0.55", "2.5", "1.02"),
]

# Fast lookup used by the projection back-fill to replicate the engine's
# territory weighting (see _title_weights).
_TELEMETRY_BY_PAIR = {
    (genre, terr): (sentiment, velocity, inflation)
    for genre, terr, sentiment, velocity, inflation in TELEMETRY
}


def _title_weights(genre: str, territories: list[str]) -> tuple[float, float]:
    """Replicate Guardrails_Engine._territory_weighting for the seed back-fill.

    cpm_weight = mean(licensing_inflation_multiplier) across territories;
    ltv_weight = mean(1 + chart_velocity_score / 100). A pair with no telemetry
    contributes a neutral 1, matching the engine. Returns (cpm_weight, ltv_weight).
    """
    if not territories:
        return 1.0, 1.0
    cpm_mults: list[float] = []
    ltv_mults: list[float] = []
    for terr in territories:
        reading = _TELEMETRY_BY_PAIR.get((genre, terr))
        if reading is None:
            cpm_mults.append(1.0)
            ltv_mults.append(1.0)
            continue
        _sentiment, velocity, inflation = reading
        cpm_mults.append(float(inflation))
        ltv_mults.append(1.0 + float(velocity) / 100.0)
    return (sum(cpm_mults) / len(cpm_mults), sum(ltv_mults) / len(ltv_mults))


def _telemetry_heat(genre: str, territories: list[str]) -> Decimal | None:
    """Replicate the engine's Telemetry_Heat for the seed (R6.3-R6.5).

    The mean, over the title's target territories that have a cached
    ``social_sentiment_index`` for the genre, of that index multiplied by 100,
    rounded to 2 decimal places half-up. Territories with no reading are
    excluded; a title with no readings at all yields ``None`` (a missing feature).
    """
    readings: list[Decimal] = []
    for terr in territories:
        reading = _TELEMETRY_BY_PAIR.get((genre, terr))
        if reading is None:
            continue
        sentiment = reading[0]
        readings.append(Decimal(sentiment) * Decimal("100"))
    if not readings:
        return None
    mean = sum(readings) / Decimal(len(readings))
    return mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# Seeded per-title feature inputs for the churn model (R9.5). Pedigree/scale come
# from `scores`, exclusivity from `LICENSE_TERMS`, asset type and genre/territories
# from `TITLES`. Built once so the snapshot/projection/explanation agree.
_PEDIGREE_SCALE = {
    "title-aurora": ("8.50", "9.00"),
    "title-monsoon": ("7.20", "6.50"),
    "title-ledger": ("6.00", "5.50"),
    "title-reruns": ("4.00", "3.50"),
    "title-echoes": ("7.80", "7.00"),
    "title-sl-ipl": ("7.00", "9.00"),
    "title-sl-crorepati": ("7.00", "7.00"),
    "title-sl-mumbainoir": ("8.00", "8.00"),
    "title-sl-football": ("6.00", "8.00"),
    "title-sl-ringkings": ("6.00", "7.00"),
    "title-sl-kaveri": ("6.50", "6.00"),
    "title-sl-deccan": ("6.00", "5.50"),
    "title-sl-paperboats": ("5.00", "5.00"),
    "title-sl-spiceroute": ("4.00", "4.00"),
    "title-sl-classics": ("3.00", "3.00"),
}
_EXCLUSIVE_BY_TITLE = {label: exclusive for label, _d, exclusive, _w, _m in LICENSE_TERMS}

# Aligned OTT content format per seeded title (calculable-churn-model R17). Each
# matches the title's asset type, so the format lift is 0 and the seeded churn is
# unchanged; the breakdown still shows an explicit Content Format row.
_FORMAT_BY_TITLE = {
    "title-aurora": "scripted-series",
    "title-monsoon": "scripted-series",
    "title-ledger": "original-film",
    "title-reruns": "library",
    "title-echoes": "scripted-series",
    "title-sl-ipl": "live-sports",
    "title-sl-crorepati": "reality-competition",
    "title-sl-mumbainoir": "scripted-series",
    "title-sl-football": "live-sports",
    "title-sl-ringkings": "live-event",
    "title-sl-kaveri": "scripted-series",
    "title-sl-deccan": "scripted-series",
    "title-sl-paperboats": "original-film",
    "title-sl-spiceroute": "documentary",
    "title-sl-classics": "library",
}


def _title_churn_result(label: str, atype: str, genre: str, territories: list[str]):
    """Compute the model Churn_Result for a seeded title (R9.5).

    Builds :class:`ChurnFeatures` from the seeded features and runs the shared
    :func:`calculate_churn_mitigation`, so the stored projection and explanation
    exactly match a live engine recompute.
    """
    pedigree, scale = _PEDIGREE_SCALE[label]
    features = ChurnFeatures(
        asset_type=atype,
        pedigree=Decimal(pedigree),
        production_scale=Decimal(scale),
        is_exclusive=_EXCLUSIVE_BY_TITLE.get(label, False),
        telemetry_heat=_telemetry_heat(genre, territories),
        genre=genre,
        content_format=_FORMAT_BY_TITLE.get(label),
    )
    return calculate_churn_mitigation(
        features, DEFAULT_CHURN_MODEL_PARAMS, "MODEL_VERSION"
    )


def _churn_model_explanation(churn_result) -> dict:
    """Build the flat ``churn_model`` object embedded in the seeded explanation,
    matching the engine's ``_churn_model_json`` shape for a CALCULATED result
    (calculable-churn-model R7.2/R9.5).

    Decimals are rendered as strings; ``bounds_adjustment`` is included only when
    the breakdown carries it (the domain omits a zero adjustment). The
    ``model_version_id`` is the seeded active model version id.
    """
    breakdown = {
        contribution.key: str(contribution.points)
        for contribution in churn_result.breakdown
    }
    return {
        "churn_method": churn_result.method,
        "is_borderline": churn_result.is_borderline,
        "params_source": "MODEL_VERSION",
        "model_version_id": str(det_uuid(MODEL_VERSION["label"])),
        "missing_features": list(churn_result.missing_features),
        "churn_breakdown": breakdown,
    }


CLUSTERS = [
    ("cluster-prestige-drama", "Prestige Drama Loyalists",
     "Subscribers who favor award-season dramas and limited series."),
    ("cluster-genre-thrill", "Genre & Thriller Bingers",
     "High-velocity viewers of sci-fi, thriller, and action."),
    ("cluster-comfort-library", "Comfort Library Watchers",
     "Long-tail library and comedy re-watchers."),
    ("cluster-global-local", "Global-Local Explorers",
     "Cross-border viewers of co-productions and local-language originals."),
]


def _json(obj) -> str:
    """Compact deterministic JSON (sorted keys) rendered as a SQL literal."""
    import json

    return q(json.dumps(obj, sort_keys=True, separators=(",", ":")))


def _seed_explanation(atype, cpvh, ltv, churn, payback, churn_result=None):
    """Build an engine-shaped Explanation (with a full `checks` array) for the seed.

    Decimal-ish values are emitted as strings to match how the engine serializes
    them into JSONB. Shortfall is the normalized distance past the threshold for a
    breached check (|distance| / threshold); None when the check passes.

    ``churn`` is the model-computed churn value stored on the projection, so the
    CHURN_MITIGATION check agrees with the stored column. When ``churn_result`` is
    supplied, a flat ``churn_model`` object matching the engine's shape is embedded
    (calculable-churn-model R7.2/R9.5).
    """
    ceiling = 0.05 if atype == "LICENSED_LIBRARY" else 0.18
    cpvh_f, ltv_f, churn_f, pay_i = float(cpvh), float(ltv), float(churn), int(payback)

    def shortfall(distance: float, threshold: float):
        return f"{abs(distance) / threshold:.6f}" if threshold else f"{abs(distance):.6f}"

    cpvh_breach = cpvh_f > ceiling
    ltv_breach = ltv_f < 3.2
    churn_breach = churn_f < 1.5
    pay_breach = pay_i > 12

    checks = [
        {
            "name": "CPVH",
            "computed_value": f"{cpvh_f:.4f}",
            "threshold": f"{ceiling:.2f}",
            "passed": not cpvh_breach,
            "breached": cpvh_breach,
            "shortfall_magnitude": shortfall(cpvh_f - ceiling, ceiling) if cpvh_breach else None,
            "correctable": True if cpvh_breach else None,
        },
        {
            "name": "LTV_TO_COST",
            "computed_value": f"{ltv_f:.4f}",
            "threshold": "3.2",
            "passed": not ltv_breach,
            "breached": ltv_breach,
            "shortfall_magnitude": shortfall(3.2 - ltv_f, 3.2) if ltv_breach else None,
            "correctable": True if ltv_breach else None,
        },
        {
            "name": "CHURN_MITIGATION",
            "computed_value": f"{churn_f:.2f}",
            "threshold": "1.5",
            "passed": not churn_breach,
            "breached": churn_breach,
            "shortfall_magnitude": shortfall(1.5 - churn_f, 1.5) if churn_breach else None,
            "correctable": False if churn_breach else None,
        },
        {
            "name": "PAYBACK_HORIZON",
            "computed_value": str(pay_i),
            "threshold": "12",
            "passed": not pay_breach,
            "breached": pay_breach,
            "shortfall_magnitude": shortfall(float(pay_i - 12), 12.0) if pay_breach else None,
            "correctable": True if pay_breach else None,
        },
    ]

    # Dominant factor: the breached check with the largest normalized shortfall.
    breaches = [c for c in checks if c["breached"]]
    dominant = None
    if breaches:
        dominant = max(
            breaches, key=lambda c: float(c["shortfall_magnitude"] or 0)
        )["name"]

    explanation = {
        "checks": checks,
        "dominant_factor": dominant,
        "unclassifiable": False,
    }
    if churn_result is not None:
        explanation["churn_model"] = _churn_model_explanation(churn_result)
    return explanation


def _self_check() -> None:
    """Guard the invariants the regenerated seed must hold.

    * The embedded ``churn_model`` JSON parses back to the imported defaults, so
      it can never drift from the domain parameters (calculable-churn-model R9.2).
    * The five seeded titles keep their verdict-preserving churn tolerances
      (R9.3/R9.4): Aurora/Echoes/Monsoon strictly above 1.5, Ledger in
      [1.60, 1.65], Vintage Reruns in [0.80, 0.90].
    """
    from app.domain.churn import parse_params

    parsed, source = parse_params(MODEL_VERSION["guardrail_params"]["churn_model"])
    assert source == "MODEL_VERSION", "embedded churn_model failed to parse"
    assert parsed == DEFAULT_CHURN_MODEL_PARAMS, (
        "embedded churn_model JSON drifted from DEFAULT_CHURN_MODEL_PARAMS"
    )

    # The embedded content_eval block round-trips to the illustrative defaults
    # (content-eval-model R5.1/R5.5, Property 12): it parses as a usable mapping,
    # resolves to byte-identical DEFAULT_CONTENT_EVAL_PARAMS, and — crucially —
    # carries NO active fitted version (fit_dataset_version null) with the
    # churn->LTV link OFF, so it is inert at seed time and no verdict can move.
    ce = parse_content_eval_params(MODEL_VERSION["guardrail_params"]["content_eval"])
    assert ce.source == "MODEL_VERSION", "embedded content_eval failed to parse"
    assert ce.fit_dataset_version is None, (
        "seed content_eval must NOT pin a fitted dataset version"
    )
    assert ce.link_churn_to_ltv is False, (
        "seed content_eval must keep link_churn_to_ltv off"
    )
    # Every PARAMETER must resolve to the illustrative defaults (only the source
    # tags differ: the block IS supplied by the model version, so each nested
    # source is "MODEL_VERSION" rather than "DEFAULTS"). The equal parameters
    # guarantee the block changes no modeled value vs the pre-feature baseline.
    _d = DEFAULT_CONTENT_EVAL_PARAMS
    assert ce.version_label == _d.version_label, "content_eval version_label drifted"
    assert ce.dominant_label_type == _d.dominant_label_type, (
        "content_eval dominant_label_type drifted"
    )
    assert ce.viewing_hours == _d.viewing_hours, (
        "embedded viewing_hours JSON drifted from DEFAULT_VIEWING_HOURS_PARAMS"
    )
    assert ce.watch_time_elasticity == _d.watch_time_elasticity, (
        "embedded watch_time_elasticity JSON drifted from its defaults"
    )
    assert ce.ad_load_receptivity == _d.ad_load_receptivity, (
        "embedded ad_load_receptivity JSON drifted from its defaults"
    )
    # The block is fully supplied by the model version, so each nested parser
    # reports "MODEL_VERSION" (confirming the serialization round-trips cleanly
    # rather than silently falling back to defaults).
    assert ce.viewing_hours_source == "MODEL_VERSION", "viewing_hours fell back"
    assert ce.watch_time_elasticity_source == "MODEL_VERSION", "WTE fell back"
    assert ce.ad_load_receptivity_source == "MODEL_VERSION", "ALR fell back"

    tolerances = {
        # label: (low, high) inclusive bounds the computed churn must fall in
        "title-aurora": (Decimal("2.06"), Decimal("2.15")),
        "title-echoes": (Decimal("1.94"), Decimal("2.04")),
        "title-monsoon": (Decimal("1.74"), Decimal("1.84")),
        "title-ledger": (Decimal("1.60"), Decimal("1.65")),
        "title-reruns": (Decimal("0.80"), Decimal("0.90")),
    }
    title_by_label = {t[0]: t for t in TITLES}
    for label, (low, high) in tolerances.items():
        t = title_by_label[label]
        _l, _n, atype, _c, _cur, terrs, genre, *_rest = t
        value = _title_churn_result(label, atype, genre, terrs).churn_reduction_pct
        assert low <= value <= high, (
            f"{label} churn {value} outside tolerance [{low}, {high}]"
        )


def render() -> str:
    _self_check()
    out: list[str] = []
    w = out.append

    w("-- =============================================================================")
    w("-- CineROI AI — mock seed data (Requirement 17.7)")
    w("-- =============================================================================")
    w("--")
    w("-- GENERATED FILE — do not edit by hand. Regenerate with:")
    w("--     python database/seed/generate_seed_sql.py")
    w("--")
    w("-- Prerequisite: the Alembic schema must exist (alembic upgrade head) and")
    w("-- 01_schema.sql must have created subscriber_clusters. Running seed.py does")
    w("-- both for you. This script is idempotent via ON CONFLICT DO NOTHING on the")
    w("-- deterministic primary keys below.")
    w("--")
    w("-- Transaction boundaries are owned by the caller (seed.py wraps the whole")
    w("-- script in a single transaction), so this file intentionally emits NO")
    w("-- BEGIN/COMMIT of its own — an inner COMMIT would close the caller's")
    w("-- transaction early and break container-startup initialization (R18.4).")
    w("-- =============================================================================")
    w("")

    # --- users (one per role) -------------------------------------------------
    w("-- Users: exactly one per User_Role (R20.1).")
    w("INSERT INTO users (user_id, external_subject, display_name, user_role, "
      "authorized_territories) VALUES")
    rows = []
    for label, name, role, terrs in USERS:
        rows.append(
            f"  ('{det_uuid(label)}', {q(label)}, {q(name)}, {q(role)}, "
            f"{_json(terrs)}::jsonb)"
        )
    # The dev/demo auth-bypass principal (deps.py: uuid5(NAMESPACE_URL,
    # 'demo:cfo'), role CFO). Seeded as a real user so audited actions it
    # performs (override / sign-off) satisfy the audit_log actor FK. DEV/DEMO
    # only; harmless in production where the bypass is disabled.
    import uuid as _uuid

    demo_id = _uuid.uuid5(_uuid.NAMESPACE_URL, "demo:cfo")
    rows.append(
        f"  ('{demo_id}', 'demo:cfo', 'Demo CFO', 'CFO', "
        f"{_json([])}::jsonb)"
    )
    w(",\n".join(rows))
    w("ON CONFLICT (user_id) DO NOTHING;")
    w("")

    # --- initial active model version ----------------------------------------
    mv = MODEL_VERSION
    w("-- Initial ACTIVE model version; coupled weights sum to exactly 1.00 "
      "(R12.2, R26.1).")
    w("INSERT INTO model_versions (model_version_id, talent_pedigree_weight, "
      "narrative_trope_weight, guardrail_params, supersedes_id, is_active) VALUES")
    w(f"  ('{det_uuid(mv['label'])}', {mv['talent_pedigree_weight']}, "
      f"{mv['narrative_trope_weight']}, {_json(mv['guardrail_params'])}::jsonb, "
      f"NULL, TRUE)")
    w("ON CONFLICT (model_version_id) DO NOTHING;")
    w("")

    # --- exchange rates -------------------------------------------------------
    w("-- Dated USD normalization rates (R21.4).")
    w("INSERT INTO exchange_rates (exchange_rate_id, from_currency, to_currency, "
      "rate, rate_date) VALUES")
    rows = []
    for frm, to, rate, rate_date in EXCHANGE_RATES:
        label = f"rate-{frm}-{to}-{rate_date}"
        rows.append(
            f"  ('{det_uuid(label)}', {q(frm)}, {q(to)}, {rate}, DATE {q(rate_date)})"
        )
    w(",\n".join(rows))
    w("ON CONFLICT (from_currency, to_currency, rate_date) DO NOTHING;")
    w("")

    # --- market telemetry cache ----------------------------------------------
    w("-- Market telemetry per (genre_tag, territory) pair (R13.2, R13.3). These")
    w("-- drive territory-weighted CPM/LTV in the Guardrails engine (R21.3); the")
    w("-- seeded title_versions back-fill divides out these weights so the stored")
    w("-- scorecards stay identical under a live recompute.")
    w("INSERT INTO market_telemetry_cache (telemetry_id, genre_tag, territory, "
      "social_sentiment_index, chart_velocity_score, licensing_inflation_multiplier, "
      "source_available) VALUES")
    rows = []
    for genre, terr, sentiment, velocity, inflation in TELEMETRY:
        label = f"telemetry-{genre}-{terr}"
        rows.append(
            f"  ('{det_uuid(label)}', {q(genre)}, {q(terr)}, {sentiment}, "
            f"{velocity}, {inflation}, TRUE)"
        )
    w(",\n".join(rows))
    w("ON CONFLICT (genre_tag, territory) DO NOTHING;")
    w("")

    # --- titles ---------------------------------------------------------------
    w("-- Candidate titles spanning every asset_type (R17.4). deal_stage seeds")
    w("-- the acquisition pipeline across a realistic mix of lifecycle stages.")
    w("INSERT INTO titles (title_id, title_name, asset_type, "
      "acquisition_cost_or_budget, native_currency, target_territories, genre_tag, "
      "projected_viewing_hours, is_historical, deal_stage, created_by) VALUES")
    rows = []
    for t in TITLES:
        (label, name, atype, cost, cur, terrs, genre, vh, hist, *_rest) = t
        stage = DEAL_STAGE_BY_TITLE.get(label, "SCREENING")
        rows.append(
            f"  ('{det_uuid(label)}', {q(name)}, {q(atype)}, {cost}, {q(cur)}, "
            f"{_json(terrs)}::jsonb, {q(genre)}, {vh}, "
            f"{'TRUE' if hist else 'FALSE'}, {q(stage)}, '{det_uuid('user-buyer')}')"
        )
    w(",\n".join(rows))
    w("ON CONFLICT (title_id) DO NOTHING;")
    w("")

    # --- title_versions (one active per title) -------------------------------
    w("-- One active title_version per title (R24.2, R24.4).")
    w("-- source_snapshot is an encrypted-at-rest TEXT column (R28.1). The seed")
    w("-- loads plaintext JSON (readable only with CINEROI_ENCRYPTION_REQUIRED=false,")
    w("-- the local/dev passthrough); a production load would supply ciphertext.")
    w("INSERT INTO title_versions (title_version_id, title_id, version_number, "
      "source_snapshot, is_active) VALUES")
    rows = []
    rate_map = {"USD": 1.0, "INR": 0.012, "EUR": 1.09, "GBP": 1.27}
    for t in TITLES:
        (label, name, atype, cost, cur, terrs, genre, vh, hist,
         cpvh, ltv, churn, payback, rec) = t
        tv_label = f"{label}-v1"
        # Back-fill modeling inputs so a live recompute reproduces the stored
        # scorecard. The engine territory-weights CPM and LTV from the seeded
        # telemetry (R21.3): the LTV-to-cost numerator is
        #   churn_reduction_value * (ltv * ltv_weight)        [SVOD]
        # + watch_time_elasticity * (cpm * cpm_weight) * ad_impressions  [AVOD].
        # We size the UNWEIGHTED inputs to a 70/30 SVOD/AVOD split of
        # total_value = ltv_multiple * normalized_cost, then DIVIDE OUT the
        # weights so applying them lands back on the same multiple - keeping the
        # seeded scorecard identical while staying faithful under a live recompute.
        cpm_weight, ltv_weight = _title_weights(genre, terrs)
        normalized = float(cost) * rate_map[cur]
        total_value = float(ltv) * normalized
        svod_value = total_value * 0.70
        avod_value = total_value * 0.30
        # SVOD: churn_reduction_value * (ltv_per_sub * ltv_weight). Fix ltv_per_sub = 120.
        ltv_per_sub = 120.0
        churn_reduction_value = round(svod_value / (ltv_per_sub * ltv_weight), 4)
        # AVOD: watch_time_elasticity(=1) * (cpm * cpm_weight) * ad_impressions. Fix cpm = 25.
        cpm = 25.0
        ad_impressions = round(avod_value / (cpm * cpm_weight), 2)
        snapshot = {
            "title_name": name,
            "ingested": "seed",
            "version": 1,
            # Modeled valuation inputs (consistent with the seeded projection).
            "churn_reduction_value": churn_reduction_value,
            "ltv": ltv_per_sub,
            "watch_time_elasticity": 1.0,
            "cpm": cpm,
            "ad_impressions": ad_impressions,
            # No churn_reduction_pct here: the seed intentionally omits a supplied
            # churn so every seeded title resolves as CALCULATED and the engine
            # computes churn from the model (calculable-churn-model R9.1). Pedigree,
            # production scale, and exclusivity are resolved from the seeded
            # metadata_vectors / license_terms rows at recompute time.
            # Payback is milestone-based (R7.1, R22.2): the engine walks the
            # schedule month by month and returns the first month where
            # margin*month exceeds the cumulative outflow. With the full cost
            # disbursed at month 1, break-even is the first m with
            # margin*m > normalized. Setting margin = normalized/(payback-0.5)
            # makes that first month land EXACTLY on the intended payback, so a
            # live recompute reproduces the seeded payback_horizon_months (a
            # split schedule front-loads outflow and shifts break-even, which is
            # why the single milestone is used for the payback input here).
            "monthly_margin": round(normalized / (float(payback) - 0.5), 2),
            "milestone_schedule": [
                {"month": 1, "amount": f"{normalized:.2f}", "currency": "USD"},
            ],
            # OTT content format (calculable-churn-model R17): each title's aligned
            # format (zero lift), so a live recompute reads it from the snapshot
            # and the breakdown shows an explicit Content Format row.
            "content_format": _FORMAT_BY_TITLE.get(label),
        }
        rows.append(
            f"  ('{det_uuid(tv_label)}', '{det_uuid(label)}', 1, "
            f"{_json(snapshot)}, TRUE)"
        )
    w(",\n".join(rows))
    w("ON CONFLICT (title_version_id) DO NOTHING;")
    w("")

    w("-- Point each title at its active version (titles.active_version_id, R24.4).")
    for t in TITLES:
        label = t[0]
        w(
            f"UPDATE titles SET active_version_id = '{det_uuid(label + '-v1')}' "
            f"WHERE title_id = '{det_uuid(label)}';"
        )
    w("")

    # --- metadata_vectors (1536-dim narrative DNA) ---------------------------
    w("-- Metadata vectors: 1536-dim Narrative_DNA per title (R2.6, R17.6).")
    w("INSERT INTO metadata_vectors (metadata_id, title_id, title_version_id, "
      "narrative_dna, affective_primary, affective_secondary, talent_pedigree_score, "
      "production_scale_metric, model_version_id, extraction_status) VALUES")
    affect = {
        "title-aurora": ("AWE", "TENSION"),
        "title-monsoon": ("NOSTALGIA", "HOPE"),
        "title-ledger": ("TENSION", "FEAR"),
        "title-reruns": ("JOY", "NOSTALGIA"),
        "title-echoes": ("HOPE", "SADNESS"),
        "title-sl-ipl": ("AWE", "TENSION"),
        "title-sl-crorepati": ("JOY", "ANTICIPATION"),
        "title-sl-mumbainoir": ("TENSION", "FEAR"),
        "title-sl-football": ("AWE", "HOPE"),
        "title-sl-ringkings": ("TENSION", "AWE"),
        "title-sl-kaveri": ("NOSTALGIA", "HOPE"),
        "title-sl-deccan": ("FEAR", "TENSION"),
        "title-sl-paperboats": ("SADNESS", "HOPE"),
        "title-sl-spiceroute": ("AWE", "NOSTALGIA"),
        "title-sl-classics": ("JOY", "NOSTALGIA"),
    }
    scores = {
        "title-aurora": ("8.50", "9.00"),
        "title-monsoon": ("7.20", "6.50"),
        "title-ledger": ("6.00", "5.50"),
        "title-reruns": ("4.00", "3.50"),
        "title-echoes": ("7.80", "7.00"),
        "title-sl-ipl": ("7.00", "9.00"),
        "title-sl-crorepati": ("7.00", "7.00"),
        "title-sl-mumbainoir": ("8.00", "8.00"),
        "title-sl-football": ("6.00", "8.00"),
        "title-sl-ringkings": ("6.00", "7.00"),
        "title-sl-kaveri": ("6.50", "6.00"),
        "title-sl-deccan": ("6.00", "5.50"),
        "title-sl-paperboats": ("5.00", "5.00"),
        "title-sl-spiceroute": ("4.00", "4.00"),
        "title-sl-classics": ("3.00", "3.00"),
    }
    rows = []
    for t in TITLES:
        label = t[0]
        prim, sec = affect[label]
        tp, ps = scores[label]
        vec = vec_literal(unit_vector(label))
        rows.append(
            f"  ('{det_uuid(label + '-mv')}', '{det_uuid(label)}', "
            f"'{det_uuid(label + '-v1')}', {q(vec)}, {q(prim)}, {q(sec)}, {tp}, {ps}, "
            f"'{det_uuid(MODEL_VERSION['label'])}', 'SUCCESS')"
        )
    w(",\n".join(rows))
    w("ON CONFLICT (metadata_id) DO NOTHING;")
    w("")

    # --- financial_projections ------------------------------------------------
    w("-- Financial projections, stamped with the active model version "
      "(R8.6, R25.3, R26.2).")
    w("INSERT INTO financial_projections (projection_id, title_id, title_version_id, "
      "calculated_cpvh, ltv_to_cost_multiple, churn_reduction_pct, "
      "payback_horizon_months, recommendation_status, normalized_cost_usd, "
      "exchange_rate_id, model_version_id, explanation) VALUES")
    rows = []
    for t in TITLES:
        (label, name, atype, cost, cur, terrs, genre, vh, hist,
         cpvh, ltv, churn, payback, rec) = t
        # Normalized cost in USD using the seeded 2024-01-02 rate for the title's
        # native currency.
        rate_map = {"USD": 1.0, "INR": 0.012, "EUR": 1.09, "GBP": 1.27}
        normalized = f"{float(cost) * rate_map[cur]:.2f}"
        rate_label = f"rate-{cur}-USD-2024-01-02"
        # Build a full, engine-shaped explanation with a per-guardrail `checks`
        # array so the title page renders the real breakdown (and so GET
        # /valuation never returns a `checks`-less explanation the UI must guard
        # against). Thresholds and correctable classification mirror the engine:
        # CPVH ceiling 0.18 premium / 0.05 library; LTV >= 3.2; churn >= 1.5;
        # payback <= 12. CPVH/LTV/payback breaches are correctable, churn is not.
        # Churn is computed by the model from the seeded features (R9.5), not the
        # old TITLES literal. The stored column, the CHURN_MITIGATION check, and
        # the embedded churn_model breakdown all use this one value so a live
        # recompute reproduces the seeded row exactly.
        churn_result = _title_churn_result(label, atype, genre, terrs)
        model_churn = str(churn_result.churn_reduction_pct)
        explanation = _seed_explanation(
            atype, cpvh, ltv, model_churn, payback, churn_result
        )
        rows.append(
            f"  ('{det_uuid(label + '-fp')}', '{det_uuid(label)}', "
            f"'{det_uuid(label + '-v1')}', {cpvh}, {ltv}, {model_churn}, {payback}, "
            f"{q(rec)}, {normalized}, '{det_uuid(rate_label)}', "
            f"'{det_uuid(MODEL_VERSION['label'])}', {_json(explanation)}::jsonb)"
        )
    w(",\n".join(rows))
    w("ON CONFLICT (projection_id) DO NOTHING;")
    w("")

    # --- license_terms --------------------------------------------------------
    w("-- License terms per title (R22). The deal-term columns (windowing_rules,")
    w("-- holdbacks, milestone_schedule) are encrypted-at-rest TEXT (R28.1); the")
    w("-- seed loads plaintext JSON for the local/dev passthrough.")
    w("INSERT INTO license_terms (license_id, title_id, license_duration_months, "
      "is_exclusive, windowing_rules, holdbacks, milestone_schedule) VALUES")
    rows = []
    for label, duration, exclusive, windowing, milestones in LICENSE_TERMS:
        rows.append(
            f"  ('{det_uuid(label + '-lic')}', '{det_uuid(label)}', {duration}, "
            f"{'TRUE' if exclusive else 'FALSE'}, {_json(windowing)}, "
            f"NULL, {_json(milestones)})"
        )
    w(",\n".join(rows))
    w("ON CONFLICT (license_id) DO NOTHING;")
    w("")

    # --- subscriber_clusters (preference vectors) ----------------------------
    w("-- Subscriber cluster preference vectors (1536-dim) for the "
      "Vector_Search_Engine (design R3).")
    w("INSERT INTO subscriber_clusters (cluster_id, cluster_name, description, "
      "preference_vector) VALUES")
    rows = []
    for label, name, desc in CLUSTERS:
        vec = vec_literal(unit_vector(label))
        rows.append(
            f"  ('{det_uuid(label)}', {q(name)}, {q(desc)}, {q(vec)})"
        )
    w(",\n".join(rows))
    w("ON CONFLICT (cluster_id) DO NOTHING;")
    w("")

    return "\n".join(out)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Generate 02_seed_data.sql")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the on-disk SQL differs from freshly generated output.",
    )
    args = parser.parse_args(argv)

    sql = render()

    if args.check:
        if not OUTPUT.exists():
            print(f"{OUTPUT.name} is missing; run the generator.", file=sys.stderr)
            return 1
        current = OUTPUT.read_text(encoding="utf-8")
        if current != sql:
            print(f"{OUTPUT.name} is out of date; regenerate it.", file=sys.stderr)
            return 1
        print(f"{OUTPUT.name} is up to date.")
        return 0

    OUTPUT.write_text(sql, encoding="utf-8")
    print(f"Wrote {OUTPUT} ({len(sql)} bytes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
