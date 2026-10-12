import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";
import type { RecommendationStatus } from "@/lib/types";

/**
 * RecommendationBadge (R14.2, R14.3).
 *
 * Renders a title's {@link RecommendationStatus} as the executive-facing label
 * GREENLIGHT / NEGOTIATE HARD / PASS. Note the display label for `NEGOTIATE_HARD`
 * drops the underscore to the spelled-out "NEGOTIATE HARD" required by R14.3.
 */

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold tracking-wide uppercase whitespace-nowrap",
  {
    variants: {
      status: {
        GREENLIGHT: "border-emerald-200 bg-emerald-100 text-emerald-800",
        NEGOTIATE_HARD: "border-amber-200 bg-amber-100 text-amber-800",
        PASS: "border-red-200 bg-red-100 text-red-800",
        UNKNOWN: "border-slate-200 bg-slate-100 text-slate-600",
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

  return (
    <span
      className={cn(badgeVariants({ status: variantStatus }), className)}
      {...props}
    >
      {recommendationLabel(status)}
    </span>
  );
}
