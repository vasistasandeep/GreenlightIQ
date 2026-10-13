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
from pathlib import Path

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
        "0.2375", "2.90", "1.20", 15, "NEGOTIATE_HARD",
    ),
    (
        "title-reruns", "Vintage Reruns Vol. 7", "LICENSED_LIBRARY", "1200000.00", "EUR",
        ["DE", "FR"], "comedy", "60000000.00", False,
        "0.0200", "4.10", "0.90", 8, "NEGOTIATE_HARD",
    ),
    (
        "title-echoes", "Echoes of 2019", "ORIGINAL_SERIES", "30000000.00", "USD",
        ["US", "GB"], "drama", "180000000.00", True,
        "0.1667", "3.50", "2.00", 10, "GREENLIGHT",
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


def render() -> str:
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
            "churn_reduction_pct": float(churn),
            "monthly_margin": round(normalized / float(payback), 2),
            # Two equal milestones as STRING amounts (the engine's _to_decimal
            # rejects floats); keeps payback computable on a live recompute.
            "milestone_schedule": [
                {"month": 0, "amount": f"{normalized / 2:.2f}", "currency": "USD"},
                {"month": 6, "amount": f"{normalized / 2:.2f}", "currency": "USD"},
            ],
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
    }
    scores = {
        "title-aurora": ("8.50", "9.00"),
        "title-monsoon": ("7.20", "6.50"),
        "title-ledger": ("6.00", "5.50"),
        "title-reruns": ("4.00", "3.50"),
        "title-echoes": ("7.80", "7.00"),
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
        explanation = {
            "cpvh": {"value": cpvh, "status": "PASS" if rec != "PASS" else "BREACH"},
            "ltv_to_cost": {"value": ltv},
            "recommendation": rec,
        }
        rows.append(
            f"  ('{det_uuid(label + '-fp')}', '{det_uuid(label)}', "
            f"'{det_uuid(label + '-v1')}', {cpvh}, {ltv}, {churn}, {payback}, "
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
