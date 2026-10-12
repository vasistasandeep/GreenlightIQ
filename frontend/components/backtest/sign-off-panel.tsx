"use client";

import { cn } from "@/lib/utils";
import type { FinalizationStatus } from "@/lib/types";

/**
 * SignOffPanel (R20.5).
 *
 * High-budget GREENLIGHT decisions require executive sign-off before they can be
 * finalized. This panel loads a decision's finalization gate
 * (`GET /decisions/{id}/finalization`) and surfaces the required roles together
 * with which approvals remain outstanding, so the studio makes the gating
 * explicit. A decision with no sign-off gate reports it is clear to finalize.
 *
 * Role identifiers from the backend are rendered as readable labels; unknown
 * roles fall back to a title-cased form of the identifier.
 */

const ROLE_LABELS: Record<string, string> = {
  CHIEF_CONTENT_OFFICER: "Chief Content Officer",
  CFO: "Chief Financial Officer",
  CONTENT_BUYER: "Content Buyer",
  DATA_ANALYST: "Data Analyst",
};

function roleLabel(role: string): string {
  if (role in ROLE_LABELS) {
    return ROLE_LABELS[role];
  }
  return role
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export interface SignOffPanelProps {
  /** The decision's finalization gate, or null before it has been loaded. */
  status?: FinalizationStatus | null;
  /** True while the finalization status is loading. */
  loading?: boolean;
  /** An error message if the finalization status could not be loaded. */
  error?: string | null;
  className?: string;
}

export function SignOffPanel({
  status = null,
  loading = false,
  error = null,
  className,
}: SignOffPanelProps) {
  const outstanding = new Set(status?.outstanding_roles ?? []);
  const approved = new Set(status?.approved_roles ?? []);

  return (
    <section
      className={cn("flex flex-col gap-3 rounded-lg border border-border p-4", className)}
      aria-labelledby="signoff-heading"
    >
      <div>
        <h3 id="signoff-heading" className="text-base font-semibold">
          Executive Sign-Off
        </h3>
        <p className="text-sm text-muted-foreground">
          High-budget greenlight decisions require sign-off before finalization.
        </p>
      </div>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading sign-off status…</p>
      ) : error ? (
        <p role="alert" className="text-sm font-medium text-red-600">
          {error}
        </p>
      ) : !status ? (
        <p className="text-sm text-muted-foreground">
          Load a decision to view its sign-off requirements.
        </p>
      ) : status.required_roles.length === 0 ? (
        <p className="text-sm font-medium text-emerald-700">
          No sign-off required — this decision is clear to finalize.
        </p>
      ) : (
        <>
          <div
            className={cn(
              "inline-flex w-fit items-center rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide",
              status.can_finalize
                ? "bg-emerald-100 text-emerald-800"
                : "bg-amber-100 text-amber-800",
            )}
          >
            {status.can_finalize ? "Ready to finalize" : "Awaiting approvals"}
          </div>

          <ul className="flex flex-col gap-1.5">
            {status.required_roles.map((role) => {
              const isApproved = approved.has(role);
              const isOutstanding = outstanding.has(role) || !isApproved;
              return (
                <li
                  key={role}
                  className="flex items-center justify-between rounded-md bg-muted px-3 py-2 text-sm"
                >
                  <span className="font-medium">{roleLabel(role)}</span>
                  <span
                    className={cn(
                      "text-xs font-semibold uppercase",
                      isApproved ? "text-emerald-700" : "text-amber-700",
                    )}
                  >
                    {isApproved ? "Approved" : isOutstanding ? "Outstanding" : "Pending"}
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
