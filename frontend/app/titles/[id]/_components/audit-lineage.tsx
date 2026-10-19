"use client";

/**
 * AuditLineage (R25.4).
 *
 * A collapsible timeline of the append-only audit lineage for a title's decision
 * - who created, evaluated, overrode, or signed off on it, in chronological
 * order. Compliance and legal teams use this to trace every input and change.
 * Loads lazily on first expand via GET /audit/lineage/{decisionId}.
 */

import { useState } from "react";

import { api } from "@/lib/api-client";
import type { AuditEntry } from "@/lib/types";

const ACTION_LABELS: Record<string, string> = {
  valuation: "Guardrail valuation executed",
  override: "Recommendation overridden",
  approve: "Executive sign-off recorded",
  reject: "Decision rejected",
};

function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().replace("T", " ").slice(0, 19) + " UTC";
}

function summarize(entry: AuditEntry): string | null {
  const before = entry.before_value?.recommendation_status;
  const after = entry.after_value?.recommendation_status;
  if (before !== undefined || after !== undefined) {
    return `${String(before ?? "-")} to ${String(after ?? "-")}`;
  }
  return null;
}

export interface AuditLineageProps {
  titleId: string;
}

export function AuditLineage({ titleId }: AuditLineageProps) {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const { decision_id } = await api.getTitleDecision(titleId);
      const lineage = await api.getLineage(decision_id);
      setEntries(lineage.entries);
    } catch {
      setError("Could not load the audit history.");
    } finally {
      setLoading(false);
    }
  }

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && entries === null && !loading) {
      void load();
    }
  }

  return (
    <section
      aria-labelledby="audit-lineage-heading"
      className="no-print rounded-xl border border-slate-800 bg-slate-900/60 p-5 shadow-sm shadow-black/20"
    >
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="flex w-full items-center justify-between text-left"
      >
        <h2 id="audit-lineage-heading" className="text-lg font-semibold">
          Audit history &amp; lineage
        </h2>
        <span aria-hidden className="text-muted-foreground">
          {open ? "Hide" : "Show"}
        </span>
      </button>

      {open ? (
        <div className="mt-3">
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading history...</p>
          ) : error ? (
            <p role="alert" className="text-sm font-medium text-red-500">
              {error}
            </p>
          ) : entries && entries.length > 0 ? (
            <ol className="relative space-y-4 border-l border-slate-700 pl-5">
              {entries.map((e) => {
                const change = summarize(e);
                return (
                  <li key={e.audit_id} className="relative">
                    <span
                      aria-hidden
                      className="absolute -left-[1.42rem] top-1.5 h-2.5 w-2.5 rounded-full bg-emerald-500"
                    />
                    <p className="text-sm font-medium text-slate-200">
                      {actionLabel(e.action)}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {formatTimestamp(e.created_at)}
                      {change ? ` - ${change}` : ""}
                    </p>
                  </li>
                );
              })}
            </ol>
          ) : (
            <p className="text-sm text-muted-foreground">
              No recorded history for this decision yet.
            </p>
          )}
        </div>
      ) : null}
    </section>
  );
}