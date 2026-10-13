/**
 * GreenlightMemo (Deal Decision Support, Investment Committee one-pager).
 *
 * A print-targeted executive brief rendered off-screen in normal viewing and
 * revealed by the browser's print dialog (see the `@media print` rules keyed on
 * `#greenlight-memo` in globals.css). It composes the recommendation, the four
 * guardrail checks, the dominant factor, the negotiation playbook, and a sign-off
 * block into a clean, paper-friendly layout a buyer can take into a Greenlight /
 * Investment Committee meeting.
 *
 * Decimal values arrive as JSON strings and are coerced before formatting.
 */

import type { ValuationScorecard } from "@/lib/types";
import { recommendationLabel } from "@/components/recommendation-badge";
import {
  formatMultiple,
  formatNumber,
  formatPercent,
  formatUsd,
  guardrailLabel,
  toNumber,
} from "./format";

export interface GreenlightMemoProps {

  titleId: string;
  scorecard: ValuationScorecard;
}

export function GreenlightMemo({ titleId, scorecard }: GreenlightMemoProps) {
  const checks = scorecard.explanation?.checks ?? [];
  const levers = scorecard.counter_proposal_levers ?? [];
  const isGreenlight = scorecard.recommendation_status === "GREENLIGHT";
  const generated = new Date().toISOString().slice(0, 10);

  return (
    <div
      id="greenlight-memo"
      aria-hidden="true"
      className="pointer-events-none absolute left-[-9999px] top-0"
    >
      <h1 style={{ fontSize: "20px", fontWeight: 700, marginBottom: "2px" }}>
        Greenlight Memo
      </h1>
      <p style={{ fontSize: "12px", marginBottom: "12px" }}>
        Title ID {titleId} &bull; Generated {generated} &bull; Recommendation:{" "}
        <strong>{recommendationLabel(scorecard.recommendation_status)}</strong>
      </p>

      <h2 style={{ fontSize: "13px", fontWeight: 700, margin: "10px 0 4px" }}>
        Financial Summary
      </h2>
      <table style={{ width: "100%", fontSize: "12px", borderCollapse: "collapse" }}>
        <tbody>
          <tr>
            <td>CPVH</td>
            <td style={{ textAlign: "right" }}>{formatNumber(scorecard.calculated_cpvh)}</td>
            <td>LTV-to-Cost</td>
            <td style={{ textAlign: "right" }}>{formatMultiple(scorecard.ltv_to_cost_multiple)}</td>
          </tr>
          <tr>
            <td>Churn reduction</td>
            <td style={{ textAlign: "right" }}>{formatPercent(scorecard.churn_reduction_pct)}</td>
            <td>Payback horizon</td>
            <td style={{ textAlign: "right" }}>
              {scorecard.payback_horizon_months ?? "-"} mo
            </td>
          </tr>
          <tr>
            <td>Normalized cost</td>
            <td style={{ textAlign: "right" }}>{formatUsd(scorecard.normalized_cost_usd)}</td>
            <td>Dominant factor</td>
            <td style={{ textAlign: "right" }}>
              {guardrailLabel(scorecard.explanation?.dominant_factor ?? null)}
            </td>
          </tr>
        </tbody>
      </table>

      <h2 style={{ fontSize: "13px", fontWeight: 700, margin: "12px 0 4px" }}>
        Guardrail Checks
      </h2>
      <table style={{ width: "100%", fontSize: "12px", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ borderBottom: "1px solid #cbd5e1", textAlign: "left" }}>
            <th>Check</th>
            <th style={{ textAlign: "right" }}>Computed</th>
            <th style={{ textAlign: "right" }}>Threshold</th>
            <th style={{ textAlign: "right" }}>Status</th>
          </tr>
        </thead>
        <tbody>
          {checks.map((c) => (
            <tr key={c.name} style={{ borderBottom: "1px solid #e2e8f0" }}>
              <td>{guardrailLabel(c.name)}</td>
              <td style={{ textAlign: "right" }}>{formatNumber(c.computed_value)}</td>
              <td style={{ textAlign: "right" }}>{formatNumber(c.threshold)}</td>
              <td style={{ textAlign: "right" }}>{c.passed ? "Passed" : "Breached"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {!isGreenlight && toNumber(scorecard.target_purchase_ceiling_usd) !== null ? (
        <>
          <h2 style={{ fontSize: "13px", fontWeight: 700, margin: "12px 0 4px" }}>
            Negotiation Playbook
          </h2>
          <p style={{ fontSize: "12px", margin: "0 0 4px" }}>
            Target purchase ceiling{" "}
            <strong>{formatUsd(scorecard.target_purchase_ceiling_usd)}</strong>
            {toNumber(scorecard.implied_discount_pct) !== null ? (
              <>
                {" "}
                (implied discount {formatPercent(scorecard.implied_discount_pct)})
              </>
            ) : null}
          </p>
          {levers.length > 0 ? (
            <ul style={{ fontSize: "12px", margin: "4px 0", paddingLeft: "18px" }}>
              {levers.map((lv) => (
                <li key={lv.name}>
                  <strong>{guardrailLabel(lv.name)}:</strong> {lv.message}
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}

      <h2 style={{ fontSize: "13px", fontWeight: 700, margin: "12px 0 4px" }}>
        Executive Sign-Off
      </h2>
      <table style={{ width: "100%", fontSize: "12px", borderCollapse: "collapse" }}>
        <tbody>
          <tr style={{ borderBottom: "1px solid #e2e8f0" }}>
            <td style={{ padding: "16px 0 4px" }}>Chief Content Officer</td>
            <td style={{ textAlign: "right" }}>Signature / Date</td>
          </tr>
          <tr style={{ borderBottom: "1px solid #e2e8f0" }}>
            <td style={{ padding: "16px 0 4px" }}>Chief Financial Officer</td>
            <td style={{ textAlign: "right" }}>Signature / Date</td>
          </tr>
        </tbody>
      </table>

      <p style={{ fontSize: "10px", marginTop: "12px", color: "#64748b" }}>
        Generated by CineROI AI. Modeled figures are decision-support estimates,
        not a guarantee of outcome.
      </p>
    </div>
  );
}