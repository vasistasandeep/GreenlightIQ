"""Guardrails_Engine orchestration (Requirements 4-8, 21, 25, 30).

The Guardrails_Engine is the financial core's orchestrator. It composes the pure
domain functions in :mod:`app.domain` (CPVH, LTV-to-Cost, churn, payback,
currency normalization, recommendation) into a single ``evaluate`` call that:

1. **Normalizes cost to USD first** (R21.2). It looks up the dated
   ``exchange_rates`` row for ``(native_currency, USD, rate_date)`` and, when the
   rate is missing, rejects the valuation *without persisting any normalized
   values* (R21.5) by raising
   :class:`~app.core.errors.ExchangeRateUnavailableError`.
2. **Applies territory-weighted CPM and LTV** across the title's
   ``target_territories`` using per-territory ``market_telemetry_cache`` indices
   (R21.3). The weighting is documented on :meth:`Guardrails_Engine._territory_weighting`.
3. **Runs the four guardrail checks** via the pure domain functions, building a
   :class:`~app.domain.recommendation.GuardrailCheck` per guardrail with the
   computed value, threshold, pass/breach status, normalized shortfall
   magnitude, and correctable classification:
     * CPVH (R4): breach when computed ``>`` ceiling; CPVH is null and the check
       fails when ``projected_viewing_hours == 0`` and no ``calculated_cpvh`` is
       persisted (R4.5); a title with no applicable ceiling fails (R4.4).
     * LTV-to-Cost (R5): breach when ``< 3.2``.
     * Churn mitigation (R6): breach when ``< 1.5``.
     * Payback horizon (R7): target 9-12 inclusive; breach when ``> 12``.
4. **Determines the recommendation and builds the explanation** via
   :func:`~app.domain.recommendation.determine_recommendation` (R8, R30.4).
5. **Persists** ``calculated_cpvh`` / ``ltv_to_cost_multiple`` /
   ``churn_reduction_pct`` / ``payback_horizon_months`` / ``recommendation_status``
   / ``normalized_cost_usd`` / ``exchange_rate_id`` / ``model_version_id`` /
   ``explanation`` to ``financial_projections``, **retrying up to 3 times** and
   preserving the prior stored value on persistent failure (R8.6, R8.7).
6. **Stamps** the valuation with the active ``model_version_id`` via
   :class:`~app.engines.model_versioning.ModelVersioningEngine` and emits an
   append-only **audit** entry via
   :class:`~app.engines.audit.AuditLogService` (R25.1, R25.3).

Dependency injection and testability
------------------------------------
The engine takes every collaborator by constructor injection: the title /
financial-projection / exchange-rate / license-term / telemetry repositories, the
model-versioning engine, the audit service, and a
:class:`ValuationInputProvider`. The provider supplies the raw financial inputs
(churn-reduction value, LTV, watch-time elasticity, CPM, ad impressions, modeled
churn-reduction percentage, milestone schedule, monthly margin) that are not
columns on the ``titles`` table. In production these come from the
feature-extraction / financial-modeling pipeline; in tests they come from an
in-memory fake. This keeps the orchestration pure of hidden I/O and fully
exercisable without a live database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Optional, Protocol, Sequence, TypedDict

from app.core.errors import ExchangeRateUnavailableError, TitleNotFoundError
from app.domain.cpvh import (
    AssetType,
    CPVHComputationError,
    compute_cpvh,
    cpvh_breaches,
    cpvh_ceiling,
)
from app.domain.currency import (
    BASE_CURRENCY,
    ExchangeRate as DomainExchangeRate,
    MissingExchangeRateError,
    NormalizedCost,
    normalize_to_usd,
)
from app.domain.attribution import ltv_attribution
from app.domain.cohort import (
    derive_modeled_cohort_size,
    retained_subscribers,
)
from app.domain.ltv import (
    LTV_TO_COST_THRESHOLD,
    compute_ltv_to_cost,
    is_ltv_breach,
)
from app.domain.recommendation import (
    GuardrailCheck,
    Explanation,
    RecommendationStatus,
    determine_recommendation,
)
from app.domain.windowing import (
    PaybackComputationError,
    compute_payback_horizon,
)

__all__ = [
    "CHURN_MITIGATION_THRESHOLD",
    "PAYBACK_TARGET_MIN_MONTHS",
    "PAYBACK_TARGET_MAX_MONTHS",
    "TerritoryWeights",
    "ValuationInputs",
    "ValuationInputProvider",
    "ValuationResult",
    "GuardrailPersistenceError",
    "Guardrails_Engine",
]

# --- Guardrail thresholds (mirroring the design) -------------------------- #

# Churn mitigation guardrail: breach when the modeled monthly churn reduction
# percentage is strictly below 1.5% (R6.2, R6.3).
CHURN_MITIGATION_THRESHOLD: Decimal = Decimal("1.5")

# Payback horizon guardrail: the target window is 9-12 months inclusive; a value
# strictly greater than 12 breaches (R7.2, R7.3).
PAYBACK_TARGET_MIN_MONTHS: int = 9
PAYBACK_TARGET_MAX_MONTHS: int = 12

# How many times to retry persisting the projection before giving up (R8.7).
_MAX_PERSIST_ATTEMPTS: int = 3


# --------------------------------------------------------------------------- #
# Injected inputs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TerritoryWeights:
    """Per-territory weighting factors derived from market telemetry (R21.3).

    ``cpm_weight`` and ``ltv_weight`` are multipliers applied to the base CPM and
    LTV for a single target territory. They are derived from that territory's
    ``market_telemetry_cache`` indices (see
    :meth:`Guardrails_Engine._territory_weighting`); a territory with no cached
    telemetry contributes a neutral weight of ``1`` so it neither inflates nor
    deflates the blended figure.
    """

    territory: str
    cpm_weight: Decimal = Decimal("1")
    ltv_weight: Decimal = Decimal("1")


@dataclass(frozen=True)
class ValuationInputs:
    """The raw financial inputs a valuation needs beyond the title row.

    These are the modeled figures the LTV / churn / payback math consumes. They
    are *not* columns on ``titles`` (which only carries cost, currency, asset
    type, viewing hours, territories, and genre), so they are supplied by the
    injected :class:`ValuationInputProvider`. All monetary values are expressed
    in USD *before* territory weighting (the engine applies the per-territory CPM
    and LTV weights itself, R21.3).

    Attributes:
        churn_reduction_value: Subscription churn-reduction value contribution
            (USD) used in the LTV-to-Cost numerator (R5.1).
        ltv: Base subscriber lifetime value (USD), pre territory weighting.
        watch_time_elasticity: Watch-time elasticity coefficient.
        cpm: Base cost-per-mille (USD), pre territory weighting.
        ad_impressions: Projected advertising impressions.
        monthly_margin: Monthly contribution margin used by milestone-based
            payback (R7.1, R22.2).
        churn_reduction_pct: The carried churn-reduction value, now *optional*
            (calculable-churn-model, R4.6). A ``Decimal`` means an explicitly
            supplied value (SUPPLIED) that overrides the model exactly; ``None``
            means "resolve and compute" — the engine resolves the title's
            features and computes churn from the Churn_Mitigation_Model (wired in
            a later task). The field is ordered among the defaulted trailing
            fields so it can default to ``None`` without breaking the frozen
            dataclass's field-ordering contract; every caller in this repo
            constructs ``ValuationInputs`` with keyword arguments, so the
            reordering is positionally transparent.
        milestone_schedule: Milestone disbursement schedule; when omitted the
            engine falls back to the title's ``license_terms`` row (R22.2).
        rate_date: The exchange-rate date to normalize against; defaults to the
            provider's choice / today's date when unset.
    """

    churn_reduction_value: Decimal
    ltv: Decimal
    watch_time_elasticity: Decimal
    cpm: Decimal
    ad_impressions: Decimal
    monthly_margin: Decimal
    churn_reduction_pct: Decimal | None = None
    milestone_schedule: Sequence[dict[str, Any]] | None = None
    rate_date: Optional[date] = None
    #: Optional modeled addressable cohort size for absolute churn numbers; when
    #: absent the engine derives a labeled placeholder. Never a guardrail input.
    modeled_cohort_size: Decimal | None = None


class ValuationInputProvider(Protocol):
    """Supplies the modeled financial inputs for a title's valuation.

    Implemented in production by the financial-modeling pipeline and in tests by
    an in-memory fake. Keeping it a Protocol means the engine depends only on the
    shape, not a concrete class, so orchestration stays testable (R-design:
    dependency injection).
    """

    async def get_inputs(self, title_id: uuid.UUID) -> ValuationInputs:
        """Return the :class:`ValuationInputs` for ``title_id``."""
        ...


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #


class ValuationResult(TypedDict):
    """The shape returned by :meth:`Guardrails_Engine.evaluate` (per design).

    Mirrors the persisted scorecard: the four guardrail outputs, the final
    recommendation status, the model-version stamp, and the structured
    explanation consumed by the explainability surface (R30.4).
    """

    title_id: uuid.UUID
    calculated_cpvh: Decimal | None
    ltv_to_cost_multiple: Decimal
    churn_reduction_pct: Decimal
    payback_horizon_months: int
    recommendation_status: RecommendationStatus
    normalized_cost_usd: Decimal
    exchange_rate_id: uuid.UUID | None
    model_version_id: uuid.UUID
    explanation: Explanation
    # Deal Decision Support (additive; response-composition only, not persisted).
    ltv_subscription_value: Decimal | None
    ltv_advertising_value: Decimal | None
    ltv_total_modeled_value: Decimal | None
    modeled_cohort_size: Decimal | None
    retained_subscribers: Decimal | None


class GuardrailPersistenceError(RuntimeError):
    """Raised when persisting the projection fails after all retries (R8.7).

    Carries the affected ``title_id`` so the caller can surface which valuation
    could not be stored. The previously stored projection value is preserved
    (the retry path never partially overwrites it).
    """

    def __init__(self, title_id: uuid.UUID, attempts: int, cause: BaseException) -> None:
        self.title_id = title_id
        self.attempts = attempts
        self.__cause__ = cause
        super().__init__(
            f"failed to persist financial projection for title {title_id!r} after "
            f"{attempts} attempt(s); the previously stored value is preserved (R8.7)."
        )


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #


class Guardrails_Engine:
    """Orchestrates currency normalization, guardrail checks, and persistence.

    Every collaborator is injected so the engine can run against in-memory fakes
    in tests and real repositories in production. The engine performs no commits
    itself: like the repositories it builds on, it flushes within the caller's
    unit of work, so the whole valuation (projection write + audit entry) is one
    atomic transaction owned by the request/task boundary.
    """

    def __init__(
        self,
        *,
        title_repository: Any,
        projection_repository: Any,
        exchange_rate_repository: Any,
        license_term_repository: Any,
        telemetry_repository: Any,
        model_versioning_engine: Any,
        audit_service: Any,
        input_provider: ValuationInputProvider,
    ) -> None:
        self._titles = title_repository
        self._projections = projection_repository
        self._exchange_rates = exchange_rate_repository
        self._license_terms = license_term_repository
        self._telemetry = telemetry_repository
        self._versioning = model_versioning_engine
        self._audit = audit_service
        self._inputs = input_provider

    # -- public API -------------------------------------------------------- #

    async def evaluate(
        self,
        title_id: uuid.UUID,
        model_version_id: uuid.UUID | None = None,
        *,
        actor: uuid.UUID | None = None,
    ) -> ValuationResult:
        """Evaluate all guardrails for a title and persist the scorecard.

        Order of operations is deliberate and matches the design:

        1. Load the title (not-found -> :class:`TitleNotFoundError`, R9.3).
        2. Normalize the acquisition cost to USD *first* (R21.2); a missing rate
           rejects the valuation before any write (R21.5).
        3. Resolve the active model-version stamp (R25.3, R26.2). The caller may
           pass an explicit ``model_version_id`` (e.g. to reproduce a historical
           valuation); otherwise the active version is used.
        4. Run the CPVH / LTV / churn / payback checks and build the explanation.
        5. Determine the recommendation (R8, R30.4).
        6. Persist the projection with up to 3 retries, preserving the prior
           value on persistent failure (R8.6, R8.7).
        7. Emit an append-only audit entry stamped with the model version
           (R25.1, R25.3).

        Args:
            title_id: The title to evaluate.
            model_version_id: Optional explicit model-version stamp; defaults to
                the active version.
            actor: Optional identity recorded on the audit entry.

        Returns:
            A :class:`ValuationResult` with the computed scorecard, stamp, and
            explanation.

        Raises:
            TitleNotFoundError: The title does not exist (R9.3).
            ExchangeRateUnavailableError: No rate is available to normalize the
                cost to USD; nothing is persisted (R21.5).
            GuardrailPersistenceError: Persistence failed after all retries
                (R8.7).
        """
        title = await self._titles.get(title_id)
        if title is None:
            raise TitleNotFoundError(
                f"No title exists for id {title_id!r}.",
                details={"title_id": str(title_id)},
            )

        inputs = await self._inputs.get_inputs(title_id)

        # 2. Normalize cost to USD FIRST (R21.2); reject on missing rate (R21.5).
        normalized, exchange_rate_id = await self._normalize_cost(title, inputs)

        # 3. Resolve the model-version stamp (R25.3, R26.2).
        stamp = model_version_id or await self._versioning.stamp()

        # 4. Territory-weighted CPM / LTV across target territories (R21.3).
        weighting = await self._territory_weighting(title)

        # 5. The payback check reads license terms (async I/O), so it is computed
        # here and threaded into the pure compute core.
        payback_check, payback_months = await self._payback_check(title, inputs)

        # 5-6. Run the guardrail checks, recommendation, and deal-support block
        # through the shared pure compute core (no I/O).
        result = self._compute(
            title, inputs, normalized, exchange_rate_id, stamp, weighting,
            payback_check, payback_months,
        )
        explanation = result["explanation"]

        # 7. Persist with retries, preserving prior value (R8.6, R8.7).
        await self._persist(title_id, result, explanation)

        # 8. Append-only audit entry stamped with the model version (R25.1, R25.3).
        await self._audit.record(
            actor,
            "valuation",
            None,
            self._audit_after(result),
            model_version_id=stamp,
            subject_id=title_id,
        )

        return result

    # -- shared pure compute core + stateless scenario path ---------------- #

    def _compute(
        self,
        title: Any,
        inputs: ValuationInputs,
        normalized: NormalizedCost,
        exchange_rate_id: uuid.UUID | None,
        stamp: uuid.UUID,
        weighting: TerritoryWeights,
        payback_check: GuardrailCheck,
        payback_months: int,
        *,
        cpvh_hours_override: Decimal | None = None,
    ) -> ValuationResult:
        """Run the four guardrail checks, the recommendation, and the deal-support
        block, returning a :class:`ValuationResult`. Performs NO I/O, NO
        persistence, and NO audit, so it is shared verbatim by the persisting
        ``evaluate`` path and the stateless ``evaluate_scenario`` path (identical
        math; no threshold or recommendation forking).
        """
        weighted_cpm = inputs.cpm * weighting.cpm_weight
        weighted_ltv = inputs.ltv * weighting.ltv_weight

        cpvh_check, calculated_cpvh = self._cpvh_check(
            title, normalized.amount_usd, cpvh_hours_override
        )
        ltv_check, ltv_multiple = self._ltv_check(
            inputs, normalized.amount_usd, weighted_cpm, weighted_ltv
        )
        # churn_reduction_pct is now optional (calculable-churn-model, R4.6): a
        # Decimal is an explicitly supplied value; None means "resolve and
        # compute". The resolve-and-compute wiring lands in a later task; for now
        # a None value falls back to a conservative Decimal("0") so the type and
        # the current churn-check semantics are preserved exactly.
        churn_pct = (
            inputs.churn_reduction_pct
            if inputs.churn_reduction_pct is not None
            else Decimal("0")
        )
        churn_check = self._churn_check(churn_pct)

        checks: list[GuardrailCheck] = [
            cpvh_check,
            ltv_check,
            churn_check,
            payback_check,
        ]

        status, explanation = determine_recommendation(checks)

        ltv_sub = ltv_adv = ltv_total = cohort_size = retained = None
        try:
            if normalized.amount_usd and normalized.amount_usd != 0:
                attribution = ltv_attribution(
                    inputs.churn_reduction_value,
                    weighted_ltv,
                    inputs.watch_time_elasticity,
                    weighted_cpm,
                    inputs.ad_impressions,
                    normalized.amount_usd,
                )
                ltv_sub = attribution["subscription_value"]
                ltv_adv = attribution["advertising_value"]
                ltv_total = attribution["total_modeled_value"]
            cohort_size = (
                inputs.modeled_cohort_size
                if inputs.modeled_cohort_size is not None
                else derive_modeled_cohort_size(normalized.amount_usd)
            )
            retained = retained_subscribers(cohort_size, churn_pct)
        except (ArithmeticError, TypeError, ValueError):
            ltv_sub = ltv_adv = ltv_total = cohort_size = retained = None

        return {
            "title_id": title.title_id,
            "calculated_cpvh": calculated_cpvh,
            "ltv_to_cost_multiple": ltv_multiple,
            "churn_reduction_pct": churn_pct,
            "payback_horizon_months": payback_months,
            "recommendation_status": status,
            "normalized_cost_usd": normalized.amount_usd,
            "exchange_rate_id": exchange_rate_id,
            "model_version_id": stamp,
            "explanation": explanation,
            "ltv_subscription_value": ltv_sub,
            "ltv_advertising_value": ltv_adv,
            "ltv_total_modeled_value": ltv_total,
            "modeled_cohort_size": cohort_size,
            "retained_subscribers": retained,
        }

    async def evaluate_scenario(
        self,
        title_id: uuid.UUID,
        *,
        cost_multiplier: Decimal,
        viewership_multiplier: Decimal,
        churn_multiplier: Decimal,
    ) -> ValuationResult:
        """Recompute a scorecard over scaled inputs WITHOUT persisting (R1, R2).

        Loads the title and its base inputs, normalizes cost to USD, scales the
        normalized cost by ``cost_multiplier`` and the remaining inputs via
        :func:`app.domain.sensitivity.scale_inputs`, and runs the shared
        :meth:`_compute` core. NEVER calls ``_persist`` or the audit service, and
        resolves the active model-version stamp read-only (R2.3).

        Raises:
            TitleNotFoundError: The title does not exist (R1.3).
            ExchangeRateUnavailableError: No rate to normalize a non-USD cost.
        """
        import dataclasses as _dc

        from app.domain.sensitivity import scale_inputs

        title = await self._titles.get(title_id)
        if title is None:
            raise TitleNotFoundError(
                f"No title exists for id {title_id!r}.",
                details={"title_id": str(title_id)},
            )

        inputs = await self._inputs.get_inputs(title_id)
        normalized, exchange_rate_id = await self._normalize_cost(title, inputs)
        stamp = await self._versioning.stamp()
        weighting = await self._territory_weighting(title)

        payback_check, payback_months = await self._payback_check(title, inputs)

        base_hours = getattr(title, "projected_viewing_hours", None)
        scaled = scale_inputs(
            inputs,
            None if base_hours is None else Decimal(base_hours),
            cost_multiplier=cost_multiplier,
            viewership_multiplier=viewership_multiplier,
            churn_multiplier=churn_multiplier,
        )
        scaled_cost = _dc.replace(
            normalized, amount_usd=normalized.amount_usd * Decimal(cost_multiplier)
        )

        return self._compute(
            title,
            scaled.inputs,
            scaled_cost,
            exchange_rate_id,
            stamp,
            weighting,
            payback_check,
            payback_months,
            cpvh_hours_override=scaled.viewing_hours,
        )

    # -- currency normalization (R21.2, R21.5) ----------------------------- #

    async def _normalize_cost(
        self, title: Any, inputs: ValuationInputs
    ) -> tuple[NormalizedCost, uuid.UUID | None]:
        """Normalize the acquisition cost to USD before any guardrail math.

        Looks up the dated ``(native_currency, USD, rate_date)`` rate. A USD-native
        cost needs no conversion and normalizes at a rate of 1 with no
        ``exchange_rate_id``. A missing rate for a non-USD currency raises
        :class:`ExchangeRateUnavailableError`, which rejects the valuation before
        anything is persisted (R21.5).
        """
        native = title.native_currency
        rate_date = inputs.rate_date or date.today()
        cost = title.acquisition_cost_or_budget

        if native == BASE_CURRENCY:
            # No conversion needed; rate is identity, no exchange_rate row used.
            normalized = normalize_to_usd(
                cost,
                Decimal("1"),
                rate_date=rate_date,
                from_currency=native,
            )
            return normalized, None

        rate_row = await self._exchange_rates.get_rate(native, BASE_CURRENCY, rate_date)
        if rate_row is None:
            # No rate dated exactly on rate_date: fall back to the most recent
            # available rate for this currency pair rather than rejecting. A
            # dated table rarely carries today's row, and the latest known rate
            # is the correct real-world behavior (and keeps re-valuation /
            # what-if working on titles seeded with historical rates).
            rate_row = await self._exchange_rates.get_latest_rate(
                native, BASE_CURRENCY
            )
        if rate_row is None:
            # Truly no rate on record for this pair: reject, persisting nothing (R21.5).
            raise ExchangeRateUnavailableError(
                f"No exchange rate available to convert {native} to "
                f"{BASE_CURRENCY} on {rate_date.isoformat()}.",
                details={
                    "from_currency": native,
                    "to_currency": BASE_CURRENCY,
                    "rate_date": rate_date.isoformat(),
                },
            )

        try:
            normalized = normalize_to_usd(
                cost,
                DomainExchangeRate(
                    rate=rate_row.rate,
                    rate_date=rate_row.rate_date,
                    from_currency=native,
                    to_currency=BASE_CURRENCY,
                    exchange_rate_id=str(rate_row.exchange_rate_id),
                ),
            )
        except MissingExchangeRateError as exc:  # pragma: no cover - defensive
            raise ExchangeRateUnavailableError(str(exc)) from exc

        return normalized, rate_row.exchange_rate_id

    # -- territory weighting (R21.3) --------------------------------------- #

    async def _territory_weighting(self, title: Any) -> TerritoryWeights:
        """Compute blended CPM / LTV weights across the title's territories (R21.3).

        Weighting model (documented): for each target territory we read its
        ``market_telemetry_cache`` row (keyed by ``(genre_tag, territory)``) and
        derive two multipliers:

        * ``cpm_multiplier``   = ``licensing_inflation_multiplier`` (how much ad
          inventory in that territory costs relative to baseline; defaults to 1).
        * ``ltv_multiplier``   = ``1 + (chart_velocity_score / 100)`` (chart
          momentum lifts subscriber lifetime value; a 0 score is neutral).

        The per-territory multipliers are averaged (equal-weight mean) across all
        target territories to produce a single blended CPM weight and LTV weight.
        A territory with no cached telemetry contributes a neutral ``1`` so it
        neither inflates nor deflates the blend. With no territories at all the
        weights fall back to ``1`` (identity), leaving the base CPM / LTV
        unchanged.

        The equal-weight mean keeps the blend bounded and deterministic; a richer
        population-share weighting can replace the mean without changing the
        engine's contract.
        """
        territories = self._extract_territories(title)
        if not territories:
            return TerritoryWeights(territory="", cpm_weight=Decimal("1"), ltv_weight=Decimal("1"))

        genre = getattr(title, "genre_tag", None)
        cpm_multipliers: list[Decimal] = []
        ltv_multipliers: list[Decimal] = []

        for territory in territories:
            telemetry = None
            if genre is not None:
                telemetry = await self._telemetry.get_for_genre_territory(
                    genre, territory
                )
            cpm_multiplier = Decimal("1")
            ltv_multiplier = Decimal("1")
            if telemetry is not None:
                inflation = getattr(telemetry, "licensing_inflation_multiplier", None)
                if inflation is not None:
                    cpm_multiplier = Decimal(inflation)
                velocity = getattr(telemetry, "chart_velocity_score", None)
                if velocity is not None:
                    ltv_multiplier = Decimal("1") + (Decimal(velocity) / Decimal("100"))
            cpm_multipliers.append(cpm_multiplier)
            ltv_multipliers.append(ltv_multiplier)

        count = Decimal(len(territories))
        cpm_weight = sum(cpm_multipliers, Decimal("0")) / count
        ltv_weight = sum(ltv_multipliers, Decimal("0")) / count

        return TerritoryWeights(
            territory=",".join(territories),
            cpm_weight=cpm_weight,
            ltv_weight=ltv_weight,
        )

    @staticmethod
    def _extract_territories(title: Any) -> list[str]:
        """Normalize ``target_territories`` (JSONB list or dict) to a list of codes."""
        raw = getattr(title, "target_territories", None)
        if raw is None:
            return []
        if isinstance(raw, dict):
            # Accept {"territories": [...]} or a mapping of code -> weight/flag.
            if "territories" in raw and isinstance(raw["territories"], list):
                return [str(t) for t in raw["territories"]]
            return [str(k) for k in raw.keys()]
        if isinstance(raw, (list, tuple)):
            return [str(t) for t in raw]
        return []

    # -- CPVH check (R4) --------------------------------------------------- #

    def _cpvh_check(
        self,
        title: Any,
        cost_usd: Decimal,
        viewing_hours_override: Decimal | None = None,
    ) -> tuple[GuardrailCheck, Decimal | None]:
        """Build the CPVH guardrail check (R4).

        * ``projected_viewing_hours == 0`` -> failed check, CPVH null, nothing to
          persist as ``calculated_cpvh`` (R4.5). This is a non-correctable breach
          (cost renegotiation cannot create viewing hours).
        * No applicable ceiling for the asset type -> failed check (R4.4), also
          non-correctable.
        * Otherwise compute CPVH (R4.1); breach when strictly ``>`` ceiling
          (R4.6), pass when ``<=`` (R4.7). A breach is correctable because a lower
          cost lowers CPVH back under the ceiling.
        """
        viewing_hours = (
            viewing_hours_override
            if viewing_hours_override is not None
            else getattr(title, "projected_viewing_hours", None)
        )
        asset_type = self._as_asset_type(getattr(title, "asset_type", None))
        ceiling = cpvh_ceiling(asset_type) if asset_type is not None else None

        # Zero / missing viewing hours: CPVH cannot be computed (R4.5).
        if viewing_hours is None or Decimal(viewing_hours) == 0:
            check: GuardrailCheck = {
                "name": "CPVH",
                "computed_value": None,
                "threshold": ceiling if ceiling is not None else Decimal("0"),
                "passed": False,
                "breached": True,
                "shortfall_magnitude": None,
                "correctable": False,
            }
            return check, None

        # No applicable ceiling for this classification (R4.4).
        if ceiling is None:
            check = {
                "name": "CPVH",
                "computed_value": None,
                "threshold": Decimal("0"),
                "passed": False,
                "breached": True,
                "shortfall_magnitude": None,
                "correctable": False,
            }
            return check, None

        try:
            cpvh = compute_cpvh(cost_usd, Decimal(viewing_hours))
        except CPVHComputationError:  # pragma: no cover - guarded above
            check = {
                "name": "CPVH",
                "computed_value": None,
                "threshold": ceiling,
                "passed": False,
                "breached": True,
                "shortfall_magnitude": None,
                "correctable": False,
            }
            return check, None

        breached = cpvh_breaches(cpvh, ceiling)
        shortfall = self._normalized_shortfall(cpvh - ceiling, ceiling) if breached else None
        check = {
            "name": "CPVH",
            "computed_value": cpvh,
            "threshold": ceiling,
            "passed": not breached,
            "breached": breached,
            "shortfall_magnitude": shortfall,
            # Overpriced acquisitions come back under the ceiling with a lower
            # cost, so a CPVH breach is correctable through renegotiation (R8.2).
            "correctable": True if breached else None,
        }
        return check, cpvh

    # -- LTV check (R5) ---------------------------------------------------- #

    def _ltv_check(
        self,
        inputs: ValuationInputs,
        cost_usd: Decimal,
        weighted_cpm: Decimal,
        weighted_ltv: Decimal,
    ) -> tuple[GuardrailCheck, Decimal]:
        """Build the LTV-to-Cost guardrail check (R5).

        CPM and LTV are already territory-weighted by the caller (R21.3). Breach
        when the multiple is strictly below 3.2 (R5.3). An LTV breach is
        correctable: dividing by a smaller cost raises the multiple, so a cost
        renegotiation can bring it back over the threshold (R8.2).
        """
        multiple = compute_ltv_to_cost(
            churn_reduction_value=inputs.churn_reduction_value,
            ltv=weighted_ltv,
            watch_time_elasticity=inputs.watch_time_elasticity,
            cpm=weighted_cpm,
            ad_impressions=inputs.ad_impressions,
            cost_usd=cost_usd,
        )
        breached = is_ltv_breach(multiple)
        shortfall = (
            self._normalized_shortfall(LTV_TO_COST_THRESHOLD - multiple, LTV_TO_COST_THRESHOLD)
            if breached
            else None
        )
        check: GuardrailCheck = {
            "name": "LTV_TO_COST",
            "computed_value": multiple,
            "threshold": LTV_TO_COST_THRESHOLD,
            "passed": not breached,
            "breached": breached,
            "shortfall_magnitude": shortfall,
            "correctable": True if breached else None,
        }
        return check, multiple

    # -- churn check (R6) -------------------------------------------------- #

    def _churn_check(self, churn_reduction_pct: Decimal) -> GuardrailCheck:
        """Build the churn-mitigation guardrail check (R6).

        Breach when the modeled monthly churn-reduction percentage is strictly
        below 1.5% (R6.3). A churn breach is driven by the title's intrinsic
        retention effect, not by cost, so renegotiating cost cannot lift it:
        it is a non-correctable breach (R8.3).
        """
        pct = Decimal(churn_reduction_pct)
        breached = pct < CHURN_MITIGATION_THRESHOLD
        shortfall = (
            self._normalized_shortfall(
                CHURN_MITIGATION_THRESHOLD - pct, CHURN_MITIGATION_THRESHOLD
            )
            if breached
            else None
        )
        return {
            "name": "CHURN_MITIGATION",
            "computed_value": pct,
            "threshold": CHURN_MITIGATION_THRESHOLD,
            "passed": not breached,
            "breached": breached,
            "shortfall_magnitude": shortfall,
            "correctable": False if breached else None,
        }

    # -- payback check (R7) ------------------------------------------------ #

    async def _payback_check(
        self, title: Any, inputs: ValuationInputs
    ) -> tuple[GuardrailCheck, int]:
        """Build the payback-horizon guardrail check (R7) from milestones (R22.2).

        Uses the milestone schedule (from ``inputs`` or, if absent, the title's
        ``license_terms`` row) with the monthly contribution margin. Target window
        is 9-12 inclusive; breach when the horizon is strictly ``> 12`` (R7.3).
        A horizon that cannot be computed (non-positive margin / malformed
        schedule) marks the check failed and unclassifiable so the recommendation
        resolves to PASS with the unclassifiable flag (R8.4). A payback breach is
        correctable: a lower cost shortens the horizon (R8.2).
        """
        schedule = inputs.milestone_schedule
        if schedule is None:
            schedule = await self._milestone_schedule_from_license(title)

        try:
            months = compute_payback_horizon(schedule or [], inputs.monthly_margin)
        except PaybackComputationError:
            # Cannot classify payback -> unclassifiable breach -> PASS + flag (R8.4).
            check: GuardrailCheck = {
                "name": "PAYBACK_HORIZON",
                "computed_value": None,
                "threshold": Decimal(PAYBACK_TARGET_MAX_MONTHS),
                "passed": False,
                "breached": True,
                "shortfall_magnitude": None,
                "correctable": None,
            }
            # Return a sentinel 0 horizon; the null computed_value conveys "unknown".
            return check, 0

        breached = months > PAYBACK_TARGET_MAX_MONTHS
        shortfall = (
            self._normalized_shortfall(
                Decimal(months - PAYBACK_TARGET_MAX_MONTHS),
                Decimal(PAYBACK_TARGET_MAX_MONTHS),
            )
            if breached
            else None
        )
        check = {
            "name": "PAYBACK_HORIZON",
            "computed_value": Decimal(months),
            "threshold": Decimal(PAYBACK_TARGET_MAX_MONTHS),
            "passed": not breached,
            "breached": breached,
            "shortfall_magnitude": shortfall,
            "correctable": True if breached else None,
        }
        return check, months

    async def _milestone_schedule_from_license(
        self, title: Any
    ) -> list[dict[str, Any]]:
        """Fetch the milestone schedule from the title's license terms (R22.2)."""
        terms = await self._license_terms.list_for_title(title.title_id)
        for term in terms:
            schedule = getattr(term, "milestone_schedule", None)
            if schedule:
                return list(schedule)
        return []

    # -- persistence with retry (R8.6, R8.7) ------------------------------- #

    async def _persist(
        self,
        title_id: uuid.UUID,
        result: ValuationResult,
        explanation: Explanation,
    ) -> None:
        """Persist the projection, retrying up to 3 times, preserving prior value.

        Attempts an ``update_with_version`` on an existing projection for the
        title, falling back to a ``create`` when none exists. On any failure the
        attempt is retried up to :data:`_MAX_PERSIST_ATTEMPTS` times. If every
        attempt fails, :class:`GuardrailPersistenceError` is raised identifying
        the affected title; because each attempt is all-or-nothing, the
        previously stored projection value is never partially overwritten (R8.7).
        """
        values = self._projection_values(result, explanation)

        last_error: BaseException | None = None
        for attempt in range(1, _MAX_PERSIST_ATTEMPTS + 1):
            try:
                existing = await self._projections.get_latest_for_title(title_id)
                if existing is None:
                    projection = self._projections.model(
                        title_id=title_id,
                        **values,
                    )
                    await self._projections.create(projection)
                else:
                    await self._projections.update_with_version(
                        existing.projection_id,
                        existing.row_version,
                        **values,
                    )
                return
            except Exception as exc:  # noqa: BLE001 - retried; re-raised below
                last_error = exc
                continue

        raise GuardrailPersistenceError(
            title_id, _MAX_PERSIST_ATTEMPTS, last_error or RuntimeError("unknown")
        )

    @staticmethod
    def _projection_values(
        result: ValuationResult, explanation: Explanation
    ) -> dict[str, Any]:
        """Map a :class:`ValuationResult` to ``financial_projections`` columns."""
        return {
            "calculated_cpvh": result["calculated_cpvh"],
            "ltv_to_cost_multiple": result["ltv_to_cost_multiple"],
            "churn_reduction_pct": result["churn_reduction_pct"],
            "payback_horizon_months": result["payback_horizon_months"],
            "recommendation_status": result["recommendation_status"],
            "normalized_cost_usd": result["normalized_cost_usd"],
            "exchange_rate_id": result["exchange_rate_id"],
            "model_version_id": result["model_version_id"],
            "explanation": _jsonable_explanation(explanation),
        }

    @staticmethod
    def _audit_after(result: ValuationResult) -> dict[str, Any]:
        """Build the JSON-serializable 'after' snapshot for the audit entry."""
        return {
            "title_id": str(result["title_id"]),
            "calculated_cpvh": _decimal_str(result["calculated_cpvh"]),
            "ltv_to_cost_multiple": _decimal_str(result["ltv_to_cost_multiple"]),
            "churn_reduction_pct": _decimal_str(result["churn_reduction_pct"]),
            "payback_horizon_months": result["payback_horizon_months"],
            "recommendation_status": result["recommendation_status"],
            "normalized_cost_usd": _decimal_str(result["normalized_cost_usd"]),
            "exchange_rate_id": (
                str(result["exchange_rate_id"])
                if result["exchange_rate_id"] is not None
                else None
            ),
            "model_version_id": str(result["model_version_id"]),
        }

    # -- helpers ----------------------------------------------------------- #

    @staticmethod
    def _as_asset_type(value: Any) -> AssetType | None:
        """Coerce a stored asset-type string to :class:`AssetType`, or ``None``."""
        if value is None:
            return None
        if isinstance(value, AssetType):
            return value
        try:
            return AssetType(str(value))
        except ValueError:
            return None

    @staticmethod
    def _normalized_shortfall(distance: Decimal, threshold: Decimal) -> Decimal:
        """Return the shortfall normalized against the threshold (R30.2).

        Normalizing (``|distance| / threshold``) makes shortfalls comparable
        across guardrails with different scales so the dominant factor (R30.3) is
        chosen on a common axis. A zero/degenerate threshold falls back to the
        raw absolute distance.
        """
        magnitude = abs(distance)
        if threshold and threshold != 0:
            return magnitude / abs(threshold)
        return magnitude


# --------------------------------------------------------------------------- #
# Module-level helpers
# --------------------------------------------------------------------------- #


def _decimal_str(value: Decimal | None) -> str | None:
    """Render a Decimal as a string (JSON-safe), or ``None``."""
    return str(value) if value is not None else None


def _jsonable_explanation(explanation: Explanation) -> dict[str, Any]:
    """Convert an :class:`Explanation` into a JSON-serializable dict for JSONB.

    Decimals become strings so the stored ``explanation`` round-trips without
    precision loss and is valid JSON (JSONB has no Decimal type).
    """
    checks: list[dict[str, Any]] = []
    for check in explanation["checks"]:
        checks.append(
            {
                "name": check["name"],
                "computed_value": _decimal_str(check["computed_value"]),
                "threshold": _decimal_str(check["threshold"]),
                "passed": check["passed"],
                "breached": check["breached"],
                "shortfall_magnitude": _decimal_str(check["shortfall_magnitude"]),
                "correctable": check["correctable"],
            }
        )
    return {
        "checks": checks,
        "dominant_factor": explanation["dominant_factor"],
        "unclassifiable": explanation["unclassifiable"],
    }
