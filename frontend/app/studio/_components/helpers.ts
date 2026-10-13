/** Formatting helpers for the Asset Studio (dark executive report). */

export function num(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

export function usd(value: number | string | null | undefined, compact = false): string {
  const n = num(value);
  if (n === null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: compact ? 1 : 0,
  }).format(n);
}

export function multiple(value: number | string | null | undefined): string {
  const n = num(value);
  return n === null ? "—" : `${n.toFixed(2)}x`;
}

export function pct(value: number | string | null | undefined, digits = 1): string {
  const n = num(value);
  if (n === null) return "—";
  const v = Math.abs(n) <= 1 ? n * 100 : n;
  return `${v.toFixed(digits)}%`;
}

export function decimals(value: number | string | null | undefined, digits = 3): string {
  const n = num(value);
  return n === null ? "—" : n.toFixed(digits);
}

/** Format an integer subscriber count with grouping, em dash when null. */
export function subscribers(value: number | string | null | undefined): string {
  const n = num(value);
  if (n === null) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(
    Math.round(n),
  );
}

export const GUARDRAIL_LABELS: Record<string, string> = {
  CPVH: "CPVH Check",
  LTV_TO_COST: "LTV-to-Cost",
  CHURN_MITIGATION: "Churn Mitigation",
  PAYBACK_HORIZON: "Payback Horizon",
};

export function guardrailLabel(name: string): string {
  return GUARDRAIL_LABELS[name] ?? name;
}