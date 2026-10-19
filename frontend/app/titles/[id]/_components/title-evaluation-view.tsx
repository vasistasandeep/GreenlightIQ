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
import { useSearchParams } from "next/navigation";

import { ApiError, api } from "@/lib/api-client";
import type { ValuationScorecard } from "@/lib/types";
import { RecommendationBadge } from "@/components/recommendation-badge";
import { GreenlightMemo } from "./greenlight-memo";
import { SensitivityPanel } from "./sensitivity-panel";
import { OverridePanel } from "./override-panel";
import { AuditLineage } from "./audit-lineage";
import { AppShell } from "@/components/layout/top-nav";

import { ExplanationPanel } from "./explanation-panel";
import { FinancialAccordion } from "./financial-accordion";
import { MetadataRadar } from "./metadata-radar";
import { ComparableTitlesPanel } from "./comparable-titles";
import { MarketTelemetryCard } from "./market-telemetry-card";
import { DealStageControl } from "./deal-stage-control";
import { NegotiationLeverage } from "./negotiation-leverage";
import { PendingValuationState } from "./pending-state";
import { TitleTabs, type TitleTab } from "./title-tabs";
import { WhatIfExplorer } from "./whatif-explorer";

type LoadState =
  | { status: "loading" }
  | { status: "pending" }
  | { status: "error"; message: string }
  | { status: "ready"; scorecard: ValuationScorecard };

export interface TitleEvaluationViewProps {
  titleId: string;
}

/** A full-width recommendation banner summarizing the verdict in plain words. */
function RecommendationBanner({
  status,
}: {
  status: ValuationScorecard["recommendation_status"];
}) {
  const map = {
    GREENLIGHT: {
      ring: "border-emerald-500/30 bg-emerald-500/10",
      dot: "bg-emerald-400",
      title: "GREENLIGHT",
      line: "All four guardrails pass. Buy it as proposed.",
      text: "text-emerald-300",
    },
    NEGOTIATE_HARD: {
      ring: "border-amber-500/30 bg-amber-500/10",
      dot: "bg-amber-400",
      title: "NEGOTIATE HARD",
      line: "Good title, wrong price. There is a lower price at which it clears - go haggle.",
      text: "text-amber-300",
    },
    PASS: {
      ring: "border-rose-500/30 bg-rose-500/10",
      dot: "bg-rose-400",
      title: "PASS",
      line: "A problem no price can fix. Walk away.",
      text: "text-rose-300",
    },
  } as const;
  const m = status ? map[status] : null;
  if (!m) return null;
  return (
    <div className={`mb-6 flex items-start gap-3 rounded-xl border px-4 py-3.5 ${m.ring}`}>
      <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${m.dot} shadow-[0_0_8px] shadow-current`} aria-hidden />
      <div>
        <p className={`text-sm font-bold tracking-wide ${m.text}`}>{m.title}</p>
        <p className="mt-0.5 text-sm text-slate-300">{m.line}</p>
      </div>
    </div>
  );
}

export function TitleEvaluationView({ titleId }: TitleEvaluationViewProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const searchParams = useSearchParams();
  const activeTab: TitleTab = searchParams.get("tab") === "what-if" ? "what-if" : "scorecard";

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
          <h1 className="text-2xl font-semibold tracking-tight text-slate-50">Title Evaluation</h1>
          <p className="mt-1 inline-flex items-center gap-1.5 text-xs text-slate-500">
            <span className="uppercase tracking-wider">ID</span>
            <code className="rounded bg-slate-800/80 px-1.5 py-0.5 font-mono text-[11px] text-slate-400">
              {titleId.slice(0, 8)}&hellip;{titleId.slice(-4)}
            </code>
          </p>
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
              className="no-print inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-sm font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M6 14h12v8H6z" />
              </svg>
              Export Memo
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
        <>
          <TitleTabs titleId={titleId} active={activeTab} />

          {activeTab === "what-if" ? (
            <WhatIfExplorer titleId={titleId} />
          ) : (
            <>
              <RecommendationBanner status={state.scorecard.recommendation_status} />
              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <div className="lg:col-span-2">
                  <DealStageControl titleId={titleId} />
                </div>
                <MetadataRadar breakdown={state.scorecard.metadata_breakdown} />
                <NegotiationLeverage scorecard={state.scorecard} />
                <div className="lg:col-span-2">
                  <ComparableTitlesPanel titleId={titleId} />
                </div>
                <div className="lg:col-span-2">
                  <MarketTelemetryCard
                    genre={state.scorecard.genre_tag}
                    territory={state.scorecard.primary_territory}
                  />
                </div>
                <div className="lg:col-span-2">
                  <FinancialAccordion scorecard={state.scorecard} />
                </div>
                <div className="lg:col-span-2">
                  <ExplanationPanel explanation={state.scorecard.explanation} />
                </div>
                <div className="lg:col-span-2">
                  <SensitivityPanel titleId={titleId} />
                </div>
                <div className="lg:col-span-2">
                  <OverridePanel
                    titleId={titleId}
                    currentStatus={state.scorecard.recommendation_status}
                    onOverridden={() => void load()}
                  />
                </div>
                <div className="lg:col-span-2">
                  <AuditLineage titleId={titleId} />
                </div>
                <GreenlightMemo titleId={titleId} scorecard={state.scorecard} />
              </div>
            </>
          )}
        </>
      ) : null}
    </AppShell>
  );
}