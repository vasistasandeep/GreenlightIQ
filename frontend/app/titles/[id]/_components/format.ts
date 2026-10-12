/**
 * Formatting + guardrail-label helpers for the Title Evaluation view (R15, R30).
 *
 * Backend `Decimal` values arrive as JSON numbers or strings; these helpers coerce
 * them defensively and render executive-facing labels. Scoped to the
 * `/titles/[id]` route so the dashboard / backtest views are untouched.
 */

import type { GuardrailName } from "@/lib/types";

/** Coerce a backend Decimal (number | string | null) to a finite number or `null`. */
export function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Format a value as USD currency, or an em dash when absent. */
export function formatUsd(value: number | string | null | undefined): string {
  const n = toNumber(value);
  if (n === null) {
    return "—";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(n);
}

/** Format a numeric value to a fixed number of fraction digits, or an em dash. */
export function formatNumber(
  value: number | string | null | undefined,
  fractionDigits = 2,
): string {
  const n = toNumber(value);
  if (n === null) {
    return "—";
  }
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(n);
}

/** Format a 0-1 or 0-100 ratio as a percentage. Values <= 1 are treated as fractions. */
export function formatPercent(
  value: number | string | null | undefined,
  fractionDigits = 1,
): string {
  const n = toNumber(value);
  if (n === null) {
    return "—";
  }
  const pct = Math.abs(n) <= 1 ? n * 100 : n;
  return `${pct.toFixed(fractionDigits)}%`;
}

/** Format a multiple (e.g. LTV-to-cost) with an `×` suffix. */
export function formatMultiple(value: number | string | null | undefined): string {
  const n = toNumber(value);
  if (n === null) {
    return "—";
  }
  return `${n.toFixed(2)}×`;
}

/** Executive-facing labels for each guardrail check (R30.1). */
export const GUARDRAIL_LABELS: Record<GuardrailName, string> = {
  CPVH: "CPVH ceiling",
  LTV_TO_COST: "LTV-to-cost multiple",
  CHURN_MITIGATION: "Churn mitigation",
  PAYBACK_HORIZON: "Payback horizon",
};

/** Resolve a human-readable guardrail label, falling back to the raw name. */
export function guardrailLabel(name: string | null | undefined): string {
  if (!name) {
    return "—";
  }
  return GUARDRAIL_LABELS[name as GuardrailName] ?? name;
}
