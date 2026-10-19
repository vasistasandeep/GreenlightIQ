"use client";

/**
 * MarketTelemetryCard (R13.3, R13.4).
 *
 * Surfaces the cached market-telemetry indices for the title's genre + primary
 * territory: social sentiment, chart velocity, and licensing-inflation. These
 * are the signals the Guardrails engine folds into territory-weighted CPM/LTV
 * (R21.3), so showing them here explains *why* a valuation leans the way it does.
 *
 * Loads on mount via GET /market/telemetry. Three states beyond the data view:
 *   - no genre/territory on the title -> nothing to look up (hidden).
 *   - found === false -> the pair has never been polled (empty state).
 *   - source_available === false -> indices are retained-but-stale (R13.4);
 *     shown with a staleness note.
 */

import { useEffect, useState } from "react";

import { api } from "@/lib/api-client";
import type { MarketTelemetry } from "@/lib/types";

type LoadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "absent" }
  | { status: "ready"; telemetry: MarketTelemetry };

export interface MarketTelemetryCardProps {
  genre: string | null | undefined;
  territory: string | null | undefined;
}

/** Coerce a string|number|null index into a number, or null when absent. */
function toNum(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded-md bg-muted/40 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums">{value}</p>
      <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p>
    </div>
  );
}

export function MarketTelemetryCard({ genre, territory }: MarketTelemetryCardProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    if (!genre || !territory) {
      setState({ status: "absent" });
      return;
    }
    let active = true;
    setState({ status: "loading" });
    api
      .getTelemetry(genre, territory)
      .then((telemetry) => {
        if (!active) return;
        setState({ status: "ready", telemetry });
      })
      .catch(() => {
        if (active) setState({ status: "error" });
      });
    return () => {
      active = false;
    };
  }, [genre, territory]);

  // Nothing to look up: no descriptors on the title. Render nothing.
  if (state.status === "absent") {
    return null;
  }

  const sentiment =
    state.status === "ready" ? toNum(state.telemetry.social_sentiment_index) : null;
  const velocity =
    state.status === "ready" ? toNum(state.telemetry.chart_velocity_score) : null;
  const inflation =
    state.status === "ready"
      ? toNum(state.telemetry.licensing_inflation_multiplier)
      : null;

  return (
    <section
      aria-labelledby="telemetry-heading"
      className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 shadow-sm shadow-black/20"
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="telemetry-heading" className="text-lg font-semibold">
          Market telemetry
        </h2>
        {genre && territory ? (
          <span className="text-xs uppercase tracking-wide text-muted-foreground">
            {genre} &middot; {territory}
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        External market signals for this genre and territory, folded into the
        territory-weighted valuation.
      </p>

      <div className="mt-4">
        {state.status === "loading" ? (
          <p className="text-sm text-muted-foreground" role="status">
            Loading telemetry...
          </p>
        ) : null}

        {state.status === "error" ? (
          <p role="alert" className="text-sm font-medium text-red-500">
            Could not load market telemetry.
          </p>
        ) : null}

        {state.status === "ready" && !state.telemetry.found ? (
          <p className="text-sm text-muted-foreground">
            No telemetry has been polled for this genre and territory yet.
          </p>
        ) : null}

        {state.status === "ready" && state.telemetry.found ? (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Metric
                label="Social sentiment"
                value={sentiment === null ? "-" : sentiment.toFixed(2)}
                hint="Audience buzz index (0-1)"
              />
              <Metric
                label="Chart velocity"
                value={velocity === null ? "-" : velocity.toFixed(1)}
                hint="Momentum; lifts LTV weighting"
              />
              <Metric
                label="Licensing inflation"
                value={inflation === null ? "-" : `${inflation.toFixed(3)}x`}
                hint="Ad-inventory cost vs baseline"
              />
            </div>
            {!state.telemetry.source_available ? (
              <p className="mt-3 rounded-md border border-amber-500/40 bg-amber-100/10 px-3 py-2 text-xs text-amber-500">
                The telemetry source was unavailable on the last poll; these
                indices are retained from the previous successful poll and may be
                stale.
              </p>
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  );
}