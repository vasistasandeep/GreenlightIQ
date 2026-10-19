"use client";

/**
 * WhatIfExplorer - the read-only deal-modeling sandbox (whatif-explore-inputs-guardrails).
 *
 * Lets a user directly set deal anchors, SVOD/AVOD revenue drivers, the churn %,
 * and the four guardrail thresholds, and see the verdict recompute live
 * Baseline-vs-Scenario. Persists nothing. State is encoded sparsely in the URL
 * (Scenario_Link). Excluded from the Greenlight Memo via `no-print`.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { api } from "@/lib/api-client";
import type { WhatIfResponse } from "@/lib/types";
import { RecommendationBadge, recommendationLabel } from "@/components/recommendation-badge";
import { formatMultiple, formatNumber, formatPercent, formatUsd, guardrailLabel, toNumber } from "./format";

const DEBOUNCE_MS = 400;

type NumMap = Record<string, number>;

/** Editable fields: key, label, group, formatter, and plain-English help. */
const INPUT_FIELDS = [
  { key: "cost_usd", label: "Acquisition cost (USD)", group: "Deal anchors", fmt: formatUsd,
    help: "What you pay for the title. Lowering it improves Cost-per-Viewing-Hour and the LTV-to-Cost multiple - the usual lever to turn a NEGOTIATE HARD into a GREENLIGHT." },
  { key: "projected_viewing_hours", label: "Projected viewing hours", group: "Deal anchors", fmt: (v: number) => formatNumber(v, 0),
    help: "Total hours audiences are expected to watch. More hours lower CPVH (cost spread over more viewing) and tend to help the verdict." },
  { key: "churn_reduction_pct", label: "Churn reduction (%)", group: "Deal anchors", fmt: (v: number) => formatPercent(v),
    help: "How much the title cuts monthly subscriber cancellations. It must clear the churn hurdle (default 1.5%). A churn breach is non-correctable - no price fixes it - so this is often the make-or-break driver." },
  { key: "ltv", label: "LTV (USD)", group: "Revenue drivers", fmt: formatUsd,
    help: "Lifetime value of a subscriber the title helps retain (SVOD side). Higher LTV raises the LTV-to-Cost multiple toward its floor." },
  { key: "churn_reduction_value", label: "Churn value / sub (USD)", group: "Revenue drivers", fmt: formatUsd,
    help: "Dollar value saved per retained subscriber. It multiplies with LTV to form the subscription (SVOD) share of modeled value." },
  { key: "cpm", label: "CPM (USD / 1k)", group: "Revenue drivers", fmt: formatUsd,
    help: "Ad revenue per 1,000 impressions (AVOD side). Higher CPM raises the advertising value and the LTV-to-Cost multiple." },
  { key: "ad_impressions", label: "Ad impressions", group: "Revenue drivers", fmt: (v: number) => formatNumber(v, 0),
    help: "Projected ad impressions. With CPM and elasticity, drives the advertising (AVOD) share of modeled value." },
  { key: "watch_time_elasticity", label: "Watch-time elasticity", group: "Revenue drivers", fmt: (v: number) => formatNumber(v, 2),
    help: "How strongly watch-time converts into ad yield. Higher elasticity amplifies the AVOD contribution to the LTV-to-Cost multiple." },
] as const;

const THRESHOLD_FIELDS = [
  { key: "ltv_hurdle_override", label: "LTV-to-Cost floor", group: "Guardrail thresholds", fmt: formatMultiple,
    help: "The minimum LTV-to-Cost multiple a deal must clear (standard 3.2). Lowering it is easier to pass; raising it is stricter. Exploration only - the saved yardstick never changes." },
  { key: "churn_hurdle_override", label: "Churn hurdle (%)", group: "Guardrail thresholds", fmt: (v: number) => formatPercent(v),
    help: "The minimum churn reduction a title must deliver (standard 1.5%). Relax it and a borderline title passes churn; tighten it and more titles breach." },
  { key: "cpvh_ceiling_override", label: "CPVH ceiling (USD/hr)", group: "Guardrail thresholds", fmt: (v: number) => formatNumber(v, 2),
    help: "The maximum allowed Cost-per-Viewing-Hour (standard 0.18 premium / 0.05 library). Raise it and an expensive title passes CPVH." },
  { key: "payback_max_months_override", label: "Payback max (months)", group: "Guardrail thresholds", fmt: (v: number) => `${v} mo`,
    help: "The longest acceptable payback horizon (standard 12 months). Extend it to tolerate slower break-even; shorten it to be stricter." },
] as const;

const INPUT_KEYS = INPUT_FIELDS.map((f) => f.key) as readonly string[];
const THRESHOLD_KEYS = THRESHOLD_FIELDS.map((f) => f.key) as readonly string[];
const ALL_KEYS = [...INPUT_KEYS, ...THRESHOLD_KEYS, "cost_multiplier", "viewership_multiplier", "churn_multiplier"];

/** Accessible info tooltip: a focusable "i" that reveals help on hover/focus. */
function InfoTip({ text }: { text: string }) {
  return (
    <span className="group/tip relative inline-flex">
      <button
        type="button"
        className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-slate-600 text-[10px] font-semibold text-slate-400 hover:border-emerald-500 hover:text-emerald-300 focus:outline-none focus-visible:ring-1 focus-visible:ring-emerald-400"
        aria-label={text}
      >
        i
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 w-56 -translate-x-1/2 rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-left text-[11px] leading-snug text-slate-200 opacity-0 shadow-xl transition-opacity duration-150 group-hover/tip:opacity-100 group-focus-within/tip:opacity-100"
      >
        {text}
      </span>
    </span>
  );
}

export interface WhatIfExplorerProps {
  titleId: string;
}

export function WhatIfExplorer({ titleId }: WhatIfExplorerProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Hydrate overrides sparsely from the URL (discard malformed/out-of-range).
  const initial = useMemo<NumMap>(() => {
    const out: NumMap = {};
    for (const key of ALL_KEYS) {
      const raw = searchParams.get(key);
      if (raw === null) continue;
      const n = Number(raw);
      if (Number.isFinite(n)) out[key] = n;
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [values, setValues] = useState<NumMap>(initial);
  const [resp, setResp] = useState<WhatIfResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  // Sync the active overrides into the URL (sparse), debounced.
  useEffect(() => {
    const params = new URLSearchParams(searchParams.toString());
    for (const key of ALL_KEYS) params.delete(key);
    for (const [k, v] of Object.entries(values)) params.set(k, String(v));
    params.set("tab", "what-if");
    const qs = params.toString();
    router.replace(`/titles/${titleId}?${qs}`, { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values, titleId]);

  // Recompute on change (debounced, stale-guarded).
  useEffect(() => {
    const id = ++requestId.current;
    const timer = setTimeout(async () => {
      setLoading(true);
      setError(null);
      const input_overrides: NumMap = {};
      const threshold_overrides: NumMap = {};
      for (const k of INPUT_KEYS) if (k in values) input_overrides[k] = values[k];
      for (const k of THRESHOLD_KEYS) if (k in values) threshold_overrides[k] = values[k];
      try {
        const result = await api.whatIf(titleId, {
          cost_multiplier: values.cost_multiplier ?? 1,
          viewership_multiplier: values.viewership_multiplier ?? 1,
          churn_multiplier: values.churn_multiplier ?? 1,
          input_overrides: Object.keys(input_overrides).length ? input_overrides : undefined,
          threshold_overrides: Object.keys(threshold_overrides).length ? threshold_overrides : undefined,
        });
        if (id === requestId.current) setResp(result);
      } catch {
        if (id === requestId.current) setError("Could not compute this scenario. Please try again.");
      } finally {
        if (id === requestId.current) setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [titleId, values]);

  const setField = useCallback((key: string, raw: string) => {
    setValues((prev) => {
      const next = { ...prev };
      if (raw.trim() === "") delete next[key];
      else {
        const n = Number(raw);
        if (Number.isFinite(n)) next[key] = n;
      }
      return next;
    });
  }, []);

  const resetField = useCallback((key: string) => {
    setValues((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const resetAll = useCallback(() => setValues({}), []);

  const copyLink = useCallback(() => {
    if (typeof window !== "undefined") void navigator.clipboard?.writeText(window.location.href);
  }, []);

  const applyPreset = useCallback(
    (preset: "bear" | "bull" | "target") => {
      const b = resp?.baseline?.inputs ?? {};
      const bn = (k: string): number | null => toNumber((b as Record<string, number | string | null>)[k]);
      const round2 = (n: number) => Math.round(n * 100) / 100;

      if (preset === "target") {
        const ceiling = toNumber(resp?.negotiation_ceiling_usd);
        if (ceiling !== null) setValues({ cost_usd: round2(ceiling) });
        return;
      }

      // Bear / Bull apply concrete deltas to the Baseline driver values so the
      // fields fill with real numbers the user can see and tweak.
      const f = preset === "bear" ? { view: 0.75, cpm: 0.8, churn: 0.85 } : { view: 1.3, cpm: 1.25, churn: 1.2 };
      const next: NumMap = {};
      const hours = bn("projected_viewing_hours");
      const imps = bn("ad_impressions");
      const cpm = bn("cpm");
      const churnPct = bn("churn_reduction_pct");
      // Viewership scales both viewing hours and ad impressions.
      if (hours !== null) next.projected_viewing_hours = Math.round(hours * f.view);
      if (imps !== null) next.ad_impressions = Math.round(imps * f.view);
      if (cpm !== null) next.cpm = round2(cpm * f.cpm);
      if (churnPct !== null) next.churn_reduction_pct = round2(churnPct * f.churn);
      setValues(next);
    },
    [resp],
  );

  const baseline = resp?.baseline ?? null;
  const scenarioRec = resp?.recommendation_status ?? null;
  const baselineRec = baseline?.recommendation_status ?? null;
  const verdictMoved = resp && baselineRec && scenarioRec && baselineRec !== scenarioRec;

  const ceiling = toNumber(resp?.negotiation_ceiling_usd);
  const targetDisabled = ceiling === null || ceiling <= 0 || baselineRec === "GREENLIGHT";
  const targetTooltip =
    baselineRec === "GREENLIGHT"
      ? "Already GREENLIGHT - no price change needed"
      : ceiling === null || ceiling <= 0
        ? "Target deal unavailable: a structural churn breach cannot be resolved by price"
        : "Set cost to the negotiation ceiling";

  const scenarioChecks = useMemo(() => {
    const e = resp?.explanation;
    return e && typeof e === "object" ? (e.checks ?? []) : [];
  }, [resp]);
  const baselineChecks = useMemo(() => {
    const e = baseline?.explanation;
    return e && typeof e === "object" ? (e.checks ?? []) : [];
  }, [baseline]);

  const baselineInputs = (baseline?.inputs ?? {}) as Record<string, number | string | null>;
  function baselinePlaceholder(key: string, fmt: (v: number) => string): string {
    // Thresholds have no baseline input value; show the model default label.
    if (key in baselineInputs) {
      const n = toNumber(baselineInputs[key]);
      if (n !== null) return fmt(n);
    }
    return "baseline";
  }

  return (
    <section aria-labelledby="whatif-heading" className="no-print space-y-5">
      {/* Sandbox banner */}
      <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-sm text-amber-200">
        <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M12 9v4M12 17h.01M10.3 3.9l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3L13.7 4a2 2 0 0 0-3.4 0z" strokeLinecap="round" strokeLinejoin="round"/></svg>
        <span><strong>Exploration sandbox.</strong> Nothing here is saved - the official scorecard is unchanged.</span>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Controls */}
        <div className="space-y-5">
          <div className="flex items-center justify-between">
            <div>
              <h2 id="whatif-heading" className="text-lg font-semibold text-slate-100">What-If Explorer</h2>
              <p className="mt-0.5 text-xs text-slate-500">Set any value to see how the verdict would change. Hover the <span className="font-semibold">i</span> on a label for what it means and how it moves the result.</p>
            </div>
            <div className="flex gap-2">
              <button type="button" onClick={resetAll} className="rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800">Reset all</button>
              <button type="button" onClick={copyLink} className="rounded-md border border-slate-700 px-2.5 py-1 text-xs text-emerald-300 hover:bg-slate-800">Copy scenario link</button>
            </div>
          </div>

          {/* Presets */}
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => applyPreset("bear")} className="rounded-full border border-slate-700 bg-slate-800/60 px-3 py-1 text-xs text-slate-200 hover:bg-slate-800">Bear case</button>
            <button type="button" onClick={() => applyPreset("bull")} className="rounded-full border border-slate-700 bg-slate-800/60 px-3 py-1 text-xs text-slate-200 hover:bg-slate-800">Bull case</button>
            <button type="button" onClick={() => applyPreset("target")} disabled={targetDisabled} title={targetTooltip} className="rounded-full border border-emerald-600/40 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-200 hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40">Target deal</button>
          </div>

          {[...INPUT_FIELDS, ...THRESHOLD_FIELDS].reduce<Record<string, typeof INPUT_FIELDS[number][]>>((acc, f) => {
            (acc[f.group] ??= []).push(f as never);
            return acc;
          }, {}) && (
            <div className="space-y-4">
              {["Deal anchors", "Revenue drivers", "Guardrail thresholds"].map((group) => (
                <div key={group}>
                  <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">{group}</p>
                  <div className="space-y-2">
                    {[...INPUT_FIELDS, ...THRESHOLD_FIELDS].filter((f) => f.group === group).map((f) => (
                      <div key={f.key} className="flex items-center gap-2">
                        <span className="flex flex-1 items-center gap-1.5 text-sm text-slate-300">
                          <span id={`wf-lbl-${f.key}`}>{f.label}</span>
                          <InfoTip text={(f as { help: string }).help} />
                        </span>
                        <input
                          id={`wf-${f.key}`}
                          aria-labelledby={`wf-lbl-${f.key}`}
                          type="number"
                          inputMode="decimal"
                          value={f.key in values ? String(values[f.key]) : ""}
                          onChange={(e) => setField(f.key, e.target.value)}
                          placeholder={baselinePlaceholder(f.key, (f as { fmt: (v: number) => string }).fmt)}
                          className="w-32 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-right text-sm text-slate-100 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none"
                        />
                        <button type="button" onClick={() => resetField(f.key)} aria-label={`Reset ${f.label}`} className="text-slate-500 hover:text-slate-300" title="Reset to baseline">&times;</button>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Live verdict */}
        <div className="space-y-4 rounded-xl border border-slate-800 bg-slate-900/60 p-5">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-400">Scenario verdict</span>
            {loading ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-emerald-500 border-t-transparent" /> : null}
          </div>

          {error ? <p role="alert" className="text-sm text-rose-400">{error}</p> : null}

          {resp ? (
            <>
              <div className="flex items-center gap-3">
                <RecommendationBadge status={scenarioRec as never} />
                {verdictMoved ? (
                  <span className="text-xs text-amber-300">
                    was {recommendationLabel(baselineRec as never)} &rarr; now {recommendationLabel(scenarioRec as never)}
                  </span>
                ) : (
                  <span className="text-xs text-slate-500">same as baseline</span>
                )}
              </div>

              <div aria-live="polite" className="space-y-1.5 text-sm">
                {scenarioChecks.map((c, i) => {
                  const b = baselineChecks.find((x) => x.name === c.name);
                  return (
                    <div key={c.name ?? i} className="flex items-center justify-between gap-2 border-b border-slate-800 py-1.5 last:border-0">
                      <span className="text-slate-300">{guardrailLabel(c.name)}</span>
                      <span className="flex items-center gap-2 tabular-nums">
                        {b ? <span className="text-slate-500">{formatNumber(b.computed_value)}</span> : null}
                        <span aria-hidden>&rarr;</span>
                        <span className={c.breached ? "text-rose-400" : "text-emerald-400"}>{formatNumber(c.computed_value)}</span>
                        <span className={"rounded px-1.5 py-0.5 text-[10px] font-semibold " + (c.breached ? "bg-rose-500/15 text-rose-300" : "bg-emerald-500/15 text-emerald-300")}>
                          {c.breached ? "BREACH" : "PASS"}
                        </span>
                      </span>
                    </div>
                  );
                })}
              </div>

              <div className="grid grid-cols-2 gap-2 rounded-lg bg-slate-800/40 p-3 text-xs">
                <div><span className="text-slate-500">SVOD (subscription)</span><div className="tabular-nums text-slate-200">{formatUsd(resp.ltv_attribution?.subscription_value)}</div></div>
                <div><span className="text-slate-500">AVOD (advertising)</span><div className="tabular-nums text-slate-200">{formatUsd(resp.ltv_attribution?.advertising_value)}</div></div>
              </div>
            </>
          ) : (
            <p className="text-sm text-slate-400">
              {loading ? "Computing scenario..." : "Edit a value on the left to explore how the verdict would change, or try a preset."}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}