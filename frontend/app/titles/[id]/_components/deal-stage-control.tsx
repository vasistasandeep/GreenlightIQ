"use client";

/**
 * DealStageControl - the acquisition deal-stage lifecycle control.
 *
 * Shows where the title sits in the human acquisition pipeline (orthogonal to
 * the AI recommendation) and lets a decision-making user advance it along the
 * guarded state machine. The allowed next stages come from the server, so the
 * UI never offers an illegal move; a rejected transition (e.g. a stale view)
 * surfaces the server's message. A 403 is treated as "not permitted" and the
 * controls are hidden rather than erroring.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api-client";
import type { DealStage, DealStageInfo } from "@/lib/types";
import { DealStageBadge, dealStageLabel } from "@/components/deal-stage-badge";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; info: DealStageInfo; permitted: boolean };

export interface DealStageControlProps {
  titleId: string;
}

export function DealStageControl({ titleId }: DealStageControlProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [saving, setSaving] = useState<DealStage | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const info = await api.getDealStage(titleId);
      setState({ status: "ready", info, permitted: true });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load the deal stage.";
      setState({ status: "error", message });
    }
  }, [titleId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function advance(target: DealStage) {
    setSaving(target);
    setActionError(null);
    try {
      const info = await api.setDealStage(titleId, target);
      setState({ status: "ready", info, permitted: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        // Not a decision-making role: keep the current stage, hide the actions.
        setState((prev) =>
          prev.status === "ready" ? { ...prev, permitted: false } : prev,
        );
        setActionError("You do not have permission to change the deal stage.");
      } else {
        const message =
          err instanceof Error ? err.message : "Could not update the deal stage.";
        setActionError(message);
      }
    } finally {
      setSaving(null);
    }
  }

  return (
    <section
      aria-labelledby="deal-stage-heading"
      className="rounded-lg border bg-background p-5 shadow-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="deal-stage-heading" className="text-lg font-semibold">
            Deal stage
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Where this title sits in the acquisition pipeline.
          </p>
        </div>
        {state.status === "ready" ? <DealStageBadge stage={state.info.deal_stage} /> : null}
      </div>

      <div className="mt-4">
        {state.status === "loading" ? (
          <p className="text-sm text-muted-foreground" role="status">
            Loading deal stage...
          </p>
        ) : null}

        {state.status === "error" ? (
          <div role="alert" className="text-sm">
            <p className="font-medium text-red-500">{state.message}</p>
            <button
              type="button"
              onClick={() => void load()}
              className="mt-2 inline-flex items-center rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
            >
              Retry
            </button>
          </div>
        ) : null}

        {state.status === "ready" ? (
          state.info.allowed_next_stages.length > 0 && state.permitted ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-muted-foreground">Advance to:</span>
              {state.info.allowed_next_stages.map((stage) => (
                <button
                  key={stage}
                  type="button"
                  disabled={saving !== null}
                  onClick={() => void advance(stage)}
                  className="inline-flex items-center rounded-md border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-sm font-medium text-slate-100 hover:border-emerald-500 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
                >
                  {saving === stage ? "Saving..." : dealStageLabel(stage)}
                </button>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {state.info.allowed_next_stages.length === 0
                ? "This deal has reached a final stage."
                : "Viewing only - advancing the deal stage requires a decision-making role."}
            </p>
          )
        ) : null}

        {actionError ? (
          <p role="alert" className="mt-3 text-sm font-medium text-red-500">
            {actionError}
          </p>
        ) : null}
      </div>
    </section>
  );
}