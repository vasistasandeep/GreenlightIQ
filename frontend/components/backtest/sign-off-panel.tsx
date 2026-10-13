"use client";

import { cn } from "@/lib/utils";
import type { FinalizationStatus } from "@/lib/types";

/**
 * SignOffPanel (R20.5).
 *
 * High-budget GREENLIGHT decisions require executive sign-off before they can be
 * finalized. This panel shows a decision's finalization gate (required roles and
 * which approvals remain outstanding) and - in the demo - lets the user record a
 * sign-off for each outstanding role so the gate can be cleared end-to-end.
 *
 * A decision that needs no sign-off reports it is clear to finalize; a title with
 * no decision yet shows a neutral "nothing to finalize" message rather than an
 * error.
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
  /**
   * Record a sign-off for a specific required role (demo). When provided, each
   * outstanding role shows an Approve action; resolves when the gate is
   * refreshed. Omit to render the panel read-only.
   */
  onApproveRole?: (role: string) => void | Promise<void>;
  /** The role currently being signed off, if any (disables that row's button). */
  approvingRole?: string | null;
  className?: string;
}

export function SignOffPanel({
  status = null,
  loading = false,
  error = null,
  onApproveRole,
  approvingRole = null,
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
        <p className="text-sm text-muted-foreground">Loading sign-off status...</p>
      ) : error ? (
        <p role="alert" className="text-sm font-medium text-red-600">
          {error}
        </p>
      ) : !status ? (
        <p className="text-sm text-muted-foreground">
          Run an audit on a title to view its sign-off requirements.
        </p>
      ) : status.required_roles.length === 0 ? (
        <p className="text-sm font-medium text-emerald-700">
          No sign-off required - this decision is clear to finalize.
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
                  className="flex items-center justify-between gap-3 rounded-md bg-muted px-3 py-2 text-sm"
                >
                  <span className="font-medium">{roleLabel(role)}</span>
                  <div className="flex items-center gap-3">
                    <span
                      className={cn(
                        "text-xs font-semibold uppercase",
                        isApproved ? "text-emerald-700" : "text-amber-700",
                      )}
                    >
                      {isApproved ? "Approved" : "Outstanding"}
                    </span>
                    {onApproveRole && !isApproved ? (
                      <button
                        type="button"
                        onClick={() => onApproveRole(role)}
                        disabled={approvingRole === role}
                        className={cn(
                          "inline-flex items-center rounded-md border border-primary px-2.5 py-1",
                          "text-xs font-semibold text-primary",
                          "disabled:cursor-not-allowed disabled:opacity-50",
                        )}
                      >
                        {approvingRole === role
                          ? "Signing..."
                          : `Approve as ${roleLabel(role)}`}
                      </button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>

          {status.can_finalize ? (
            <p className="text-sm font-medium text-emerald-700">
              All required sign-offs recorded - this decision can be finalized.
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}