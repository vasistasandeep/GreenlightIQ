import { describe, expect, it } from "vitest";
import fc from "fast-check";

import { selectAuditableTitles } from "@/lib/backtest/select-auditable-titles";
import type { RecommendationStatus, TitleSummary } from "@/lib/types";

/**
 * selectAuditableTitles property tests.
 *
 * Feature: backtest-studio-demo-friendly, Property 1: Auditable filter selects
 * exactly the titles with a stored prediction.
 */

const STATUSES: (RecommendationStatus | null)[] = [
  null,
  "GREENLIGHT",
  "NEGOTIATE_HARD",
  "PASS",
];

/** Build a TitleSummary-shaped record with a chosen recommendation_status. */
function titleArb(): fc.Arbitrary<TitleSummary> {
  return fc.record({
    title_id: fc.uuid(),
    title_name: fc.string(),
    asset_type: fc.constantFrom(
      "ORIGINAL_SERIES",
      "ORIGINAL_FILM",
      "LICENSED_LIBRARY",
      "CO_PRODUCTION",
    ) as fc.Arbitrary<TitleSummary["asset_type"]>,
    asking_price: fc.integer({ min: 0, max: 1_000_000 }),
    native_currency: fc.constantFrom("USD", "EUR", "INR"),
    cpvh_status: fc.constantFrom(
      "PASS",
      "BREACH",
      "NO_CEILING",
      "PENDING",
    ) as fc.Arbitrary<TitleSummary["cpvh_status"]>,
    ltv_to_cost_multiple: fc.option(fc.float({ min: 0, max: 10 }), { nil: null }),
    recommendation_status: fc.constantFrom(...STATUSES),
  });
}

describe("selectAuditableTitles (Property 1)", () => {
  it("keeps exactly the titles whose recommendation_status is non-null", () => {
    fc.assert(
      fc.property(fc.array(titleArb()), (titles) => {
        const result = selectAuditableTitles(titles);
        const expected = titles.filter((t) => t.recommendation_status !== null);

        // Same count as the non-null subset.
        expect(result).toHaveLength(expected.length);

        // Same identity and order: each kept option matches a non-null title.
        expected.forEach((title, index) => {
          expect(result[index]).toEqual({
            title_id: title.title_id,
            title_name: title.title_name,
          });
        });

        // Every null-status title is excluded.
        const keptIds = new Set(result.map((o) => o.title_id));
        titles
          .filter((t) => t.recommendation_status === null)
          .forEach((t) => {
            // A null-status title id only appears if a distinct non-null title
            // happened to share the id; guard by checking the status subset.
            const sharesWithNonNull = expected.some(
              (e) => e.title_id === t.title_id,
            );
            if (!sharesWithNonNull) {
              expect(keptIds.has(t.title_id)).toBe(false);
            }
          });
      }),
      { numRuns: 200 },
    );
  });

  it("returns an empty list when every title lacks a prediction", () => {
    const titles = [
      { recommendation_status: null } as TitleSummary,
      { recommendation_status: null } as TitleSummary,
    ];
    expect(selectAuditableTitles(titles)).toEqual([]);
  });
});