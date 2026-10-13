import { cn } from "@/lib/utils";
import type { DealStage } from "@/lib/types";

/**
 * DealStageBadge - renders a title's acquisition {@link DealStage} as a labelled
 * pill. Stage is conveyed by both a distinct color and a spelled-out label so it
 * does not rely on color alone (a11y). Terminal stages (won/lost/passed) use
 * muted or outcome colors to read as "done".
 */

const STAGE_LABELS: Record<DealStage, string> = {
  SCREENING: "Screening",
  EVALUATED: "Evaluated",
  IN_NEGOTIATION: "In Negotiation",
  APPROVED: "Approved",
  CLOSED_WON: "Closed · Won",
  CLOSED_LOST: "Closed · Lost",
  PASSED: "Passed",
};

const STAGE_CLASSES: Record<DealStage, string> = {
  SCREENING: "border-slate-500 bg-slate-500/10 text-slate-300",
  EVALUATED: "border-sky-500 bg-sky-500/10 text-sky-300",
  IN_NEGOTIATION: "border-amber-500 bg-amber-500/10 text-amber-300",
  APPROVED: "border-emerald-500 bg-emerald-500/10 text-emerald-300",
  CLOSED_WON: "border-emerald-600 bg-emerald-600/20 text-emerald-200",
  CLOSED_LOST: "border-rose-500 bg-rose-500/10 text-rose-300",
  PASSED: "border-slate-600 bg-slate-700/20 text-slate-400",
};

/** Resolve the display label for a deal stage. */
export function dealStageLabel(stage: DealStage | null | undefined): string {
  return stage ? STAGE_LABELS[stage] ?? stage : "—";
}

export interface DealStageBadgeProps {
  stage: DealStage | null | undefined;
  className?: string;
}

export function DealStageBadge({ stage, className }: DealStageBadgeProps) {
  if (!stage) {
    return <span className={cn("text-sm text-muted-foreground", className)}>—</span>;
  }
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
        STAGE_CLASSES[stage],
        className,
      )}
    >
      {STAGE_LABELS[stage] ?? stage}
    </span>
  );
}