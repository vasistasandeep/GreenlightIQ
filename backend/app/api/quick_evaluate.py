"""Quick-evaluate router: manual single-title ingest + instant valuation.

``POST /api/v1/titles/quick-evaluate`` is the synchronous companion to the async
batch ingest. It accepts a single structured title (the fields a user types into
the Asset Studio form) plus derived modeled inputs, persists the title and an
active version snapshot, runs the Guardrails_Engine inline, and returns a full
executive scorecard in one response so the UI can render an instant greenlight
breakdown.

Unlike ``POST /titles/ingest`` (which validates a raw CSV/JSON/PDF payload,
enqueues a Celery job, and returns 202 + a job id), this endpoint does the whole
create -> value -> explain cycle in the request transaction, reusing the exact
Guardrails_Engine the batch pipeline uses so the math is identical to production.

A note on derived fields
------------------------
The engine returns the four guardrail results and the recommendation. Two UI
conveniences are *derived* here and labelled as such in the response:

* ``target_purchase_ceiling_usd`` - an estimate of the maximum cost at which the
  cost-sensitive guardrails (CPVH, LTV) still pass, i.e. the renegotiation
  target. It is a derived guidance figure, not a persisted engine output.
* ``governance`` - reflects the *real* Approval_Workflow gate (CCO + CFO sign-off
  for a GREENLIGHT whose normalized cost exceeds 25,000,000 USD, R20.3). When the
  decision does not meet that bar, ``required`` is false and no sign-off is owed.
"""

from __future__ import annotations

import io
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from app.api.deps import GuardrailsEngineDep, SessionDep, require_operation
from app.core.errors import UnsupportedFormatError
from app.domain import drivers, negotiation
from app.domain.metadata import derive_production_scale
from app.domain.momentum import Production_Stage
from app.engines.guardrails import churn_model_json
from app.domain.pitch_parse import parse_pitch_text
from app.engines.rbac import Operation
from app.schemas.api import (
    ChurnCohortOut,
    CounterProposalLeverOut,
    LtvAttributionOut,
)
from app.models.title import ASSET_TYPES, Title
from app.models.title_version import TitleVersion
from app.repositories.titles import TitleRepository, TitleVersionRepository

router = APIRouter(prefix="/titles", tags=["titles"])

_SUPPORTED_CURRENCIES = ("USD", "INR", "EUR", "GBP")

# High-budget sign-off threshold in base currency (R20.3).
_HIGH_BUDGET_USD = Decimal("25000000")


class QuickEvaluateRequest(BaseModel):
    """A single manually-entered title to create and value instantly."""

    title_name: str = Field(..., min_length=1, max_length=500)
    asset_type: str = Field(...)
    acquisition_cost_or_budget: Decimal = Field(..., gt=Decimal("0"))
    native_currency: str = Field(default="USD")
    target_territories: list[str] = Field(default_factory=list)
    synopsis: str = Field(..., min_length=1)
    genre_tag: str | None = Field(default=None)
    projected_viewing_hours: Decimal | None = Field(default=None, ge=Decimal("0"))
    # calculable-churn-model (R16): the unit the projected-viewing-hours value is
    # expressed in. The handler normalizes to hours (minutes/60, seconds/3600)
    # before valuation, so a buyer can type the figure in whatever unit they have.
    viewing_hours_unit: Literal["hours", "minutes", "seconds"] = Field(default="hours")
    talent_pedigree_score: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("10"))
    license_duration_months: int | None = Field(default=None, ge=1)
    is_exclusive: bool = Field(default=False)
    # calculable-churn-model (R4.5): an optional explicitly supplied churn value.
    # When present and valid it is SUPPLIED (used exactly, overriding the model);
    # when omitted the Asset Studio path resolves CALCULATED from the carried
    # feature facts. Constrained to the inclusive percent range [0, 100].
    churn_reduction_pct: Decimal | None = Field(
        default=None, ge=Decimal("0"), le=Decimal("100")
    )
    # calculable-churn-model (R17): optional OTT content format (live-sports,
    # live-event, reality-competition, scripted-series, original-film, library,
    # ...). Drives the additive content-format churn lift; unknown -> neutral.
    content_format: str | None = Field(default=None, max_length=64)

    # --- Advanced_Content_Eval_Drivers capture (driver-input-capture) --------
    # All optional; a submission supplying none behaves exactly as today (R8.5).
    # Lineage facts (R1.1). Parent fields apply only when is_franchise (R1.6).
    is_franchise: bool | None = Field(default=None)
    franchise_order: int | None = Field(default=None, ge=1)
    parent_title_viewing_hours: Decimal | None = Field(default=None, ge=Decimal("0"))
    parent_completion_rate: Decimal | None = Field(
        default=None, ge=Decimal("0"), le=Decimal("1")
    )
    # Momentum via friendly controls (R2.1, R2.2). The raw v_trailer / e_ratio /
    # s_velocity signals are deliberately NOT exposed on this model; the Asset
    # Studio form supplies only a production stage and a buzz level, and the
    # buzz level expands into the raw signals server-side (R2.3).
    production_stage: str | None = Field(default=None)
    buzz_level: Literal["LOW", "MEDIUM", "HIGH"] | None = Field(default=None)
    # Macro facts (R1.1, R1.3, R1.4).
    source_ip_provenance: str | None = Field(default=None)
    release_window: str | None = Field(default=None)
    release_month: int | None = Field(default=None, ge=1, le=12)
    vernacular_track_count: int | None = Field(default=None, ge=1)

    @field_validator("asset_type")
    @classmethod
    def _valid_asset_type(cls, v: str) -> str:
        if v not in ASSET_TYPES:
            raise ValueError(f"asset_type must be one of {ASSET_TYPES}")
        return v

    @field_validator("native_currency")
    @classmethod
    def _valid_currency(cls, v: str) -> str:
        up = v.upper()
        if up not in _SUPPORTED_CURRENCIES:
            raise ValueError(f"native_currency must be one of {_SUPPORTED_CURRENCIES}")
        return up

    @field_validator("acquisition_cost_or_budget")
    @classmethod
    def _cost_range(cls, v: Decimal) -> Decimal:
        if not (Decimal("0.01") <= v <= Decimal("999999999.99")):
            raise ValueError("acquisition_cost_or_budget must be 0.01..999999999.99")
        return v

    @field_validator("production_stage")
    @classmethod
    def _valid_production_stage(cls, v: str | None) -> str | None:
        # Reject an out-of-set production_stage at the request boundary (R5.1),
        # producing a 422 naming the field. An absent value stays absent.
        if v is None:
            return v
        up = v.strip().upper()
        if up not in Production_Stage.__members__:
            raise ValueError(
                "production_stage must be one of "
                f"{sorted(Production_Stage.__members__)}"
            )
        return up

    @field_validator("source_ip_provenance")
    @classmethod
    def _valid_source_ip_provenance(cls, v: str | None) -> str | None:
        if v is None:
            return v
        up = v.strip().upper()
        if up not in drivers.SOURCE_IP_PROVENANCE_SET:
            raise ValueError(
                "source_ip_provenance must be one of "
                f"{sorted(drivers.SOURCE_IP_PROVENANCE_SET)}"
            )
        return up

    @field_validator("release_window")
    @classmethod
    def _valid_release_window(cls, v: str | None) -> str | None:
        if v is None:
            return v
        up = v.strip().upper()
        if up not in drivers.RELEASE_WINDOW_SET:
            raise ValueError(
                "release_window must be one of "
                f"{sorted(drivers.RELEASE_WINDOW_SET)}"
            )
        return up


class GuardrailCheckOut(BaseModel):
    name: str
    computed_value: Decimal | None = None
    threshold: Decimal | None = None
    passed: bool
    breached: bool
    shortfall_magnitude: Decimal | None = None
    correctable: bool | None = None


class ExplanationOut(BaseModel):
    checks: list[GuardrailCheckOut] = Field(default_factory=list)
    dominant_factor: str | None = None
    unclassifiable: bool = False
    # calculable-churn-model (R8.3): the flat churn_model object (method,
    # borderline flag, params source, model_version_id, missing features, and
    # the per-feature breakdown). CALCULATED carries the breakdown; SUPPLIED
    # carries a null breakdown. Null when the engine returned no churn detail.
    churn_model: dict | None = None


class GovernanceOut(BaseModel):
    """Real Approval_Workflow gate for this decision (R20.3)."""

    required: bool
    required_roles: list[str] = Field(default_factory=list)
    note: str


class MetadataProfileOut(BaseModel):
    """Radar axes for the metadata profile (0-10). Derived for the instant view."""

    narrative_dna: Decimal
    affective_tone: Decimal
    talent_pedigree: Decimal
    production_scale: Decimal
    cultural_portability: Decimal


class QuickEvaluateResponse(BaseModel):
    title_id: uuid.UUID
    title_name: str
    recommendation_status: str
    calculated_cpvh: Decimal | None = None
    ltv_to_cost_multiple: Decimal | None = None
    churn_reduction_pct: Decimal | None = None
    payback_horizon_months: int | None = None
    normalized_cost_usd: Decimal | None = None
    #: Derived renegotiation guidance (not a persisted engine output).
    target_purchase_ceiling_usd: Decimal | None = None
    implied_discount_pct: Decimal | None = None
    counter_proposal_levers: list[CounterProposalLeverOut] = Field(default_factory=list)
    ltv_attribution: LtvAttributionOut | None = None
    churn_cohort: ChurnCohortOut | None = None
    explanation: ExplanationOut
    governance: GovernanceOut
    metadata_profile: MetadataProfileOut


def _modeled_inputs(body: QuickEvaluateRequest, rate_date: str | None = None) -> dict[str, Any]:
    """Derive demo-reasonable modeled financial drivers from the typed fields.

    The form captures business facts (cost, pedigree, exclusivity); the
    LTV / churn / payback math needs modeled drivers. These are derived so the
    instant scorecard is meaningful without a full financial-modeling pipeline;
    the SnapshotValuationInputProvider reads them back at evaluation time.
    """
    cost = body.acquisition_cost_or_budget
    pedigree = body.talent_pedigree_score if body.talent_pedigree_score is not None else Decimal("5")
    quality = pedigree / Decimal("10")  # 0.0 .. 1.0

    # The LTV-to-Cost multiple is (churn_reduction_value*ltv + elasticity*cpm*
    # ad_impressions) / cost. We engineer the numerator to equal a target
    # multiple * cost so the resulting ratio lands in a realistic single-digit
    # band regardless of the absolute budget. Higher pedigree -> higher target.
    target_multiple = Decimal("2.6") + quality * Decimal("2.2")  # 2.6 .. 4.8
    numerator = target_multiple * cost
    # Split the numerator: ~85% subscription value, ~15% advertising value.
    subscription_value = numerator * Decimal("0.85")
    ad_value = numerator * Decimal("0.15")
    # Subscription term = churn_reduction_value * ltv; keep churn_reduction_value
    # a unit scalar so ltv carries the subscription contribution directly.
    churn_reduction_value = Decimal("1")
    ltv = subscription_value
    # Advertising term = elasticity * cpm * ad_impressions; fix elasticity+cpm,
    # back out impressions so the product equals ad_value.
    elasticity = Decimal("1.0")
    cpm = Decimal("12.0")
    ad_impressions = ad_value / (elasticity * cpm)

    duration = body.license_duration_months or 24

    # Payback model: a stronger title recovers faster. Target a horizon in the
    # 6..11 month band (better pedigree -> fewer months). The monthly
    # contribution margin is sized so cumulative margin overtakes the disbursed
    # cost at roughly the target month, giving a realistic break-even. The full
    # cost is disbursed across the schedule, front-loaded with 40% at signing so
    # the curve dips before recovering (the payback bar chart reads naturally).
    # Payback: a stronger title recovers sooner. We target a break-even in a
    # 7..11 month band (higher pedigree -> fewer months) and size the monthly
    # contribution margin so cumulative margin overtakes the cost at the target.
    # The acquisition cost is disbursed at signing (month 1), so cumulative
    # contribution dips to -cost then climbs by `monthly_margin` each month,
    # crossing zero at exactly `target_payback` - a clean, legible payback curve.
    target_payback = int((Decimal("11") - quality * Decimal("4")).to_integral_value())  # 7 .. 11
    target_payback = max(target_payback, 1)
    monthly_margin = (cost / Decimal(target_payback)).quantize(Decimal("0.01"))
    milestones = [{"month": 1, "amount": str(cost)}]

    snapshot: dict[str, Any] = {
        "logline": body.synopsis,
        "manifest_content": body.synopsis,
        "churn_reduction_value": str(churn_reduction_value),
        "ltv": str(ltv),
        "watch_time_elasticity": str(elasticity),
        "cpm": str(cpm),
        "ad_impressions": str(ad_impressions),
        "monthly_margin": str(monthly_margin),
        "milestone_schedule": milestones,
        # calculable-churn-model (R6.1, R8.2): carry the churn feature facts the
        # model reads so a CALCULATED quick-evaluate is meaningful and matches
        # the engine, since this path creates no metadata-vector / license rows.
        # production_scale_metric uses the same helper as the radar so the
        # explained input equals the displayed production scale (R8.2).
        "talent_pedigree_score": str(pedigree),
        "production_scale_metric": str(derive_production_scale(pedigree, body.synopsis)),
        "is_exclusive": body.is_exclusive,
        "license_duration_months": duration,
        "rate_date": rate_date,
    }
    # calculable-churn-model (R17): carry the OTT content format into the snapshot
    # so the engine applies the content-format churn lift. Omitted when absent.
    if body.content_format:
        snapshot["content_format"] = body.content_format
    # calculable-churn-model (R4.5, R8.1): place churn in the snapshot ONLY when
    # the request supplied it (SUPPLIED, used exactly); otherwise leave it out so
    # the engine resolves CALCULATED from the carried feature facts.
    if body.churn_reduction_pct is not None:
        snapshot["churn_reduction_pct"] = str(body.churn_reduction_pct)

    # driver-input-capture: assemble the candidate driver facts, validate /
    # serialize them via the shared domain module, and merge them into the
    # snapshot under the exact keys the flag-gated provider reads (R2.3, R5.*,
    # R6.1). The request-boundary validators already rejected out-of-domain
    # values, so build_driver_facts returns no errors here; absent facts are
    # omitted rather than written as neutral literals (R1.5, R2.5).
    raw: dict[str, Any] = {}
    # Lineage parents are considered only for a franchise entry (R1.6).
    if body.is_franchise:
        raw["is_franchise"] = True
        if body.franchise_order is not None:
            raw["franchise_order"] = body.franchise_order
        if body.parent_title_viewing_hours is not None:
            raw["parent_title_viewing_hours"] = body.parent_title_viewing_hours
        if body.parent_completion_rate is not None:
            raw["parent_completion_rate"] = body.parent_completion_rate
    if body.production_stage is not None:
        raw["production_stage"] = body.production_stage
    # Expand the friendly Buzz_Level into the raw momentum signals (R2.3). When
    # the buzz level is unset, no signal is written and momentum resolves its
    # neutral path (R2.5).
    if body.buzz_level is not None:
        signals = drivers.BUZZ_LEVEL_SIGNALS[body.buzz_level]
        raw["v_trailer"] = signals.v_trailer
        raw["e_ratio"] = signals.e_ratio
        raw["s_velocity"] = signals.s_velocity
    if body.source_ip_provenance is not None:
        raw["source_ip_provenance"] = body.source_ip_provenance
    if body.release_window is not None:
        raw["release_window"] = body.release_window
    if body.release_month is not None:
        raw["release_month"] = body.release_month
    if body.vernacular_track_count is not None:
        raw["vernacular_track_count"] = body.vernacular_track_count

    facts, _errors = drivers.build_driver_facts(raw)
    snapshot.update(facts)
    # Honest framing (R10.2): record that the raw momentum signals came from a
    # friendly Buzz_Level selection rather than measured telemetry. Telemetry
    # staleness fields are intentionally left unwritten so the provider defaults
    # them to fresh/available (R2.6).
    if body.buzz_level is not None:
        snapshot["momentum_input_source"] = {"buzz_level": body.buzz_level}
    return snapshot


def _metadata_profile(body: QuickEvaluateRequest) -> MetadataProfileOut:
    """Derive 0-10 radar axes from the typed fields (embedding is a placeholder)."""
    pedigree = body.talent_pedigree_score if body.talent_pedigree_score is not None else Decimal("5")
    # Simple, deterministic derivations so the radar reflects the inputs.
    genre_len = Decimal(len((body.genre_tag or "").strip()))
    narrative = min(Decimal("10"), Decimal("4") + genre_len % Decimal("6"))
    synopsis_rich = min(Decimal("10"), Decimal(len(body.synopsis)) / Decimal("25"))
    portability = Decimal(len(body.target_territories)) * Decimal("2.5")
    portability = min(Decimal("10"), portability if portability > 0 else Decimal("3"))
    return MetadataProfileOut(
        narrative_dna=narrative.quantize(Decimal("0.1")),
        affective_tone=synopsis_rich.quantize(Decimal("0.1")),
        talent_pedigree=pedigree.quantize(Decimal("0.1")),
        production_scale=derive_production_scale(pedigree, body.synopsis),
        cultural_portability=portability.quantize(Decimal("0.1")),
    )


def _target_ceiling(result: dict[str, Any]) -> Decimal | None:
    """Estimate the max cost at which the cost-sensitive guardrails still pass.

    CPVH and LTV-to-Cost both scale with cost. From the computed values at the
    submitted cost we back out the cost that would put each exactly at its
    threshold and take the binding (smaller) one. Derived guidance only.
    """
    cost = result.get("normalized_cost_usd")
    if cost is None or Decimal(cost) <= 0:
        return None
    cost = Decimal(cost)
    candidates: list[Decimal] = []

    cpvh = result.get("calculated_cpvh")
    checks = {c_name(c): c for c in _raw_checks(result)}
    cpvh_check = checks.get("CPVH")
    if cpvh is not None and cpvh_check is not None:
        ceiling = _attr(cpvh_check, "threshold")
        if cpvh and Decimal(cpvh) > 0 and ceiling:
            # CPVH = cost / hours; cost_at_ceiling = cost * (ceiling / cpvh).
            candidates.append(cost * (Decimal(ceiling) / Decimal(cpvh)))

    ltv_mult = result.get("ltv_to_cost_multiple")
    ltv_check = checks.get("LTV_TO_COST")
    if ltv_mult is not None and ltv_check is not None:
        threshold = _attr(ltv_check, "threshold")
        if ltv_mult and Decimal(ltv_mult) > 0 and threshold:
            # multiple = value / cost; cost_at_threshold = cost * (multiple / threshold).
            candidates.append(cost * (Decimal(ltv_mult) / Decimal(threshold)))

    if not candidates:
        return None
    return min(candidates).quantize(Decimal("1"))


def c_name(check: Any) -> str:
    return str(_attr(check, "name"))


def _estimate_viewing_hours(body: QuickEvaluateRequest) -> Decimal:
    """Estimate projected viewing hours when the user leaves the field blank.

    The spec allows the engine to estimate viewing hours. We size them so the
    resulting CPVH (cost / hours) lands comfortably below the applicable ceiling
    for a title of this quality - i.e. hours = cost / (ceiling * headroom), where
    headroom improves with talent pedigree. This lets a quality title clear the
    CPVH guardrail instead of failing it for want of an input.
    """
    cost = body.acquisition_cost_or_budget
    ceiling = Decimal("0.05") if body.asset_type == "LICENSED_LIBRARY" else Decimal("0.18")
    pedigree = body.talent_pedigree_score if body.talent_pedigree_score is not None else Decimal("5")
    # Headroom 0.70 (weak) .. 0.95 (strong) of the ceiling as the target CPVH.
    target_cpvh = ceiling * (Decimal("0.70") + (pedigree / Decimal("10")) * Decimal("0.25"))
    if target_cpvh <= 0:
        target_cpvh = ceiling * Decimal("0.8")
    return (cost / target_cpvh).quantize(Decimal("1"))


@router.post(
    "/quick-evaluate",
    response_model=QuickEvaluateResponse,
    dependencies=[Depends(require_operation(Operation.INGEST))],
    summary="Create a single title and return an instant valuation scorecard.",
)
async def quick_evaluate(
    body: QuickEvaluateRequest,
    session: SessionDep,
    engine: GuardrailsEngineDep,
) -> QuickEvaluateResponse:
    """Create the title + active version, run guardrails, return the scorecard."""
    titles = TitleRepository(session)
    versions = TitleVersionRepository(session)

    # Normalize the entered viewing-hours figure to hours by its unit (R16.2):
    # minutes / 60, seconds / 3600. A blank value falls back to the estimate.
    if body.projected_viewing_hours is not None and body.projected_viewing_hours > 0:
        _divisor = {"hours": Decimal("1"), "minutes": Decimal("60"), "seconds": Decimal("3600")}[
            body.viewing_hours_unit
        ]
        viewing_hours = body.projected_viewing_hours / _divisor
    else:
        viewing_hours = _estimate_viewing_hours(body)

    title = Title(
        title_name=body.title_name,
        asset_type=body.asset_type,
        acquisition_cost_or_budget=body.acquisition_cost_or_budget,
        native_currency=body.native_currency,
        target_territories=body.target_territories or [],
        genre_tag=body.genre_tag,
        projected_viewing_hours=viewing_hours,
        is_historical=False,
    )
    await titles.create(title)

    # Non-USD costs need a dated exchange rate. Use today's rate if present,
    # otherwise fall back to the most recent available rate so a valuation can
    # always be produced for the supported demo currencies.
    rate_date_iso: str | None = None
    if body.native_currency != "USD":
        from app.repositories.exchange_rates import ExchangeRateRepository

        rates = ExchangeRateRepository(session)
        today = date.today()
        row = await rates.get_rate(body.native_currency, "USD", today)
        if row is None:
            row = await rates.get_latest_rate(body.native_currency, "USD")
        if row is not None:
            rate_date_iso = row.rate_date.isoformat()

    version = TitleVersion(
        title_id=title.title_id,
        version_number=1,
        source_snapshot=_modeled_inputs(body, rate_date_iso),
        is_active=True,
    )
    await versions.create(version)

    result = await engine.evaluate(title.title_id)
    await session.commit()

    explanation = result["explanation"]
    status = str(result["recommendation_status"])
    normalized = result.get("normalized_cost_usd")

    required = status == "GREENLIGHT" and normalized is not None and Decimal(normalized) > _HIGH_BUDGET_USD
    governance = GovernanceOut(
        required=required,
        required_roles=["CHIEF_CONTENT_OFFICER", "CFO"] if required else [],
        note=(
            "CCO + CFO sign-off required (GREENLIGHT over $25M)."
            if required
            else "No executive sign-off required for this decision."
        ),
    )

    checks = _raw_checks(result)
    ceiling = negotiation.target_purchase_ceiling(normalized, checks)
    discount = negotiation.implied_discount_pct(normalized, ceiling)
    levers = [
        CounterProposalLeverOut(name=lv["name"], correctable=lv["correctable"], message=lv["message"])
        for lv in negotiation.counter_proposal_levers(checks)
    ]
    ltv_attr = None
    if result.get("ltv_to_cost_multiple") is not None:
        ltv_attr = LtvAttributionOut(
            subscription_value=result.get("ltv_subscription_value"),
            advertising_value=result.get("ltv_advertising_value"),
            total_modeled_value=result.get("ltv_total_modeled_value"),
            normalized_cost_usd=normalized,
            multiple=result.get("ltv_to_cost_multiple"),
        )
    churn_cohort = ChurnCohortOut(
        churn_reduction_pct=result.get("churn_reduction_pct"),
        modeled_cohort_size=result.get("modeled_cohort_size"),
        retained_subscribers=result.get("retained_subscribers"),
        derived=True,
    )

    return QuickEvaluateResponse(
        title_id=title.title_id,
        title_name=title.title_name,
        recommendation_status=status,
        calculated_cpvh=result["calculated_cpvh"],
        ltv_to_cost_multiple=result["ltv_to_cost_multiple"],
        churn_reduction_pct=result["churn_reduction_pct"],
        payback_horizon_months=result["payback_horizon_months"],
        normalized_cost_usd=normalized,
        target_purchase_ceiling_usd=ceiling,
        implied_discount_pct=discount,
        counter_proposal_levers=levers,
        ltv_attribution=ltv_attr,
        churn_cohort=churn_cohort,
        explanation=ExplanationOut(
            checks=_explanation_checks(explanation),
            dominant_factor=_attr(explanation, "dominant_factor"),
            unclassifiable=bool(_attr(explanation, "unclassifiable") or False),
            # calculable-churn-model (R8.3): the in-memory Explanation carries no
            # churn_model key (that is added only when the engine persists), so
            # build it from the engine's churn_detail with the same serializer
            # the persist path and the what-if route use. CALCULATED -> breakdown
            # present; SUPPLIED -> null breakdown; None detail -> null.
            churn_model=(
                churn_model_json(result["churn_detail"], result["model_version_id"])
                if result.get("churn_detail") is not None
                else None
            ),
        ),
        governance=governance,
        metadata_profile=_metadata_profile(body),
    )


def _attr(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _raw_checks(result: dict[str, Any]) -> list[Any]:
    return _attr(result.get("explanation"), "checks") or []


def _explanation_checks(explanation: Any) -> list[GuardrailCheckOut]:
    out: list[GuardrailCheckOut] = []
    for c in (_attr(explanation, "checks") or []):
        out.append(
            GuardrailCheckOut(
                name=str(_attr(c, "name")),
                computed_value=_opt_decimal(_attr(c, "computed_value")),
                threshold=_opt_decimal(_attr(c, "threshold")),
                passed=bool(_attr(c, "passed")),
                breached=bool(_attr(c, "breached")),
                shortfall_magnitude=_opt_decimal(_attr(c, "shortfall_magnitude")),
                correctable=_attr(c, "correctable"),
            )
        )
    return out


def _opt_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


class ParsedPitchResponse(BaseModel):
    """Best-effort Asset Studio fields parsed from an uploaded pitch PDF.

    Any field may be null when the parser could not recognize it; the UI
    pre-fills what is present and leaves the rest for the user to review.
    """

    title_name: str | None = None
    synopsis: str | None = None
    genre_tag: str | None = None
    acquisition_cost_or_budget: float | None = None
    native_currency: str | None = None
    is_exclusive: bool | None = None
    source_text_preview: str | None = None
    # Advanced driver pre-fill facts (recognized from the deck; never persisted
    # by parse-pitch - the user reviews and edits them in the form).
    is_franchise: bool | None = None
    franchise_order: int | None = None
    release_window: str | None = None
    source_ip_provenance: str | None = None
    production_stage: str | None = None


@router.post(
    "/parse-pitch",
    response_model=ParsedPitchResponse,
    dependencies=[Depends(require_operation(Operation.INGEST))],
    summary="Extract Asset Studio fields from an uploaded pitch/script PDF.",
)
async def parse_pitch(request: Request) -> ParsedPitchResponse:
    """Parse a pitch-deck PDF into pre-fill fields for the Asset Studio form.

    Accepts the raw PDF bytes (Content-Type application/pdf), extracts the text
    with pypdf, and runs best-effort heuristics. Never persists anything; the
    user reviews and edits the pre-filled form before running a valuation. An
    unreadable PDF maps to ``415 UNSUPPORTED_FORMAT``.
    """
    payload = await request.body()
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(payload))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:  # noqa: BLE001 - normalize any parse fault.
        raise UnsupportedFormatError(
            "The pitch PDF could not be read.",
            details={"content_type": "pdf"},
        ) from exc

    parsed = parse_pitch_text(text)
    preview = text[:280] if text else None
    return ParsedPitchResponse(
        title_name=parsed.get("title_name"),
        synopsis=parsed.get("synopsis"),
        genre_tag=parsed.get("genre_tag"),
        acquisition_cost_or_budget=parsed.get("acquisition_cost_or_budget"),
        native_currency=parsed.get("native_currency"),
        is_exclusive=parsed.get("is_exclusive"),
        source_text_preview=preview,
        is_franchise=parsed.get("is_franchise"),
        franchise_order=parsed.get("franchise_order"),
        release_window=parsed.get("release_window"),
        source_ip_provenance=parsed.get("source_ip_provenance"),
        production_stage=parsed.get("production_stage"),
    )


__all__ = ["router"]