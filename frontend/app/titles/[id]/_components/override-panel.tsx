"use client";

/**
 * OverridePanel (R20.2).
 *
 * Lets a decision-making executive override the engine's recommendation with a
 * mandatory business justification, which the backend records in the append-only
 * audit log. The control resolves the title's decision id, posts the override,
 * and surfaces the applied status. RBAC is enforced server-side; an unauthorized
 * role gets a readable error.
 *
 * Excluded from the Greenlight Memo print via `no-print`.
 */

import { useState } from "react";

import { api, ApiError } from "@/lib/api-client";
import type { RecommendationStatus } from "@/lib/types";
import { recommendationLabel } from "@/components/recommendation-badge";

const STATUSES: RecommendationStatus[] = ["GREENLIGHT", "NEGOTIATE_HARD", "PASS"];

export interface OverridePanelProps {
  titleId: string;
  currentStatus: RecommendationStatus | null;
  /** Called with the new status after a successful override so the page can refresh. */
  onOverridden?: (status: RecommendationStatus) => void;
}

export function OverridePanel({ titleId, currentStatus, onOverridden }: OverridePanelProps) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<RecommendationStatus>(currentStatus ?? "GREENLIGHT");
  const [justification, setJustification] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (justification.trim().length === 0) {
      setError("A business justification is required to override.");
      return;
    }
    setSubmitting(true);
    try {
      const { decision_id } = await api.getTitleDecision(titleId);
      const result = await api.overrideDecision(decision_id, {
        recommendation_status: status,
        justification: justification.trim(),
      });
      setApplied(result.recommendation_status);
      onOverridden?.(status);
      setOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError("Your role is not permitted to override recommendations.");
      } else if (err instanceof ApiError) {
        setError(err.envelope?.message ?? err.message);
      } else {
        setError("Could not record the override. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section
      aria-labelledby="override-heading"
      className="no-print rounded-lg border bg-background p-5 shadow-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="override-heading" className="text-lg font-semibold">
          Override recommendation
        </h2>
        {!open ? (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="inline-flex items-center rounded-md border border-slate-700 px-3 py-1.5 text-sm font-medium text-slate-200 hover:bg-slate-800"
          >
            Override recommendation
          </button>
        ) : null}
      </div>

      {applied ? (
        <p className="mt-2 text-sm font-medium text-emerald-500">
          Override recorded - recommendation is now {recommendationLabel(applied as RecommendationStatus)}.
        </p>
      ) : null}

      {open ? (
        <form onSubmit={submit} className="mt-3 flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">New recommendation</span>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as RecommendationStatus)}
              className="rounded-md border border-border bg-background px-3 py-2 text-sm"
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {recommendationLabel(s)}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">
              Business justification (recorded in the audit log)
            </span>
            <textarea
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              rows={3}
              placeholder="Why is this override warranted?"
              className="rounded-md border border-border bg-background px-3 py-2 text-sm"
            />
          </label>

          {error ? (
            <p role="alert" className="text-sm font-medium text-red-500">
              {error}
            </p>
          ) : null}

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="inline-flex items-center rounded-md bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 hover:bg-emerald-400 disabled:opacity-60"
            >
              {submitting ? "Recording..." : "Record override"}
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-sm text-slate-400 hover:text-slate-200"
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}