/**
 * Shared domain types mirroring the backend contract.
 *
 * These are the minimal shapes the typed API client exposes. They are expanded
 * as the backend schemas (task 16) and frontend views (tasks 19-21) are built.
 */

export type AssetType =
  | "ORIGINAL_SERIES"
  | "ORIGINAL_FILM"
  | "LICENSED_LIBRARY"
  | "CO_PRODUCTION";

export type RecommendationStatus = "GREENLIGHT" | "NEGOTIATE_HARD" | "PASS";

export type JobStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";

/** Standard backend error envelope: { error_code, message, details }. */
export interface ApiErrorEnvelope {
  error_code: string;
  message: string;
  details?: unknown;
}

/** Session context returned by the auth endpoints (R19.2). */
export interface SessionInfo {
  token: string;
  user_id: string;
  role: string;
  issued_at: string;
  expires_at: string;
}

/** The guardrail checks evaluated by the engine (R30.1). */
export type GuardrailName =
  | "CPVH"
  | "LTV_TO_COST"
  | "CHURN_MITIGATION"
  | "PAYBACK_HORIZON";

/**
 * One guardrail evaluation result from the recommendation explanation (R30.1, R30.2).
 *
 * Mirrors the backend `GuardrailCheck`. Decimal values are serialized by the
 * backend as JSON numbers or strings; the UI coerces them defensively.
 */
export interface GuardrailCheck {
  name: GuardrailName;
  /** The computed metric value, or `null` when it could not be computed. */
  computed_value: number | string | null;
  /** The applicable threshold for this guardrail. */
  threshold: number | string | null;
  passed: boolean;
  breached: boolean;
  /** Normalized distance past the threshold for a breach (R30.2), else `null`. */
  shortfall_magnitude: number | string | null;
  /**
   * `true` when the breach is correctable through renegotiated terms,
   * `false` when non-correctable, or `null` when it cannot be classified.
   */
  correctable: boolean | null;
}

/**
 * The Churn_Mitigation_Model explanation attached to a recommendation (R10).
 *
 * Mirrors the backend `churn_model` object persisted inside the explanation
 * JSON. `churn_breakdown` is `null` for a SUPPLIED result (and for a scaled
 * what-if scenario); its values are per-feature percentage points serialized as
 * JSON strings. A pre-feature stored explanation omits this object entirely, so
 * consumers MUST treat it as possibly absent (R7.6).
 */
export interface ChurnModel {
  /** How the churn-reduction percentage was obtained. */
  churn_method: "CALCULATED" | "SUPPLIED";
  /** `true` when the resolved value lies within [1.45, 1.55] of the hurdle (R5). */
  is_borderline: boolean;
  /** Whether the params came from the model version or the built-in defaults (R3.3). */
  params_source?: string;
  /** The model version in effect when churn was resolved, or `null` (R3.3). */
  model_version_id?: string | null;
  /** Feature keys that were missing and contributed zero (R2, R10.4). */
  missing_features?: string[];
  /**
   * Feature keys that used a neutral default rather than a real reading: a
   * missing market-telemetry reading or an unknown/absent genre (R14.3, R15.2).
   * Distinct from `missing_features` (which score zero).
   */
  assumed_features?: string[];
  /**
   * Per-feature contributions keyed by feature name (points as JSON strings).
   * `null` for a SUPPLIED result or a scaled what-if scenario (R10.3).
   */
  churn_breakdown?: Record<string, string> | null;
}

/**
 * Structured explainability payload for a recommendation (R30).
 *
 * Mirrors the backend `Explanation`: every guardrail check with its pass/breach
 * status (R30.1) plus the dominant contributing factor (R30.3).
 */
export interface Explanation {
  /**
   * Per-guardrail checks (R30.1). Present on a freshly computed valuation; the
   * stored explanation returned by `GET /valuation/{id}` for a seeded/ingested
   * title may omit it, so consumers MUST treat it as possibly undefined.
   */
  checks?: GuardrailCheck[];
  /** Name of the breached check with the largest shortfall, or `null` (R30.3). */
  dominant_factor?: GuardrailName | string | null;
  /** `true` when a breach could not be classified as correctable (R8.4). */
  unclassifiable?: boolean;
  /**
   * The Churn_Mitigation_Model explanation (R10). Absent on a pre-feature stored
   * explanation; `null` is also tolerated. Rides on both the title scorecard's
   * `explanation` and the quick-evaluate response's `explanation`.
   */
  churn_model?: ChurnModel | null;
}

/**
 * Extracted metadata profile surfaced in the full scorecard (R10.2, R15.1).
 *
 * A projection of the title's `metadata_vectors` row: the affective tone
 * triggers and the talent-pedigree / production-scale scores. The 1536-dim
 * Narrative_DNA embedding is summarized by its dimension count.
 */
export interface MetadataBreakdown {
  affective_primary: string | null;
  affective_secondary: string | null;
  talent_pedigree_score: number | string | null;
  production_scale_metric: number | string | null;
  narrative_dna_dimensions: number | null;
  extraction_status: string | null;
}

/**
 * The full valuation scorecard returned by `GET /valuation/{title_id}` (R10, R30.4).
 *
 * Carries the persisted guardrail outputs, the model-version stamp, the
 * metadata-vector breakdown (R10.2), and the recommendation explanation (R30.4).
 */
export interface ValuationScorecard {
  title_id: string;
  calculated_cpvh: number | string | null;
  ltv_to_cost_multiple: number | string | null;
  churn_reduction_pct: number | string | null;
  payback_horizon_months: number | null;
  recommendation_status: RecommendationStatus | null;
  normalized_cost_usd: number | string | null;
  model_version_id: string | null;
  explanation: Explanation | null;
  metadata_breakdown: MetadataBreakdown | null;
  /** Title descriptors for the market-telemetry lookup (R13.3). */
  genre_tag?: string | null;
  primary_territory?: string | null;
  /** Deal Decision Support (R4, R6, R8). Decimals arrive as JSON strings. */
  target_purchase_ceiling_usd?: number | string | null;
  implied_discount_pct?: number | string | null;
  counter_proposal_levers?: CounterProposalLever[];
  ltv_attribution?: LtvAttribution | null;
  churn_cohort?: ChurnCohort | null;}


/**
 * CPVH guardrail outcome for a title, as surfaced in the dashboard grid (R14.2).
 *
 * `PASS`/`BREACH` reflect whether the computed cost-per-viewing-hour is within
 * the asset-type ceiling (R4). `NO_CEILING` applies to asset types without a
 * defined ceiling, and `PENDING` to titles with no completed valuation yet.
 */
export type CpvhStatus = "PASS" | "BREACH" | "NO_CEILING" | "PENDING";

/**
 * KPI header-card figures for the Executive Command Dashboard (R14.1).
 *
 * All monetary values are USD-normalized. Fields are `null` when the pipeline
 * has no data to compute the figure (e.g. no completed valuations yet).
 */
export interface DashboardKpis {
  /** Sum of normalized acquisition cost across active-pipeline titles (USD). */
  active_pipeline_valuation_usd: number | null;
  /** Mean LTV-to-Cost multiple across valued titles. */
  avg_ltv_to_cost: number | null;
  /** Portfolio risk exposure index (0–1); higher means more breaches/PASS titles. */
  portfolio_risk_exposure: number | null;
  /** Model prediction accuracy rate (0–1), derived from backtesting MAPE. */
  model_accuracy_rate: number | null;
}

/**
 * One row of the master asset data grid (R14.2).
 *
 * Combines title identity with its latest valuation outcome. Valuation-derived
 * fields are `null`/`PENDING` until a completed valuation exists.
 */
export interface TitleSummary {
  title_id: string;
  title_name: string;
  asset_type: AssetType;
  /** Native asking price / acquisition cost (not currency-normalized). */
  asking_price: number;
  native_currency: string;
  cpvh_status: CpvhStatus;
  ltv_to_cost_multiple: number | null;
  recommendation_status: RecommendationStatus | null;
  deal_stage?: DealStage;
}

/** Aggregate payload backing the dashboard: KPI figures + the grid rows (R14). */
export interface DashboardSummary {
  kpis: DashboardKpis;
  titles: TitleSummary[];
}

// --------------------------------------------------------------------------- //
// Backtesting & Calibration Studio (R11, R12, R16)
// --------------------------------------------------------------------------- //

/** One observed actual-outcome metric in a ground-truth submission (R11.1). */
export interface GroundTruthMetricInput {
  /** The audited metric, e.g. "cpvh" or "ltv_to_cost_multiple". */
  metric_name: string;
  /** The observed actual value; must be numeric server-side (R11.2). */
  actual_value: number;
}

/** Request body for POST /backtest/audit — ground-truth submission (R11.1). */
export interface BacktestAuditRequest {
  title_id: string;
  metrics: GroundTruthMetricInput[];
}

/** One predicted/actual row of the returned audit scorecard (R11.6, R11.7). */
export interface AuditMetric {
  metric: string;
  /** Decimal values are serialized by the backend as JSON strings; coerce defensively. */
  predicted: number | string;
  actual: number | string;
  /** True when the pair was excluded from MAPE (zero actual — R11.7). */
  excluded: boolean;
}

/** The audit scorecard returned by POST /backtest/audit (R11.6, R11.8). */
export interface BacktestAuditResponse {
  title_id: string;
  metrics: AuditMetric[];
  /** Mean absolute percentage error across eligible metrics, or null (R11.8).
   * Serialized by the backend as a JSON string; the UI coerces defensively. */
  mape: number | string | null;
  /** True when every metric was excluded, so MAPE is undefined (R11.8). */
  no_eligible_metrics: boolean;
}

/** Request body for POST /calibration/apply (R12, R16.3). */
export interface CalibrationApplyRequest {
  title_id: string;
}

/** The outcome of a calibration-apply request (R12.3, R12.5, R16.4). */
export interface CalibrationApplyResponse {
  /** True when MAPE exceeded the threshold and a new version was forked (R12.3). */
  adjustment_required: boolean;
  /** Backend serializes Decimal as a JSON string; the UI coerces defensively. */
  mape: number | string | null;
  /** The id of the newly activated model version when adjustment occurred. */
  new_model_version_id: string | null;
  /**
   * Applied weight offsets keyed by weight name, shown on success (R16.4).
   * Values are Decimal, serialized by the backend as JSON strings.
   */
  offsets: Record<string, number | string> | null;
}

/** Scenario multipliers for the stateless what-if recompute. */
/** Direct input overrides for the What-If Explorer (absent => Baseline). */
export interface ScenarioInputOverrides {
  cost_usd?: number;
  projected_viewing_hours?: number;
  churn_reduction_pct?: number;
  ltv?: number;
  churn_reduction_value?: number;
  cpm?: number;
  ad_impressions?: number;
  watch_time_elasticity?: number;
}

/** Direct threshold overrides for the What-If Explorer (absent => model constant). */
export interface ScenarioThresholdOverrides {
  cpvh_ceiling_override?: number;
  ltv_hurdle_override?: number;
  churn_hurdle_override?: number;
  payback_max_months_override?: number;
}

export interface WhatIfRequest {
  cost_multiplier: number;
  viewership_multiplier: number;
  churn_multiplier?: number;
  input_overrides?: ScenarioInputOverrides;
  threshold_overrides?: ScenarioThresholdOverrides;
}

/** The Baseline comparison block returned by the What-If endpoint. */
export interface BaselineSummary {
  recommendation_status: string | null;
  calculated_cpvh: number | string | null;
  ltv_to_cost_multiple: number | string | null;
  churn_reduction_pct: number | string | null;
  payback_horizon_months: number | null;
  ltv_subscription_value: number | string | null;
  ltv_advertising_value: number | string | null;
  explanation: Explanation | null;
  /** Effective Baseline input values (keys mirror ScenarioInputOverrides). */
  inputs?: Partial<Record<keyof ScenarioInputOverrides, number | string | null>> | null;
}

/** The What-If Explorer response: the Scenario scorecard + Baseline + ceiling. */
export interface WhatIfResponse extends ValuationScorecard {
  baseline: BaselineSummary;
  negotiation_ceiling_usd: number | string | null;
}

/** Inclusive slider bounds for what-if multipliers (include 1.0). */
export const MULTIPLIER_BOUNDS = { min: 0.5, max: 2.0 } as const;

/** A plain-language negotiation lever keyed to a breached guardrail (R3). */
export interface CounterProposalLever {
  name: string;
  correctable: boolean | null;
  message: string;
}

/** LTV-to-Cost numerator decomposition (R6). Decimals arrive as JSON strings. */
export interface LtvAttribution {
  subscription_value: number | string | null;
  advertising_value: number | string | null;
  total_modeled_value: number | string | null;
  normalized_cost_usd: number | string | null;
  multiple: number | string | null;
}

/** Absolute churn-cohort figures (R8); `derived` flags a modeled figure. */
export interface ChurnCohort {
  churn_reduction_pct: number | string | null;
  modeled_cohort_size: number | string | null;
  retained_subscribers: number | string | null;
  derived: boolean;
}

/**
 * Resolves a title to its latest decision (financial projection) id, which the
 * sign-off / finalization endpoints key on (R20.5).
 */
export interface TitleDecision {
  title_id: string;
  decision_id: string;
}

/**
 * One nearest-neighbour title in the Top-3 comps surface (R2.6). A comp is the
 * result of a title-to-title Narrative_DNA cosine-similarity lookup;
 * `recommendation_status` is null when the neighbour has no computed valuation.
 */
export interface TitleComp {
  title_id: string;
  title_name: string;
  genre_tag: string | null;
  recommendation_status: string | null;
  cosine_similarity: number;
}

/**
 * GET /valuation/{titleId}/comps payload (R2.6). `found` is false when the
 * query title has no stored embedding, in which case `comps` is empty.
 */
export interface ComparableTitles {
  title_id: string;
  found: boolean;
  comps: TitleComp[];
}

/**
 * Cached market telemetry for a genre/territory pair (R13.3). `found` is false
 * when the pair has never been polled; `source_available` is false when the
 * most recent poll failed and the indices are retained-but-stale (R13.4).
 */
export interface MarketTelemetry {
  genre_tag: string;
  territory: string;
  social_sentiment_index: number | string | null;
  chart_velocity_score: number | string | null;
  licensing_inflation_multiplier: number | string | null;
  source_available: boolean;
  found: boolean;
}

/** The human acquisition pipeline stages (deal-stage lifecycle). */
export type DealStage =
  | "SCREENING"
  | "EVALUATED"
  | "IN_NEGOTIATION"
  | "APPROVED"
  | "CLOSED_WON"
  | "CLOSED_LOST"
  | "PASSED";

/**
 * A title's current deal stage and the stages it may advance to next. An empty
 * `allowed_next_stages` means the lifecycle has reached a terminal stage.
 */
export interface DealStageInfo {
  title_id: string;
  deal_stage: DealStage;
  allowed_next_stages: DealStage[];
}

/** Best-effort Asset Studio fields parsed from an uploaded pitch PDF. */
export interface ParsedPitch {
  title_name: string | null;
  synopsis: string | null;
  genre_tag: string | null;
  acquisition_cost_or_budget: number | null;
  native_currency: string | null;
  is_exclusive: boolean | null;
  source_text_preview: string | null;
}

/** 202 response from POST /titles/ingest - a dispatched batch job (R1, R23.2). */
export interface IngestAccepted {
  job_id: string;
  status: JobStatus;
  accepted_count?: number | null;
  rejected_count?: number | null;
  rejections?: { row: number | null; reason: string }[] | null;
}

/** A job's lifecycle status + terminal payload, polled via GET /jobs/{id}. */
export interface JobStatusInfo {
  job_id: string;
  job_type: string;
  status: JobStatus;
  result: Record<string, unknown> | null;
  failure_reason: string | null;
  dead_lettered: boolean;
}

/** One immutable model version in the catalog (R26.1, R26.3). */
export interface ModelVersion {
  model_version_id: string;
  talent_pedigree_weight: number | string;
  narrative_trope_weight: number | string;
  guardrail_params: Record<string, unknown>;
  supersedes_id: string | null;
  is_active: boolean;
  created_at: string | null;
}

/** Request to override a decision's recommendation (R20.2). */
export interface OverrideRequest {
  recommendation_status: RecommendationStatus;
  justification?: string | null;
}

/** The result of an override, echoing the applied status (R20.2). */
export interface OverrideResult {
  decision_id: string;
  previous_status: string | null;
  recommendation_status: string;
}

/** One append-only entry in a subject's audit lineage (R25.1, R25.4). */
export interface AuditEntry {
  audit_id: string;
  subject_id: string;
  actor_id: string | null;
  action: string;
  before_value: Record<string, unknown> | null;
  after_value: Record<string, unknown> | null;
  model_version_id: string | null;
  created_at: string | null;
}

/** The ordered audit lineage for a subject (R25.4). */
export interface Lineage {
  subject_id: string;
  entries: AuditEntry[];
}

/** Confirmation that an approve/reject/sign-off act was recorded (R20.4). */
export interface DecisionActionResult {
  decision_id: string;
  action: string;
  actor_id: string;
  acted_at: string | null;
}

/** Finalization gating report for a decision (R20.5). */
export interface FinalizationStatus {
  decision_id: string;
  /** True when all required sign-offs are recorded (R20.5). */
  can_finalize: boolean;
  /** Roles required to sign off a high-budget GREENLIGHT (R20.3, R20.5). */
  required_roles: string[];
  /** Required roles whose approval is still outstanding (R20.5). */
  outstanding_roles: string[];
  /** Roles that have already approved. */
  approved_roles: string[];
}


// --------------------------------------------------------------------------- //
// Asset Studio: manual single-title ingest + instant valuation
// --------------------------------------------------------------------------- //

/** Request body for POST /titles/quick-evaluate (the Asset Studio form). */
export interface QuickEvaluateRequest {
  title_name: string;
  asset_type: AssetType;
  acquisition_cost_or_budget: number;
  native_currency: string;
  target_territories: string[];
  synopsis: string;
  genre_tag?: string | null;
  projected_viewing_hours?: number | null;
  /** Unit the viewing-hours value is in; the backend normalizes to hours (R16). */
  viewing_hours_unit?: "hours" | "minutes" | "seconds";
  /** OTT content format driving the churn content-format lift (R17). */
  content_format?: string | null;
  talent_pedigree_score?: number | null;
  license_duration_months?: number | null;
  is_exclusive: boolean;
}

/** The real Approval_Workflow gate for a decision (R20.3). */
export interface Governance {
  required: boolean;
  required_roles: string[];
  note: string;
}

/** Radar axes for the metadata profile (0-10). Derived for the instant view. */
export interface MetadataProfile {
  narrative_dna: number | string;
  affective_tone: number | string;
  talent_pedigree: number | string;
  production_scale: number | string;
  cultural_portability: number | string;
}

/** Instant executive scorecard returned by POST /titles/quick-evaluate. */
export interface QuickEvaluateResponse {
  title_id: string;
  title_name: string;
  recommendation_status: RecommendationStatus;
  calculated_cpvh: number | string | null;
  ltv_to_cost_multiple: number | string | null;
  churn_reduction_pct: number | string | null;
  payback_horizon_months: number | null;
  normalized_cost_usd: number | string | null;
  /** Derived renegotiation guidance, not a persisted engine output. */
  target_purchase_ceiling_usd: number | string | null;
  implied_discount_pct?: number | string | null;
  counter_proposal_levers?: CounterProposalLever[];
  ltv_attribution?: LtvAttribution | null;
  churn_cohort?: ChurnCohort | null;
  explanation: Explanation;
  governance: Governance;
  metadata_profile: MetadataProfile;
}


// --------------------------------------------------------------------------- //
// Data Chat Assistant (read-only, grounded chat over data + how-to knowledge)
// --------------------------------------------------------------------------- //

/** One prior turn in the client-maintained conversation history. */
export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

/** Request body for POST /api/v1/chat. */
export interface ChatRequest {
  message: string;
  title_id?: string | null;
  history?: ChatTurn[];
}

/** Response from POST /api/v1/chat: the answer plus its grounding sources. */
export interface ChatResponse {
  answer: string;
  sources: string[];
  /** Suggested next questions the UI renders as one-click chips. */
  follow_ups?: string[];
}
