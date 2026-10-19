/**
 * ExplanationPanel (R30.4).
 *
 * The explainability surface for a recommendation: every guardrail check with its
 * pass/breach status (R30.1), the computed value against its threshold and the
 * shortfall magnitude for breaches (R30.2), and the dominant contributing factor
 * driving a PASS / NEGOTIATE_HARD status (R30.3). When a breach could not be
 * classified the panel flags the result as unclassifiable (R8.4).
 *
 * Presentational, server-renderable (no interactivity).
 */

import type { Explanation } from "@/lib/types";
import { formatNumber, guardrailLabel } from "./format";

export interface ExplanationPanelProps {
  explanation: Explanation | null;
}

export function ExplanationPanel({ explanation }: ExplanationPanelProps) {
  // The stored explanation (from GET /valuation) may omit `checks`; only a live
  // recompute carries the full per-check array. Default to an empty list so the
  // panel degrades to its empty state instead of throwing.
  const checks = explanation?.checks ?? [];
  return (
    <section
      aria-labelledby="explanation-panel-heading"
      className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 shadow-sm shadow-black/20"
    >
      <h2 id="explanation-panel-heading" className="mb-3 text-lg font-semibold">
        Why this recommendation
      </h2>

      {!explanation || checks.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No recommendation explanation is available for this title.
        </p>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <p>
              <span className="text-muted-foreground">Dominant factor: </span>
              <span className="font-medium">
                {explanation.dominant_factor
                  ? guardrailLabel(explanation.dominant_factor)
                  : "None — all checks passed"}
              </span>
            </p>
            {explanation.unclassifiable ? (
              <p className="font-medium text-red-700">
                A breach could not be classified — treat the result with caution.
              </p>
            ) : null}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">
                Guardrail checks with computed value, threshold, and shortfall
              </caption>
              <thead>
                <tr className="border-b text-xs uppercase tracking-wide text-muted-foreground">
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Check
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Status
                  </th>
                  <th scope="col" className="py-2 pr-4 text-right font-medium">
                    Computed
                  </th>
                  <th scope="col" className="py-2 pr-4 text-right font-medium">
                    Threshold
                  </th>
                  <th scope="col" className="py-2 text-right font-medium">
                    Shortfall
                  </th>
                </tr>
              </thead>
              <tbody>
                {checks.map((check) => {
                  const isDominant = explanation.dominant_factor === check.name;
                  return (
                    <tr key={check.name} className="border-b last:border-b-0">
                      <th
                        scope="row"
                        className="py-2 pr-4 font-medium"
                      >
                        {guardrailLabel(check.name)}
                        {isDominant ? (
                          <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-600">
                            Dominant
                          </span>
                        ) : null}
                      </th>
                      <td className="py-2 pr-4">
                        <span
                          className={
                            check.passed
                              ? "inline-flex rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800"
                              : "inline-flex rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-800"
                          }
                        >
                          {check.passed ? "Passed" : "Breached"}
                        </span>
                      </td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        {formatNumber(check.computed_value)}
                      </td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        {formatNumber(check.threshold)}
                      </td>
                      <td className="py-2 text-right tabular-nums">
                        {check.breached
                          ? formatNumber(check.shortfall_magnitude)
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
