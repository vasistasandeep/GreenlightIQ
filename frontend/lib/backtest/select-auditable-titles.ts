/**
 * Pure selector for the Backtesting Studio title picker.
 *
 * Derives the list of auditable titles from the dashboard summary rows: a title
 * is auditable only when it already carries a stored prediction, i.e. its
 * `recommendation_status` is non-null (an audit compares predicted vs actual, so
 * a title with no prediction can never be audited). The projection keeps only the
 * identifier and display name the selector needs, preserving input order.
 *
 * This module is intentionally pure (no React, no fetch) so it is directly
 * unit- and property-testable.
 */

import type { TitleSummary } from "@/lib/types";

/** One selectable auditable title passed from the page to the form. */
export interface AuditableTitleOption {
  title_id: string;
  title_name: string;
}

/** Load lifecycle for the title list; drives selector enable + placeholder. */
export type TitlesLoadStatus = "loading" | "loaded" | "empty" | "error";

/**
 * Keep only titles that have a stored prediction (non-null recommendation_status)
 * and project each to the minimal option shape, preserving input order.
 */
export function selectAuditableTitles(
  titles: TitleSummary[],
): AuditableTitleOption[] {
  return titles
    .filter((title) => title.recommendation_status !== null)
    .map((title) => ({ title_id: title.title_id, title_name: title.title_name }));
}