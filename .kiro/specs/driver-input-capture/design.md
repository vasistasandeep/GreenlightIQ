# Design Document

## Overview

**Driver_Input_Capture** closes the single gap identified in the requirements: the four Advanced_Content_Eval_Drivers read their modeling facts from a title's active `title_versions.source_snapshot`, but no entry path ever *writes* those facts, so enabling the driver flags moves no verdict. This design adds the write side across the three ingest paths (Asset Studio quick-evaluate, batch CSV/JSON, pitch-PDF pre-fill), validates every supplied fact against documented bounds, persists each into the exact snapshot keys the provider already reads, and turns the four driver flags on in the demo configuration — all with **no change to the provider or engine** (`backend/app/api/deps.py`).

The feature is purely additive. Every driver fact is optional on every path (R8.5); a title/row/pitch that supplies none behaves exactly as today (R8.1–R8.4). Comps (Driver A) remain out of scope for user entry (R9).

### Design grounding (verified against the worktree `feat/advanced-content-eval-drivers`)

The integration seam and the exact behaviors this design depends on were read from the target branch at `c:\Projects\GreenlightIQ\.worktrees\advanced-content-eval-drivers`:

- **Provider seam.** `AdvancedDriversValuationInputProvider.get_inputs` (deps.py) short-circuits byte-identical when all four flags are false. With a flag on, it reads `active.source_snapshot` and calls `_resolve_comps` / `_resolve_lineage` / `_resolve_momentum` / `_resolve_macro_modifiers`, which consume the twelve driver keys directly off the snapshot. Writing those keys is the whole seam (R6.1, R6.2).
- **Comps is snapshot-sourced and inert for seeds — verified.** `_resolve_comps(snapshot, advanced)` sources the comp set from `snapshot.get("comps")` (a pre-resolved sub-object with `viewing_hours` / `churn_pct` / `title_ids` lists), **not** from live pgvector retrieval. The pgvector `MetadataVectorRepository.rank_comps_within_band` exists but is a separate, un-wired seam used only by `valuation.py`'s `_resolve_comps_anchor`. When the snapshot carries no `comps` key, `calculate_comps([], [], ...)` returns `use_intercept_fallback=True` and `h_comps is None`, so the resolver surfaces **no** `base_hours_override` / `base_churn_override` — a true no-op (R9.2). This is the mechanism behind the seed invariant below.
- **Read path coerces decimals from strings — verified.** `_resolve_lineage` uses `linmod.coerce_decimal`, `_resolve_momentum` uses `mommod.coerce_decimal` / `mommod.coerce_stage`, `_resolve_macro_modifiers` uses `macmod.coerce_decimal`; each accepts a string and returns a finite `Decimal` or `None`. The content-eval/snapshot financial reads use `Decimal(str(val))`. This confirms the stringify-on-write contract (R5.7).
- **Momentum math — verified.** `calculate_momentum` (momentum.py) with `DEFAULT_MOMENTUM_PARAMS` (`w_v=0.15, w_e=0.20, w_s=0.25, baseline_v=1.0, cap_v=2.00, cap_e=1.00, momentum_multiplier_max=1.50`, `S_VELOCITY_MIN=0.50`, `S_VELOCITY_MAX=2.00`) computes `raw = 1 + w_v*clamp(v/baseline_v,0,cap_v) + w_e*clamp(e,0,cap_e) + w_s*(clamp(s,0.50,2.00) - 1)` then `multiplier = clamp(raw, 1.00, 1.50)`. `CONCEPT_SCRIPT` / `IN_PRODUCTION` are stage-gated to a flat 1.00 (`STAGE_EXCLUDED`).
- **Seed — verified.** `database/seed/generate_seed_sql.py` writes the five titles' `source_snapshot` with only financial modeling keys and **no** `comps` key and **none** of the twelve driver keys; the `titles` columns are backfilled with neutral defaults (`is_franchise=false`, `franchise_order=1`, parents NULL, `CONCEPT_SCRIPT`, `ORIGINAL_SCREENPLAY`, `DIRECT_TO_STREAMING`, NULL month, `vernacular_track_count=1`). The provider reads the snapshot, not the columns, for driver resolution.
- **Existing write conventions — verified.** Asset Studio `_modeled_inputs` (quick_evaluate.py) already stringifies decimals (`"ltv": str(ltv)`, `"churn_reduction_pct": str(...)`) and writes native bools/ints. Batch `_snapshot` (ingestion.py) copies every raw record field, stringifying `Decimal`/`UUID`. Pitch `parse_pitch_text` (pitch_parse.py) returns only recognized fields and never persists.

## Architecture

The write side is three independent capture adapters feeding one shared persistence contract and one shared validation module. The read side is untouched.

```mermaid
flowchart TD
    subgraph Capture Paths (write side — this feature)
        AS[Asset Studio form<br/>frontend/app/studio] -->|QuickEvaluateRequest| QE[quick_evaluate.py<br/>_modeled_inputs + driver mapping]
        PP[Pitch PDF] -->|parse-pitch| PPX[pitch_parse.py<br/>recognition heuristics]
        PPX -.pre-fill, never persists.-> AS
        BATCH[CSV / JSON manifest] -->|ingest| ING[ingestion.py<br/>_validate + _snapshot]
    end

    DV[drivers.py NEW<br/>shared validation + BUZZ_LEVEL_SIGNALS<br/>+ build_driver_facts]
    QE --> DV
    ING --> DV

    QE -->|source_snapshot| TV[(title_versions.source_snapshot<br/>JSONB — stringified decimals)]
    ING -->|source_snapshot| TV

    subgraph Read side (UNCHANGED)
        TV --> PROV[AdvancedDriversValuationInputProvider<br/>deps.py — flag-gated resolvers]
        PROV --> ENG[Guardrails_Engine]
        ENG --> EXP[explanation.driver_explanations.advanced_drivers]
    end

    CFG[docker-compose x-backend-env<br/>four CINEROI_ENABLE_* = true] -.enables.-> PROV
```

Design decisions and rationale:

- **One shared domain module `backend/app/domain/drivers.py`.** Validation bounds (R5) and the Buzz_Level mapping (R2.3) must be identical for the Asset Studio and batch paths. Centralizing them in a pure, dependency-free module keeps the two callers thin and lets the rules be property-tested once. The module mirrors the existing `momentum.py` / `lineage.py` / `macro_modifiers.py` style (frozen constants, `coerce_*` helpers, never raises on coercion).
- **Snapshot is the only write target.** No new tables, no provider change. This honors R6.2 literally and keeps the blast radius to the write paths.
- **Comps is never captured.** No field, column, parameter, or parse mapping references comps (R9.1). The `comps` snapshot key is reserved for the pre-resolved comp sub-object the live seam will one day populate; this feature never writes it (R9.3).

## Components and Interfaces

### Component A — Shared driver module (`backend/app/domain/drivers.py`, NEW)

Pure module. No I/O. Holds the canonical sets, the Buzz_Level mapping, the validation, and the fact-dict builder used by both the Asset Studio and batch paths.

```python
# Canonical domains (mirror the provider's expectations; reuse momentum's enum).
from app.domain.momentum import Production_Stage  # CONCEPT_SCRIPT / IN_PRODUCTION / FESTIVAL_PREVIEW / ACQUISITION_READY

SOURCE_IP_PROVENANCE_SET = frozenset({
    "ORIGINAL_SCREENPLAY", "BESTSELLER_BOOK", "TRUE_CRIME_IP", "WEBTOON_MANGA", "PUBLIC_DOMAIN",
})
RELEASE_WINDOW_SET = frozenset({
    "DIRECT_TO_STREAMING", "DAY_AND_DATE", "THEATRICAL_30D", "THEATRICAL_60D_PLUS",
})

BuzzLevel = Literal["LOW", "MEDIUM", "HIGH"]

@dataclass(frozen=True)
class BuzzSignals:
    v_trailer: Decimal
    e_ratio: Decimal
    s_velocity: Decimal

# The single documented mapping constant the Asset Studio path uses (R2.3).
# See "Buzz_Level mapping constant" below for the verified arithmetic.
BUZZ_LEVEL_SIGNALS: dict[str, BuzzSignals] = {
    "LOW":    BuzzSignals(Decimal("0.50"), Decimal("0.02"), Decimal("0.50")),
    "MEDIUM": BuzzSignals(Decimal("1.00"), Decimal("0.05"), Decimal("1.10")),
    "HIGH":   BuzzSignals(Decimal("2.00"), Decimal("0.10"), Decimal("1.50")),
}

@dataclass
class FieldError:
    field: str
    reason: str

# Validate + coerce a loose mapping of candidate driver facts into the
# snapshot-ready, stringified-decimal dict. Returns (facts, errors).
def build_driver_facts(raw: Mapping[str, Any]) -> tuple[dict[str, Any], list[FieldError]]: ...
```

`build_driver_facts` is the heart of the feature. For each of the twelve keys it (1) skips the key entirely when the input is absent/blank (R1.5, R2.5, R3.4 — absent, not a neutral literal), (2) validates against the bound, appending a `FieldError` on violation, and (3) on success emits the value in the provider-expected JSON type. Serialization types (R5.7, see Persistence Contract):

| Snapshot key | Input | Validation (R5) | Serialized JSON type |
|---|---|---|---|
| `is_franchise` | bool | — | native bool |
| `franchise_order` | int | integer ≥ 1 (R5.2) | native int |
| `parent_title_viewing_hours` | decimal | finite, ≥ 0 (R5.6) | **string** `"6000.00"` |
| `parent_completion_rate` | decimal | finite, in [0,1] (R5.3) | **string** `"0.80"` |
| `production_stage` | enum | ∈ Production_Stage (R5.1) | native string |
| `v_trailer` | decimal | finite, ≥ 0 (R5.6) | **string** |
| `e_ratio` | decimal | finite, ≥ 0 (R5.6) | **string** |
| `s_velocity` | decimal | finite, ≥ 0 (R5.6) | **string** |
| `source_ip_provenance` | enum | ∈ Source_IP_Provenance_Set (R5.1) | native string |
| `release_window` | enum | ∈ Release_Window_Set (R5.1) | native string |
| `release_month` | int \| null | in 1..12, or absent→valid null (R5.5) | native int (omitted when null) |
| `vernacular_track_count` | int | integer ≥ 1 (R5.4) | native int |

Lineage parent fields are only required/considered when `is_franchise` is true; `is_franchise=false` or unset omits them without error (R1.6).

### Component B — Asset Studio path (`backend/app/api/quick_evaluate.py`)

**Request model extension.** `QuickEvaluateRequest` gains optional driver fields plus the friendly Buzz_Level and production-stage controls. Raw momentum numbers are **not** on this model (R2.2 — the form never exposes them):

```python
class QuickEvaluateRequest(BaseModel):
    # ... existing fields ...
    # Lineage (R1.1)
    is_franchise: bool | None = None
    franchise_order: int | None = Field(default=None, ge=1)
    parent_title_viewing_hours: Decimal | None = Field(default=None, ge=Decimal("0"))
    parent_completion_rate: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    # Momentum via friendly controls (R2.1, R2.2)
    production_stage: str | None = None          # validated against Production_Stage
    buzz_level: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    # Macro (R1.1)
    source_ip_provenance: str | None = None      # validated against the set
    release_window: str | None = None            # validated against the set
    release_month: int | None = Field(default=None, ge=1, le=12)
    vernacular_track_count: int | None = Field(default=None, ge=1)
```

Pydantic `field_validator`s reject enum values outside their sets and non-integer/out-of-range numerics at the request boundary (R5.1–R5.5), producing a 422 with the offending field — this is where Asset Studio validation lives (mirrors the existing `_valid_asset_type` / `_valid_currency` validators).

**`_modeled_inputs` extension.** After building the existing financial keys, the handler maps the driver controls and merges them into the returned snapshot dict:

```python
def _modeled_inputs(body, rate_date=None) -> dict[str, Any]:
    snapshot = { ...existing... }
    raw: dict[str, Any] = {}
    if body.is_franchise:                       raw["is_franchise"] = True
    if body.is_franchise and body.franchise_order is not None:
        raw["franchise_order"] = body.franchise_order
    if body.is_franchise and body.parent_title_viewing_hours is not None:
        raw["parent_title_viewing_hours"] = body.parent_title_viewing_hours
    if body.is_franchise and body.parent_completion_rate is not None:
        raw["parent_completion_rate"] = body.parent_completion_rate
    if body.production_stage is not None:       raw["production_stage"] = body.production_stage
    if body.buzz_level is not None:             # R2.3: expand to raw signals
        sig = drivers.BUZZ_LEVEL_SIGNALS[body.buzz_level]
        raw["v_trailer"] = sig.v_trailer
        raw["e_ratio"] = sig.e_ratio
        raw["s_velocity"] = sig.s_velocity
    if body.source_ip_provenance is not None:   raw["source_ip_provenance"] = body.source_ip_provenance
    if body.release_window is not None:         raw["release_window"] = body.release_window
    if body.release_month is not None:          raw["release_month"] = body.release_month
    if body.vernacular_track_count is not None: raw["vernacular_track_count"] = body.vernacular_track_count

    facts, _errors = drivers.build_driver_facts(raw)  # errors already impossible post-validator
    snapshot.update(facts)                            # stringified decimals, native bool/int
    # Buzz provenance marker for honest framing (R10.2).
    if body.buzz_level is not None:
        snapshot["momentum_input_source"] = {"buzz_level": body.buzz_level}
    return snapshot
```

Because the form never exposes telemetry staleness, `telemetry_last_updated_at` / `telemetry_source_available` are **not** written; the provider's `_resolve_momentum` then defaults `source_available=True` and `last_updated_at=None` (fresh/available), satisfying R2.6. When `buzz_level` is unset, no `v_trailer`/`e_ratio`/`s_velocity` are written and momentum resolves its neutral path (R2.5).

**Frontend form controls (`frontend/app/studio/_components/asset-form.tsx`).** New optional controls grouped under an "Advanced drivers (optional)" section:

- `is_franchise` toggle; when on, reveals `franchise_order` (number, min 1), `parent_title_viewing_hours`, `parent_completion_rate` (R1.6 — hidden/not required when off).
- `production_stage` select bound to the four Production_Stage members (R2.1).
- `buzz_level` select {LOW, MEDIUM, HIGH} — no raw numeric inputs (R2.2).
- `source_ip_provenance` select bound to Source_IP_Provenance_Set (R1.3); `release_window` select bound to Release_Window_Set (R1.4); `release_month` (1..12, optional); `vernacular_track_count` (min 1).

**Stage-gating UX (R2 clarification #4).** The Buzz_Level control is **stage-aware**. When `production_stage` is `CONCEPT_SCRIPT` or `IN_PRODUCTION` (the `EXCLUDED_STAGES` in `momentum.py`), the Buzz_Level select is **disabled** and annotated with helper text: *"Inactive in early stage (STAGE_EXCLUDED) — buzz does not affect an unproduced title's verdict."* This mirrors the backend exactly: `calculate_momentum` forces the multiplier to a flat `1.00` with `reason="STAGE_EXCLUDED"` for those stages, so HIGH buzz would be silently ignored. Disabling the control makes that behavior legible rather than surprising. The user may still submit buzz for `FESTIVAL_PREVIEW` / `ACQUISITION_READY`, where it is active. (The backend remains authoritative — the UX gate is a usability mirror, not the enforcement point.)

### Component C — Batch path (`backend/app/engines/ingestion.py`)

**Columns/fields.** The batch path accepts an optional CSV column or JSON field for each of the twelve driver keys by its exact snapshot name (R3.1), including the raw momentum signals directly (Raw_Signal_Mode — R3.3; batch is the power-user path and bypasses Buzz_Level).

**Validation lives in `_validate`.** The existing `_validate(record)` is extended to run `drivers.build_driver_facts(record.raw)` over the twelve candidate keys; the **first** driver-fact `FieldError` becomes a `RejectionDetail{row_index, field, reason}` and the record is rejected (R3.5). Existing title_name/cost/asset_type checks run first (unchanged order). Rejecting one record does not stop the loop — the existing per-row loop already continues and preserves the conservation invariant `accepted + rejected == total` (R3.5).

**Persistence in `_snapshot`.** `_snapshot(record)` currently copies every raw field, stringifying `Decimal`/`UUID`. To guarantee the provider-expected types (not whatever string the CSV carried), `_snapshot` is refactored to merge the **validated** `build_driver_facts` output over the twelve driver keys (overwriting the raw copies for those keys with correctly typed, stringified-decimal values), while leaving all existing keys untouched (R6.4). A record that omits a driver key writes no key for it (R3.4). The `_validate` pass having already succeeded, `build_driver_facts` here returns no errors.

**No inference (R3.6).** `vernacular_track_count` is persisted exactly as supplied; the path never derives it from `target_territories`. The two fields are independent.

### Component D — Pitch path (`backend/app/domain/pitch_parse.py`)

`parse_pitch_text` gains recognition heuristics returning additional optional keys. Never persists (R6 / R4.6); the parsed facts flow back as `ParsedPitchResponse` pre-fill the user reviews and edits in the form.

```python
_FRANCHISE = re.compile(r"\b(?:sequel|season\s*(\d+)|part\s+(II|III|IV|2|3|4)|chapter\s+(\d+))\b", re.I)
_RELEASE_WINDOW = [
    (re.compile(r"\bday[\s-]and[\s-]date\b", re.I), "DAY_AND_DATE"),
    (re.compile(r"\b(?:60|90)[\s-]day|theatrical.*60", re.I), "THEATRICAL_60D_PLUS"),
    (re.compile(r"\b30[\s-]day theatrical|theatrical window\b", re.I), "THEATRICAL_30D"),
    (re.compile(r"\btheatrical release\b", re.I), "THEATRICAL_30D"),
    (re.compile(r"\b(?:direct[\s-]to[\s-]streaming|streaming[\s-]only)\b", re.I), "DIRECT_TO_STREAMING"),
]
_SOURCE_IP = [
    (re.compile(r"\b(?:based on the|adapted from the)?\s*bestsell", re.I), "BESTSELLER_BOOK"),
    (re.compile(r"\btrue[\s-]crime\b", re.I), "TRUE_CRIME_IP"),
    (re.compile(r"\b(?:webtoon|manga|manhwa)\b", re.I), "WEBTOON_MANGA"),
    (re.compile(r"\bpublic[\s-]domain\b", re.I), "PUBLIC_DOMAIN"),
    (re.compile(r"\boriginal screenplay\b", re.I), "ORIGINAL_SCREENPLAY"),
]
_STAGE = [
    (re.compile(r"\bacquisition[\s-]ready|screener\b", re.I), "ACQUISITION_READY"),
    (re.compile(r"\bfestival (?:preview|premiere|cut)\b", re.I), "FESTIVAL_PREVIEW"),
    (re.compile(r"\bin production|principal photography\b", re.I), "IN_PRODUCTION"),
    (re.compile(r"\bconcept|script stage|in development\b", re.I), "CONCEPT_SCRIPT"),
]
```

- Franchise cue (R4.1): sets `is_franchise=true`; when a numeric entry (`season 2`, `part III`, an explicit entry number) is captured, sets `franchise_order` to it.
- Release window (R4.2), source-IP (R4.3), production stage (R4.4): set to the matched member; first/most-specific match wins.
- Only recognized facts are included; unrecognized facts are omitted (R4.5, R8.4) — no guessing.

`ParsedPitchResponse` gains the matching optional fields so the router returns them to the form.

### Component E — Demo enablement (`docker-compose.yml`)

The `x-backend-env: &backend-env` anchor (shared by the API, worker, and db-init services) adds the four flags defaulted on for the demo, overridable via the root `.env` (R7.1):

```yaml
  CINEROI_ENABLE_COMPS: ${CINEROI_ENABLE_COMPS:-true}
  CINEROI_ENABLE_LINEAGE: ${CINEROI_ENABLE_LINEAGE:-true}
  CINEROI_ENABLE_MOMENTUM: ${CINEROI_ENABLE_MOMENTUM:-true}
  CINEROI_ENABLE_MACRO_MODIFIERS: ${CINEROI_ENABLE_MACRO_MODIFIERS:-true}
```

No code default changes: `Settings` keeps all four `False` (R7.4 — a disabled flag leaves its driver inert; and non-demo/test environments stay inert unless explicitly enabled).

## Data Models

No schema change. All facts land in the existing JSONB `title_versions.source_snapshot` under the twelve keys the provider reads (R6.1). The in-flight shapes:

- **`QuickEvaluateRequest`** (extended): the optional driver fields + `buzz_level` + `production_stage` above.
- **`BuzzSignals`** (new, frozen): the three raw momentum decimals a Buzz_Level expands to.
- **`FieldError`** (new): `{field, reason}`, converted to the batch `RejectionDetail{row_index, field, reason}`.
- **`ParsedPitchResponse`** (extended): optional `is_franchise`, `franchise_order`, `release_window`, `source_ip_provenance`, `production_stage`.
- **Snapshot fragment written** (example, franchise + buzz + macro):
  ```json
  {
    "is_franchise": true,
    "franchise_order": 2,
    "parent_title_viewing_hours": "6000.00",
    "parent_completion_rate": "0.80",
    "production_stage": "ACQUISITION_READY",
    "v_trailer": "2.00", "e_ratio": "0.10", "s_velocity": "1.50",
    "source_ip_provenance": "BESTSELLER_BOOK",
    "release_window": "THEATRICAL_30D",
    "release_month": 11,
    "vernacular_track_count": 3,
    "momentum_input_source": {"buzz_level": "HIGH"}
  }
  ```

## Buzz_Level mapping constant (verified arithmetic — clarification #1)

The single documented constant `BUZZ_LEVEL_SIGNALS` maps each level to raw `(v_trailer, e_ratio, s_velocity)`. Below is the explicit arithmetic against the **real** `DEFAULT_MOMENTUM_PARAMS` (`w_v=0.15, w_e=0.20, w_s=0.25, baseline_v=1.0, cap_v=2.00, cap_e=1.00, mm_max=1.50`, S_velocity clamp `[0.50, 2.00]`), using
`raw = 1 + 0.15·clamp(v/1.0, 0, 2.00) + 0.20·clamp(e, 0, 1.00) + 0.25·(clamp(s, 0.50, 2.00) − 1)` and `multiplier = clamp(raw, 1.00, 1.50)`, for a non-excluded stage (e.g. `ACQUISITION_READY`). These values were computed by running the mapped inputs through the actual `momentum.calculate_momentum` on the worktree.

**LOW** — mapped `v=0.50, e=0.02, s=0.50`:
- `0.15·clamp(0.50,0,2.00)=0.15·0.50=0.0750`
- `0.20·clamp(0.02,0,1.00)=0.20·0.02=0.0040`
- `0.25·(clamp(0.50,0.50,2.00)−1)=0.25·(0.50−1)=0.25·(−0.50)=−0.1250`
- `raw = 1 + 0.0750 + 0.0040 − 0.1250 = 0.9540` → `clamp(0.9540, 1.00, 1.50) = ` **1.00** (neutral target met via the floor clamp).

> Adjustment note: the reviewer's candidate LOW used `s_velocity=0.80`, which yields `raw=1.0290 → 1.0290` (above the intended neutral 1.00). To land exactly on the intended ~neutral 1.00 while keeping the reviewer's `v`/`e`, the mapped `s_velocity` is lowered to **0.50** (the clamp floor), giving `raw=0.9540` → clamped to **1.00**. This is the corrected LOW mapping in `BUZZ_LEVEL_SIGNALS`.

**MEDIUM** — mapped `v=1.00, e=0.05, s=1.10`:
- `0.15·1.00=0.1500`; `0.20·0.05=0.0100`; `0.25·(1.10−1)=0.25·0.10=0.0250`
- `raw = 1 + 0.1500 + 0.0100 + 0.0250 = 1.1850` → `clamp = ` **1.1850** (intended ~1.18 met).

**HIGH** — mapped `v=2.00 (at cap_v), e=0.10, s=1.50`:
- `0.15·clamp(2.00,0,2.00)=0.15·2.00=0.3000`; `0.20·0.10=0.0200`; `0.25·(1.50−1)=0.25·0.50=0.1250`
- `raw = 1 + 0.3000 + 0.0200 + 0.1250 = 1.4450` → `clamp = ` **1.4450** (intended 1.45–1.50 met).

Resulting mapping and multipliers (stage-active):

| Buzz_Level | v_trailer | e_ratio | s_velocity | raw | multiplier | intended |
|---|---|---|---|---|---|---|
| LOW | 0.50 | 0.02 | 0.50 | 0.9540 | **1.00** | ~1.00 ✓ |
| MEDIUM | 1.00 | 0.05 | 1.10 | 1.1850 | **1.1850** | ~1.18 ✓ |
| HIGH | 2.00 | 0.10 | 1.50 | 1.4450 | **1.4450** | 1.45–1.50 ✓ |

The mapping is monotonic non-decreasing (1.00 ≤ 1.1850 ≤ 1.4450) and every multiplier is within the `[1.00, 1.50]` band. (For an excluded stage the multiplier is forced to 1.00 regardless of level — see stage-gating.)

## Persistence contract — stringified decimals (clarification #3)

`source_snapshot` is JSONB. Python's stdlib `json.dumps` cannot serialize `Decimal`, so **all decimal driver facts are written as strings** and non-decimal facts as native JSON:

- **String:** `parent_title_viewing_hours`, `parent_completion_rate`, `v_trailer`, `e_ratio`, `s_velocity` — e.g. `"6000.00"`, `"0.80"`, `"2.00"`.
- **Native bool:** `is_franchise`.
- **Native int:** `franchise_order`, `release_month`, `vernacular_track_count`.
- **Native string (enum literal):** `production_stage`, `source_ip_provenance`, `release_window`.

This matches the existing conventions verified on the branch: Asset Studio `_modeled_inputs` already does `str(ltv)` / `str(churn_reduction_pct)`; batch `_snapshot` already stringifies `Decimal`. The new `build_driver_facts` output follows the same discipline so both paths write identical shapes.

**Read path confirmed defensive.** The provider coerces on read: `_resolve_lineage` → `linmod.coerce_decimal`, `_resolve_momentum` → `mommod.coerce_decimal` / `coerce_stage`, `_resolve_macro_modifiers` → `macmod.coerce_decimal`. Each accepts a string, returns a finite `Decimal`/enum or `None`. So `"0.80"` on write round-trips to `Decimal("0.80")` on read with no provider change (R5.7, R6.2).

## No-provider-change seam and flag-enablement + seed invariant (clarification #2, R7.5)

**Seam.** The only integration point is the twelve snapshot keys. `AdvancedDriversValuationInputProvider` already reads them; this feature only writes them. `deps.py` is not modified (R6.2).

**Why enabling all four flags leaves the five seeded titles byte-identical (R7.5, R8.2).** Verified against the worktree seed and resolvers:

1. **Comps (Driver A).** `_resolve_comps` sources its comp set from `snapshot.get("comps")` — a **pre-resolved sub-object**, not live pgvector retrieval. (`rank_comps_within_band` exists but is wired only into `valuation.py`'s separate anchor path, not into the provider's `_resolve_comps`.) The seeded snapshots carry **no `comps` key**, so `calculate_comps([], [], title_ids=None)` returns `use_intercept_fallback=True` with `h_comps is None`/`c_comps is None`. The resolver therefore surfaces **no** `base_hours_override` / `base_churn_override` — it is a no-op and does not touch base hours or churn. (The design does **not** claim comps live-retrieves and must be defended against; the real behavior is snapshot-sourced inertness.)
2. **Lineage (Driver B).** Seeded snapshots carry no `is_franchise` / `franchise_order` / parent facts. `_resolve_lineage` reads `is_franchise=False`, `franchise_order=1`, parents `None` → `calculate_lineage` resolves `is_active=False`, `franchise_floor`/`delta_c_franchise` neutral. No effect on inputs.
3. **Momentum (Driver C).** No `production_stage` in the snapshot → `coerce_stage(None)` → `CONCEPT_SCRIPT` → `STAGE_EXCLUDED` → flat `1.00`. No effect.
4. **Macro (Driver D).** No macro keys → all features `None` → `calculate_macro_modifiers` yields the neutral `product = 1.00`. No effect.

All four resolvers attach only an **explanation block** under `driver_explanations["advanced_drivers"]`; none mutates `ValuationInputs` (comps surfaces overrides only when `h_comps` is present, which requires a `comps` sub-object). Since no seeded title carries driver facts or a `comps` key, every driver is inert and the engine's inputs — hence the verdict and the numeric breakdown — are unchanged flags-on vs flags-off. The five seeded verdicts hold: Aurora Protocol / Monsoon Lanes / Echoes of 2019 GREENLIGHT; The Ledger NEGOTIATE_HARD; Vintage Reruns Vol. 7 PASS (R7.5).

A **regression guard** (Correctness Property 7 and a parameterized test over the five titles) asserts this invariant explicitly.

**Neutral titles in general (R8.1–R8.2).** The same reasoning extends to any title/row/pitch supplying no driver facts: flags-off is the provider short-circuit (byte-identical); flags-on resolves every driver to its neutral/no-op path (explanation-only, inputs unchanged).

## Honest framing in the breakdown (R10)

The supplied facts are user-entered modeling inputs, not fitted ground truth, and the breakdown must say so (R10.1, R10.3). Two surfaces:

- **Provenance marker.** When a Buzz_Level drove the raw signals, `_modeled_inputs` writes `momentum_input_source = {"buzz_level": <level>}` into the snapshot. The momentum explanation block can surface that the raw signals were derived from a friendly Buzz_Level selection rather than measured telemetry (R10.2). (This is additive snapshot provenance; the provider's momentum block already carries `source_tier`/`reason`.)
- **Labelling.** The per-driver explanation surface frames each supplied driver fact as a *user-supplied modeling input* distinct from a fitted/empirically derived value, consistent with the existing `source_tier` provenance the resolvers already emit (`DETERMINISTIC_FALLBACK` for the illustrative coefficients). The feature never presents supplied facts or the resulting driver contributions as validated real-world outcomes (R10.3).

## Error Handling

| Condition | Path | Handling | Requirement |
|---|---|---|---|
| Enum fact outside its set | Asset Studio | Pydantic `field_validator` → 422, field named | R5.1 |
| Enum fact outside its set | Batch | `build_driver_facts` → `FieldError` → `RejectionDetail`, row continues | R5.1, R3.5 |
| `franchise_order` < 1 / non-integer | both | reject; message "must be an integer ≥ 1" | R5.2 |
| `parent_completion_rate` ∉ [0,1] | both | reject; message states the [0,1] bound | R5.3 |
| `vernacular_track_count` < 1 / non-integer | both | reject; message "must be an integer ≥ 1" | R5.4 |
| `release_month` ∉ 1..12 | both | reject; message states the 1..12 bound | R5.5 |
| `release_month` absent | both | valid null — omitted from snapshot | R5.5 |
| `parent_title_viewing_hours`/`v_trailer`/`e_ratio`/`s_velocity` non-finite or negative | both | reject; message states finite-non-negative bound | R5.6 |
| Pitch PDF unreadable | Pitch | existing `UnsupportedFormatError` (415) — unchanged | R4 |
| Pitch has no recognizable driver facts | Pitch | return existing fields only; no driver keys added | R4.5, R8.4 |
| Batch record rejected | Batch | `RejectionDetail` added; loop continues; conservation holds | R3.5 |

Validation **location** per path: Asset Studio at the request boundary (Pydantic validators) so an invalid value never reaches `_modeled_inputs`; batch inside `_validate` (via `build_driver_facts`) so an invalid value never reaches `_snapshot`; pitch performs no validation (recognition-only, never persists). The shared bounds live once in `drivers.build_driver_facts`.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

PBT applies to this feature: the capture paths are pure-ish transformations (request/record → snapshot dict) and the validation/mapping are pure functions over large input spaces, with a round-trip through the real provider as the strongest check. After reflection, redundant properties were consolidated: the "present under exact key" and "serialized in the expected type" claims are folded into one write-contract property (Property 1); the per-field bound rejections (R5.1–R5.6) are one parameterized rejection property (Property 3); the absence guarantees for omitted facts, comps, and legacy manifests are one omission property (Property 4) plus a dedicated comps-absence property (Property 8) since comps has an independent never-write rule.

### Property 1: Supplied facts are persisted under exact keys in the provider-expected type

*For all* valid driver-fact subsets supplied on a capture path, every supplied fact appears in the produced `source_snapshot` under its exact snapshot key, serialized in the provider-expected JSON type (decimal facts as strings, `is_franchise` as native bool, integer facts as native int, enum facts as their literal string), and no existing snapshot key is removed or altered.

**Validates: Requirements 1.2, 2.3, 2.4, 3.2, 5.7, 6.1, 6.4**

### Property 2: Buzz_Level mapping is bounded and monotonic

*For all* Buzz_Level values {LOW, MEDIUM, HIGH}, feeding the mapped `(v_trailer, e_ratio, s_velocity)` through `calculate_momentum` at a non-excluded stage yields a multiplier within the inclusive `[1.00, 1.50]` band, and the multipliers are monotonic non-decreasing in level (LOW ≤ MEDIUM ≤ HIGH).

**Validates: Requirements 2.3**

### Property 3: Out-of-bounds facts are rejected with a per-field reason and never written

*For all* driver facts whose value violates its documented bound — enum ∉ its set; `franchise_order` < 1 or non-integer; `parent_completion_rate` ∉ [0,1]; `vernacular_track_count` < 1 or non-integer; `release_month` ∉ 1..12; `parent_title_viewing_hours`/`v_trailer`/`e_ratio`/`s_velocity` non-finite or negative — the relevant capture path rejects the value, reports the offending field and the violated bound, and writes no key for it; a valid value in the same field is persisted.

**Validates: Requirements 3.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6**

### Property 4: Omitted facts are absent, not neutral literals

*For all* capture-path inputs that omit a given driver fact (including a manifest with no driver columns at all), the produced snapshot contains no key for that omitted fact, leaving the title neutral with respect to it.

**Validates: Requirements 1.5, 2.5, 3.4, 8.3, 8.5**

### Property 5: Supplied facts round-trip through the real provider

*For all* valid driver-fact sets written to a title's active snapshot by a capture path, resolving that title through the unmodified `AdvancedDriversValuationInputProvider` (all four flags on) produces per-driver resolutions equal to the pure-domain computation over the same facts — lineage `is_active`/floor reflecting the franchise facts, the momentum multiplier equal to `calculate_momentum` over the written signals, and the macro product reflecting the written enums/ints — confirming the snapshot write is the complete integration seam.

**Validates: Requirements 6.1, 6.2, 6.3**

### Property 6: Non-neutral facts change the evaluation when flags are on

*For all* titles carrying at least one validated non-neutral driver fact (with the fact's driver flag enabled), the resolved driver block differs from the same title's neutral-defaults resolution (a non-neutral lineage floor, a momentum multiplier ≠ 1.00 at an active stage, or a macro product ≠ 1.00), so enablement is observable.

**Validates: Requirements 7.2**

### Property 7: Neutral and seeded titles are invariant under flag enablement

*For all* titles whose snapshot carries none of the twelve driver keys and no `comps` key, resolving through the provider with all four flags enabled yields inputs equal to the flags-disabled resolution — every driver resolves to its neutral/no-op path (comps surfaces no base override, lineage `is_active` false, momentum 1.00, macro product 1.00) — and in particular the five seeded demo titles retain their verdicts (Aurora Protocol / Monsoon Lanes / Echoes of 2019 GREENLIGHT; The Ledger NEGOTIATE_HARD; Vintage Reruns Vol. 7 PASS).

**Validates: Requirements 7.3, 7.5, 8.1, 8.2**

### Property 8: No comps anchor fact is ever written

*For all* Asset Studio submissions, batch records, and parsed pitches, the produced snapshot contains no `comps` key and no comps-anchor fact, so the Comps_Engine anchor remains auto-derived and user input never influences it.

**Validates: Requirements 9.1, 9.3**

## Testing Strategy

**Dual approach.** Property tests cover the universal write/validation/round-trip behavior; example and edge-case tests cover specific recognition, framing, and anti-inference behaviors; a parameterized regression pins the five seeded verdicts.

**Property-based testing.** Python target (the backend is Python/pytest), using **Hypothesis** (already present in the backend `.hypothesis` cache on the worktree). Do not hand-roll generators where Hypothesis strategies suffice. Each property test runs **≥ 100 iterations** and is tagged with a comment referencing its design property, format: `# Feature: driver-input-capture, Property {n}: {property_text}`. Each design property is implemented by a **single** property-based test:

- Property 1 — generate random valid driver-fact subsets → assert exact-key presence + JSON type + existing keys preserved (over `build_driver_facts` and `_modeled_inputs`).
- Property 2 — the three Buzz_Levels through `calculate_momentum`: bounds + monotonicity (plus an example pinning 1.00 / 1.1850 / 1.4450).
- Property 3 — generate out-of-bounds values per field → assert rejection + field + bound message, and that a valid sibling value persists.
- Property 4 — generate inputs omitting random fact subsets → assert the omitted keys are absent.
- Property 5 — generate valid fact sets, write to a snapshot, resolve through the real provider (flags on) → assert resolver outputs equal the pure-domain computation.
- Property 6 — generate non-neutral facts → assert the resolved block differs from neutral.
- Property 7 — generate neutral (driver-key-free, comps-free) snapshots → assert flags-on == flags-off resolution.
- Property 8 — generate submissions/records/pitch texts → assert no `comps` key in any produced snapshot.

**Unit / example / edge tests** (focused, not exhaustive):

- Pitch recognition table (R4.1–R4.4): representative snippets → expected recognized facts; a no-cue deck → no driver keys (R4.5, R8.4).
- Anti-inference example (R3.6): a 3-territory record with `vernacular_track_count=1` persists 1, not 3.
- Stage-gating UX example: frontend test asserting Buzz_Level is disabled/annotated for `CONCEPT_SCRIPT`/`IN_PRODUCTION`.
- Honest-framing examples (R10.1–R10.3): breakdown marks supplied facts as user-supplied modeling inputs; a buzz-sourced submission carries the `momentum_input_source` provenance marker; nothing is labelled a validated outcome.
- Seed regression (R7.5): parameterized over the five titles — verdict flags-on == verdict flags-off == seeded verdict.

**Backward-compatibility inertness** is covered by Properties 4, 7, and 8 plus the seed regression — a title/row/pitch with no driver facts produces no driver keys and resolves identically with flags on or off.
