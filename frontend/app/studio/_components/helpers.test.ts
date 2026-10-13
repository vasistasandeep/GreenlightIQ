import { describe, it, expect } from "vitest";

import { parseShorthandAmount } from "./helpers";

describe("parseShorthandAmount", () => {
  it.each<[string, number]>([
    ["12 Cr", 120_000_000],
    ["12cr", 120_000_000],
    ["1.5M", 1_500_000],
    ["500k", 500_000],
    ["3 Lakh", 300_000],
    ["2.4 crore", 24_000_000],
    ["1,200,000", 1_200_000],
    ["42000000", 42_000_000],
    ["1 bn", 1_000_000_000],
    ["0.05", 0.05],
  ])("parses %s to %d", (input, expected) => {
    expect(parseShorthandAmount(input)).toBe(expected);
  });

  it.each(["", "abc", "12 foo", "1.2.3", "cr"])(
    "returns null for invalid input %s",
    (input) => {
      expect(parseShorthandAmount(input)).toBeNull();
    },
  );
});