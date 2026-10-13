"use client";

/**
 * ComparableTitlesPanel (R2.6).
 *
 * The "Top 3 Historical Comps" tile: the three titles whose Narrative_DNA is
 * closest to this one by pgvector cosine similarity. Each comp links through to
 * its own evaluation and carries its recommendation badge, so an analyst can
 * sanity-check a valuation against the most semantically similar precedents.
 *
 * Loads lazily on mount via GET /valuation/{titleId}/comps. A title with no
 * stored embedding (`found === false`) and a title with no neighbours both
 * render a graceful empty state rather than an error.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api-client";
import type { TitleComp } from "@/lib/types";
import {
  RecommendationBadge,
} from "@/components/recommendation-badge";
import type { RecommendationStatus } from "@/lib/types";

type LoadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "empty"; reason: "no-embedding" | "no-neighbours" }
  | { status: "ready"; comps: TitleComp[] };

export interface ComparableTitlesPanelProps {
  titleId: string;
}

/** Render a cosine similarity in [-1, 1] as a 0-100% affinity reading. */
function similarityPercent(cosine: number): string {
  const pct = Math.max(0, Math.min(1, cosine)) * 100;
  return `${pct.toFixed(1)}%`;
}

export function ComparableTitlesPanel({ titleId }: ComparableTitlesPanelProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let active = true;
    async function load() {
      setState({ status: "loading" });
      try {
        const result = await api.getComps(titleId);
        if (!active) return;
        if (!result.found) {
          setState({ status: "empty", reason: "no-embedding" });
          return;
        }
        if (result.comps.length === 0) {
          setState({ status: "empty", reason: "no-neighbours" });
          return;
        }
        setState({ status: "ready", comps: result.comps });
      } catch {
        if (active) setState({ status: "error" });
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [titleId]);

  return (
    <section
      aria-labelledby="comps-heading"
      className="rounded-lg border bg-background p-5 shadow-sm"
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="comps-heading" className="text-lg font-semibold">
          Top 3 historical comps
        </h2>
        <span className="text-xs text-muted-foreground">
          Narrative DNA similarity
        </span>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        The titles most semantically similar to this one, by Narrative_DNA
        cosine similarity.
      </p>

      <div className="mt-4">
        {state.status === "loading" ? (
          <p className="text-sm text-muted-foreground" role="status">
            Finding comparable titles...
          </p>
        ) : null}

        {state.status === "error" ? (
          <p role="alert" className="text-sm font-medium text-red-500">
            Could not load comparable titles.
          </p>
        ) : null}

        {state.status === "empty" ? (
          <p className="text-sm text-muted-foreground">
            {state.reason === "no-embedding"
              ? "This title has no Narrative_DNA embedding yet, so comps cannot be computed."
              : "No other title has a Narrative_DNA embedding to compare against yet."}
          </p>
        ) : null}

        {state.status === "ready" ? (
          <ol className="space-y-2">
            {state.comps.map((comp, index) => (
              <li key={comp.title_id}>
                <Link
                  href={`/titles/${comp.title_id}`}
                  className="flex items-center justify-between gap-3 rounded-md border border-transparent bg-muted/40 px-3 py-2 transition hover:border-slate-700 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
                >
                  <span className="flex min-w-0 items-center gap-3">
                    <span
                      aria-hidden
                      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-800 text-xs font-semibold text-slate-200"
                    >
                      {index + 1}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">
                        {comp.title_name}
                      </span>
                      {comp.genre_tag ? (
                        <span className="block truncate text-xs text-muted-foreground">
                          {comp.genre_tag}
                        </span>
                      ) : null}
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-3">
                    <RecommendationBadge
                      status={
                        comp.recommendation_status as
                          | RecommendationStatus
                          | null
                      }
                    />
                    <span
                      className="w-14 text-right text-sm font-semibold tabular-nums text-slate-200"
                      title={`Cosine similarity ${comp.cosine_similarity.toFixed(4)}`}
                    >
                      {similarityPercent(comp.cosine_similarity)}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        ) : null}
      </div>
    </section>
  );
}