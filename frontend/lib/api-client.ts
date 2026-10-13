/**
 * Typed API client for the CineROI AI backend.
 *
 * A thin fetch wrapper that targets the FastAPI service under `/api/v1`, carries
 * the session credential as an `Authorization: Bearer` header (R19.2, R19.3), and
 * normalizes the backend error envelope `{ error_code, message, details }` into a
 * typed {@link ApiError}. Expired / revoked sessions (R19.4, R19.6) are detected and
 * the ambient session token is cleared so the UI can redirect to login.
 */

import { clearSessionToken, getSessionToken } from "./session";
import type {
  ApiErrorEnvelope,
  BacktestAuditRequest,
  BacktestAuditResponse,
  CalibrationApplyRequest,
  CalibrationApplyResponse,
  DashboardSummary,
  DecisionActionResult,
  FinalizationStatus,
  QuickEvaluateRequest,
  QuickEvaluateResponse,
  SessionInfo,
  Lineage,
  ModelVersion,
  OverrideRequest,
  OverrideResult,
  TitleDecision,
  WhatIfRequest,
  ValuationScorecard,
} from "./types";

/**
 * Resolve the backend base URL for a request.
 *
 * - **Browser:** use SAME-ORIGIN by default (empty base), so calls go to
 *   `/api/v1/...` on whatever host served the page. Next.js rewrites proxy
 *   `/api/*` and `/health` to the backend (see next.config.mjs). This makes the
 *   app work behind a single public URL (a tunnel, a load balancer, or any
 *   host) with no hardcoded localhost. An explicit `NEXT_PUBLIC_API_BASE_URL`
 *   still overrides it when a separate API origin is desired.
 * - **Server (RSC):** reach the backend directly over the internal network via
 *   `API_BASE_URL_INTERNAL` (e.g. http://backend:8000), falling back to
 *   localhost for local dev outside Docker.
 */
function resolveApiBaseUrl(): string {
  const isServer = typeof window === "undefined";
  if (isServer) {
    return (
      process.env.API_BASE_URL_INTERNAL ??
      process.env.NEXT_PUBLIC_API_BASE_URL ??
      "http://localhost:8000"
    );
  }
  // Browser: prefer an explicit public base, else same-origin ("" -> /api/v1).
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
}

const API_BASE_URL = resolveApiBaseUrl();

const API_V1 = "/api/v1";

/**
 * Error thrown when the backend returns a non-2xx response.
 *
 * Carries the parsed error envelope when the backend supplied one, plus the HTTP
 * status so callers can branch (e.g. render the auth screen on `isAuthError`).
 */
export class ApiError extends Error {
  readonly status: number;
  readonly envelope?: ApiErrorEnvelope;

  constructor(status: number, message: string, envelope?: ApiErrorEnvelope) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.envelope = envelope;
  }

  /** Backend error code (e.g. `"UNAUTHENTICATED"`), when the envelope carried one. */
  get errorCode(): string | undefined {
    return this.envelope?.error_code;
  }

  /** True for authentication failures (missing / expired / revoked credential Ã¢â‚¬â€ R19.3, R19.6). */
  get isAuthError(): boolean {
    return this.status === 401;
  }
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  /**
   * Explicit session token forwarded as a bearer credential (R19.2).
   * When omitted, the ambient browser session token is used. Server Components
   * must supply this explicitly since they cannot read the browser session.
   */
  token?: string;
  /** Set to `true` to send the request without any Authorization header. */
  anonymous?: boolean;
  /** JSON-serializable request body; serialized automatically. */
  body?: unknown;
}

/**
 * Perform a typed request against the backend, returning parsed JSON.
 *
 * Attaches the session credential, serializes a JSON body, and throws
 * {@link ApiError} on non-2xx responses, surfacing the error envelope. On a 401 the
 * ambient session token is cleared so the app can re-authenticate (R19.4, R19.6).
 */
export async function apiFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { token, anonymous, headers, body, ...rest } = options;

  const credential = anonymous ? undefined : (token ?? getSessionToken() ?? undefined);

  const response = await fetch(`${API_BASE_URL}${API_V1}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(credential ? { Authorization: `Bearer ${credential}` } : {}),
      ...headers,
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });

  if (!response.ok) {
    let envelope: ApiErrorEnvelope | undefined;
    try {
      envelope = (await response.json()) as ApiErrorEnvelope;
    } catch {
      envelope = undefined;
    }

    // A rejected session (missing / expired / revoked) invalidates the ambient
    // credential; drop it so the UI falls back to login (R19.3, R19.4, R19.6).
    if (response.status === 401 && !anonymous) {
      clearSessionToken();
    }

    throw new ApiError(
      response.status,
      envelope?.message ?? `Request failed with status ${response.status}`,
      envelope,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

/** Typed endpoint helpers. Expanded as routers land in task 16. */
export const api = {
  /** POST /api/v1/auth/login Ã¢â‚¬â€ exchange SSO assertion for a session (R19.1, R19.2). */
  login(assertion: unknown, options?: RequestOptions) {
    return apiFetch<SessionInfo>("/auth/login", {
      method: "POST",
      anonymous: true,
      body: assertion,
      ...options,
    });
  },

  /** POST /api/v1/auth/logout Ã¢â‚¬â€ end the current session (R19). */
  logout(options?: RequestOptions) {
    return apiFetch<void>("/auth/logout", { method: "POST", ...options });
  },

  /** GET /api/v1/auth/session Ã¢â‚¬â€ current session context, or 401 if invalid (R19.3). */
  getSession(options?: RequestOptions) {
    return apiFetch<SessionInfo>("/auth/session", { method: "GET", ...options });
  },

  /** GET /api/v1/valuation/{titleId} Ã¢â‚¬â€ full financial scorecard (R10). */
  getValuation(titleId: string, options?: RequestOptions) {
    return apiFetch<ValuationScorecard>(`/valuation/${titleId}`, {
      method: "GET",
      ...options,
    });
  },
  /**
   * GET /api/v1/valuation/{titleId}/decision - resolve a title to its latest
   * decision (financial projection) id, which the sign-off / finalization
   * endpoints key on (R20.5).
   */
  getTitleDecision(titleId: string, options?: RequestOptions) {
    return apiFetch<TitleDecision>(`/valuation/${titleId}/decision`, {
      method: "GET",
      ...options,
    });
  },

  /**
   * POST /api/v1/valuation/{titleId}/what-if - recompute a scorecard under
   * scenario multipliers WITHOUT persisting (read-only sensitivity analysis).
   */
  whatIf(titleId: string, body: WhatIfRequest, options?: RequestOptions) {
    return apiFetch<ValuationScorecard>(`/valuation/${titleId}/what-if`, {
      method: "POST",
      body,
      ...options,
    });
  },

  /**
   * POST /api/v1/decisions/{decisionId}/override - override a decision's
   * recommendation with a mandatory justification, recorded in the audit log
   * (R20.2). Gated to decision-making roles by the backend.
   */
  overrideDecision(decisionId: string, body: OverrideRequest, options?: RequestOptions) {
    return apiFetch<OverrideResult>(`/decisions/${decisionId}/override`, {
      method: "POST",
      body,
      ...options,
    });
  },

  /**
   * GET /api/v1/audit/lineage/{subjectId} - the ordered, append-only audit
   * lineage for a decision or title (R25.4).
   */
  getLineage(subjectId: string, options?: RequestOptions) {
    return apiFetch<Lineage>(`/audit/lineage/${subjectId}`, {
      method: "GET",
      ...options,
    });
  },

  /** GET /api/v1/models/versions - the immutable model-version catalog (R26.3). */
  listModelVersions(options?: RequestOptions) {
    return apiFetch<ModelVersion[]>("/models/versions", {
      method: "GET",
      ...options,
    });
  },

  /**
   * POST /api/v1/models/versions/{id}/activate - roll back to a prior model
   * version by making it active (R26.3). Gated to CALIBRATE roles server-side.
   */
  activateModelVersion(modelVersionId: string, options?: RequestOptions) {
    return apiFetch<ModelVersion>(`/models/versions/${modelVersionId}/activate`, {
      method: "POST",
      ...options,
    });
  },

  /**
   * GET /api/v1/dashboard/summary Ã¢â‚¬â€ the Executive Command Dashboard payload:
   * KPI header figures and the master asset grid rows (R14.1, R14.2).
   */
  getDashboardSummary(options?: RequestOptions) {
    return apiFetch<DashboardSummary>("/dashboard/summary", {
      method: "GET",
      ...options,
    });
  },

  /**
   * POST /api/v1/titles/quick-evaluate - create a single title from manual input
   * and return the instant executive scorecard (recommendation, guardrail
   * metrics, explanation, governance, and metadata profile).
   */
  quickEvaluate(request: QuickEvaluateRequest, options?: RequestOptions) {
    return apiFetch<QuickEvaluateResponse>("/titles/quick-evaluate", {
      method: "POST",
      body: request,
      ...options,
    });
  },

  /**
   * POST /api/v1/backtest/audit Ã¢â‚¬â€ persist ground truth and return the audit
   * scorecard comparing predicted vs actual with the computed MAPE (R11.1, R11.6).
   */
  backtestAudit(request: BacktestAuditRequest, options?: RequestOptions) {
    return apiFetch<BacktestAuditResponse>("/backtest/audit", {
      method: "POST",
      body: request,
      ...options,
    });
  },

  /**
   * POST /api/v1/calibration/apply Ã¢â‚¬â€ request auto-tuning offsets from a
   * historical title's MAPE; forks a new model version when MAPE is too high and
   * reports the applied weight offsets (R12.3, R16.3, R16.4).
   */
  applyCalibration(request: CalibrationApplyRequest, options?: RequestOptions) {
    return apiFetch<CalibrationApplyResponse>("/calibration/apply", {
      method: "POST",
      body: request,
      ...options,
    });
  },

  /**
   * GET /api/v1/decisions/{decisionId}/finalization Ã¢â‚¬â€ the finalization gate and
   * outstanding required approvals for a high-budget decision (R20.5).
   */
  getFinalization(decisionId: string, options?: RequestOptions) {
    return apiFetch<FinalizationStatus>(`/decisions/${decisionId}/finalization`, {
      method: "GET",
      ...options,
    });
  },

  /**
   * POST /api/v1/decisions/{decisionId}/demo-sign-off - DEV/DEMO ONLY. Record an
   * APPROVE on behalf of a seeded executive role so a single demo session can
   * clear a two-role (CCO + CFO) sign-off gate end-to-end (R20.4, R20.5).
   */
  demoSignOff(decisionId: string, role: string, options?: RequestOptions) {
    return apiFetch<DecisionActionResult>(
      `/decisions/${decisionId}/demo-sign-off`,
      { method: "POST", body: { role }, ...options },
    );
  },
};
