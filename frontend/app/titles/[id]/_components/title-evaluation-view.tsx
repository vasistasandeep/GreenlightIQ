"use client";

/**
 * TitleEvaluationView (R15, R30.4).
 *
 * Client component that fetches the full valuation scorecard for a title through
 * the typed API client (carrying the ambient browser session credential) and
 * composes the deep-dive panels:
 *   - {@link MetadataRadar} - Narrative DNA / Affective Tone / Talent Pedigree /
 *     Production Scale radar (R15.1).
 *   - {@link FinancialAccordion} - CPVH ceiling checks, churn mitigation curve,
 *     payback timeline bar chart (R15.2).
 *   - {@link NegotiationLeverage} - contractual safeguards / levers (R15.3).
 *   - {@link ExplanationPanel} - passed/breached checks, computed vs threshold,
 *     shortfall, dominant factor (R30.4).
 *
 * A `404 TITLE_NOT_FOUND` is treated as the expected pending-valuation state
 * (R15.4); other failures render an error with a retry affordance.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api-client";
import type { ValuationScorecard } from "@/lib/types";
import { RecommendationBadge } from "@/components/recommendation-badge";
import { GreenlightMemo } from "./greenlight-memo";
import { SensitivityPanel } from "./sensitivity-panel";
import { AppShell } from "@/components/layout/top-nav";

import { ExplanationPanel } from "./explanation-panel";
import { FinancialAccordion } from "./financial-accordion";
import { MetadataRadar } from "./metadata-radar";
import { NegotiationLeverage } from "./negotiation-leverage";
import { PendingValuationState } from "./pending-state";

type LoadState =
  | { status: "loading" }
  | { status: "pending" }
  | { status: "error"; message: string }
  | { status: "ready"; scorecard: ValuationScorecard };

export interface TitleEvaluationViewProps {
  titleId: string;
}

export function TitleEvaluationView({ titleId }: TitleEvaluationViewProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const scorecard = await api.getValuation(titleId);
      // A title with no computed projection has a null recommendation; the
      // backend returns 404 for that case, but guard defensively here too.
      if (scorecard.recommendation_status === null) {
        setState({ status: "pending" });
        return;
      }
      setState({ status: "ready", scorecard });
    } catch (err) {
      // 404 TITLE_NOT_FOUND is the expected "no completed valuation" case (R15.4).
      if (err instanceof ApiError && err.status === 404) {
        setState({ status: "pending" });
        return;
      }
      const message =
        err instanceof Error ? err.message : "Failed to load the valuation.";
      setState({ status: "error", message });
    }
  }, [titleId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <AppShell>
      <Link
        href="/dashboard"
        className="mb-6 inline-flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200"
      >
        &larr; Back to dashboard
      </Link>

      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Title Evaluation</h1>
          <p className="text-sm text-slate-400">Title {titleId}</p>
        </div>
        {state.status === "ready" ? (
          <div className="flex items-center gap-3">
            <RecommendationBadge
              status={state.scorecard.recommendation_status}
              className="text-sm"
            />
            <button
              type="button"
              onClick={() => window.print()}
              className="no-print inline-flex items-center rounded-md border border-slate-700 px-3 py-1.5 text-sm font-medium text-slate-200 hover:bg-slate-800"
            >
              Export Greenlight Memo (PDF)
            </button>
          </div>
        ) : null}
      </header>

      {state.status === "loading" ? (
        <div
          role="status"
          className="rounded-lg border border-slate-800 bg-slate-900/60 p-10 text-center text-sm text-slate-400"
        >
          Loading valuation...
        </div>
      ) : null}

      {state.status === "pending" ? (
        <PendingValuationState titleId={titleId} />
      ) : null}

      {state.status === "error" ? (
        <div
          role="alert"
          className="rounded-lg border border-red-900/60 bg-red-950/40 p-6 text-center"
        >
          <p className="font-medium text-red-300">Could not load this valuation.</p>
          <p className="mt-1 text-sm text-red-400">{state.message}</p>
          <button
            type="button"
            onClick={() => void load()}
            className="mt-4 inline-flex items-center rounded-md border border-red-800 bg-slate-900 px-3 py-1.5 text-sm font-medium text-red-300 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
          >
            Retry
          </button>
        </div>
      ) : null}

      {state.status === "ready" ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <MetadataRadar breakdown={state.scorecard.metadata_breakdown} />
          <NegotiationLeverage scorecard={state.scorecard} />
          <div className="lg:col-span-2">
            <FinancialAccordion scorecard={state.scorecard} />
          </div>
          <div className="lg:col-span-2">
            <ExplanationPanel explanation={state.scorecard.explanation} />
          </div>
          <div className="lg:col-span-2">
            <SensitivityPanel titleId={titleId} />
          </div>
          <GreenlightMemo titleId={titleId} scorecard={state.scorecard} />
        </div>
      ) : null}
    </AppShell>
  );
}