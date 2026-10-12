/**
 * PendingValuationState (R15.4).
 *
 * Shown when the requested title has no completed valuation yet — the backend
 * returns `404 TITLE_NOT_FOUND` for a title with no computed financial projection.
 * The view distinguishes this expected "pending" case from genuine errors.
 */

export interface PendingValuationStateProps {
  titleId: string;
}

export function PendingValuationState({ titleId }: PendingValuationStateProps) {
  return (
    <div
      role="status"
      className="rounded-lg border border-dashed bg-muted/40 p-10 text-center"
    >
      <h2 className="text-lg font-semibold">Valuation pending</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
        This title does not have a completed valuation yet. Once the Guardrails
        Engine finishes computing its scorecard, the metadata profile, financial
        breakdown, and recommendation will appear here.
      </p>
      <p className="mt-4 text-xs text-muted-foreground">Title {titleId}</p>
    </div>
  );
}
