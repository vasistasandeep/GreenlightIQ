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

/**
 * Parse a shorthand monetary amount into an absolute number, or null when the
 * input is not a recognizable amount. Supports grouping commas and the suffixes
 * k (thousand), L / lakh (1e5), M / mn (million), Cr / crore (1e7), B / bn
 * (billion). Case-insensitive; a bare number passes through. Examples:
 *   "12 Cr" -> 120000000, "1.5M" -> 1500000, "500k" -> 500000,
 *   "3 Lakh" -> 300000, "1,200,000" -> 1200000.
 */
export function parseShorthandAmount(raw: string): number | null {
  const text = raw.trim().toLowerCase();
  if (text === "") return null;
  const match = text.match(
    /^([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]*\.?[0-9]+)\s*(cr|crore|crores|l|lakh|lakhs|k|m|mn|million|b|bn|billion)?$/,
  );
  if (!match) return null;
  const base = Number(match[1].replace(/,/g, ""));
  if (!Number.isFinite(base)) return null;
  const suffix = match[2];
  const factor: Record<string, number> = {
    k: 1e3,
    l: 1e5, lakh: 1e5, lakhs: 1e5,
    m: 1e6, mn: 1e6, million: 1e6,
    cr: 1e7, crore: 1e7, crores: 1e7,
    b: 1e9, bn: 1e9, billion: 1e9,
  };
  const mult = suffix ? factor[suffix] ?? 1 : 1;
  return base * mult;
}
