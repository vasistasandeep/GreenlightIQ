import { cva, type VariantProps } from "class-variance-authority";
import { Check, Scale, X, Clock, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import type { RecommendationStatus } from "@/lib/types";

/**
 * RecommendationBadge (R14.2, R14.3).
 *
 * Renders a title's {@link RecommendationStatus} as the executive-facing label
 * GREENLIGHT / NEGOTIATE HARD / PASS. Note the display label for `NEGOTIATE_HARD`
 * drops the underscore to the spelled-out "NEGOTIATE HARD" required by R14.3.
 *
 * Status is conveyed by THREE redundant channels - color, a distinct icon, and a
 * high-contrast border - so the meaning survives color-blindness (e.g. the green
 * check vs. the amber scale vs. the rose X are distinguishable without hue).
 */

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border-2 px-2.5 py-0.5 text-xs font-semibold tracking-wide uppercase whitespace-nowrap",
  {
    variants: {
      status: {
        GREENLIGHT: "border-emerald-500 bg-emerald-100 text-emerald-900",
        NEGOTIATE_HARD: "border-amber-500 bg-amber-100 text-amber-900",
        PASS: "border-rose-500 bg-rose-100 text-rose-900",
        UNKNOWN: "border-slate-400 bg-slate-100 text-slate-700",
      },
    },
    defaultVariants: {
      status: "UNKNOWN",
    },
  },
);

/** Display labels keyed by status. R14.3: GREENLIGHT, NEGOTIATE HARD, PASS. */
const STATUS_LABELS: Record<RecommendationStatus, string> = {
  GREENLIGHT: "GREENLIGHT",
  NEGOTIATE_HARD: "NEGOTIATE HARD",
  PASS: "PASS",
};

/** A distinct icon per status so meaning does not depend on color (a11y). */
const STATUS_ICONS: Record<RecommendationStatus | "UNKNOWN", LucideIcon> = {
  GREENLIGHT: Check,
  NEGOTIATE_HARD: Scale,
  PASS: X,
  UNKNOWN: Clock,
};

/** Fallback label when a title has no recommendation yet. */
const UNKNOWN_LABEL = "PENDING";

/** Resolve the executive display label for a recommendation status (R14.3). */
export function recommendationLabel(
  status: RecommendationStatus | null | undefined,
): string {
  if (status && status in STATUS_LABELS) {
    return STATUS_LABELS[status];
  }
  return UNKNOWN_LABEL;
}

export interface RecommendationBadgeProps
  extends Omit<React.HTMLAttributes<HTMLSpanElement>, "children">,
    Omit<VariantProps<typeof badgeVariants>, "status"> {
  /** The title's recommendation status; `null`/`undefined` renders a pending badge. */
  status: RecommendationStatus | null | undefined;
}

export function RecommendationBadge({
  status,
  className,
  ...props
}: RecommendationBadgeProps) {
  const variantStatus =
    status && status in STATUS_LABELS ? status : "UNKNOWN";
  const Icon = STATUS_ICONS[variantStatus];

  return (
    <span
      className={cn(badgeVariants({ status: variantStatus }), className)}
      {...props}
    >
      <Icon className="h-3 w-3" aria-hidden />
      {recommendationLabel(status)}
    </span>
  );
}