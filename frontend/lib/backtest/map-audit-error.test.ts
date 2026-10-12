import { describe, expect, it } from "vitest";
import fc from "fast-check";

import { ApiError } from "@/lib/api-client";
import { mapAuditError } from "@/lib/backtest/map-audit-error";
import type { ApiErrorEnvelope } from "@/lib/types";

/**
 * mapAuditError property + example tests.
 *
 * Feature: backtest-studio-demo-friendly, Property 2: Known error codes map to
 *   their specific actionable message.
 * Feature: backtest-studio-demo-friendly, Property 3: Unmapped codes fall back to
 *   the (ASCII-sanitized) envelope message, else the generic message.
 * Feature: backtest-studio-demo-friendly, Property 4: Mapper output is ASCII-only.
 *
 * Note on Properties 3 + 4: the mapper surfaces the backend envelope message for
 * unmapped codes (Requirement 3.5) but strips non-ASCII characters first so the
 * ASCII-only invariant (Requirement 3.6) always holds. The fallback assertions
 * therefore compare against the ASCII-sanitized form of the input message.
 */

const GENERIC = "Something went wrong. Please try again.";
const INVALID_TITLE =
  "The selected title identifier is invalid or missing. Please select an auditable title.";
const NOT_FOUND = "The selected title no longer exists in the system.";
const NO_PREDICTION =
  "The selected title has no stored prediction to audit against.";
const INVALID_ACTUALS =
  "The entered actual values are invalid. Enter numeric values only.";

const MAPPED_CODES = [
  "VALIDATION_FAILED",
  "TITLE_NOT_FOUND",
  "GROUND_TRUTH_MISSING",
  "GROUND_TRUTH_INVALID",
];

/** Construct an ApiError with the given status, code, and message. */
function apiError(status: number, code: string, message: string): ApiError {
  const envelope: ApiErrorEnvelope = { error_code: code, message };
  return new ApiError(status, message, envelope);
}

function isAscii(s: string): boolean {
  for (const ch of s) {
    if (ch.codePointAt(0)! >= 128) {
      return false;
    }
  }
  return true;
}

/** Mirror of the mapper's internal ASCII sanitization, for test expectations. */
function expectedAscii(value: string): string {
  let out = "";
  for (const ch of value) {
    if (ch.codePointAt(0)! < 128) {
      out += ch;
    }
  }
  return out.replace(/\s+/g, " ").trim();
}

describe("mapAuditError (Property 2: known-code mapping)", () => {
  it("maps each known code to its specific message, honoring the 404 pair", () => {
    const known = fc.oneof(
      fc
        .record({ status: fc.integer({ min: 400, max: 500 }), message: fc.string() })
        .map((r) => ({ ...r, code: "VALIDATION_FAILED", expected: INVALID_TITLE })),
      fc
        .record({ message: fc.string() })
        .map((r) => ({
          status: 404,
          code: "TITLE_NOT_FOUND",
          message: r.message,
          expected: NOT_FOUND,
        })),
      fc
        .record({ message: fc.string() })
        .map((r) => ({
          status: 404,
          code: "GROUND_TRUTH_MISSING",
          message: r.message,
          expected: NO_PREDICTION,
        })),
      fc
        .record({ status: fc.integer({ min: 400, max: 500 }), message: fc.string() })
        .map((r) => ({
          ...r,
          code: "GROUND_TRUTH_INVALID",
          expected: INVALID_ACTUALS,
        })),
    );

    fc.assert(
      fc.property(known, ({ status, code, message, expected }) => {
        expect(mapAuditError(apiError(status, code, message))).toBe(expected);
      }),
      { numRuns: 200 },
    );
  });

  it("maps concrete examples per branch", () => {
    expect(mapAuditError(apiError(422, "VALIDATION_FAILED", "x"))).toBe(INVALID_TITLE);
    expect(mapAuditError(apiError(404, "TITLE_NOT_FOUND", "x"))).toBe(NOT_FOUND);
    expect(mapAuditError(apiError(404, "GROUND_TRUTH_MISSING", "x"))).toBe(
      NO_PREDICTION,
    );
    expect(mapAuditError(apiError(422, "GROUND_TRUTH_INVALID", "x"))).toBe(
      INVALID_ACTUALS,
    );
  });
});

describe("mapAuditError (Property 3: unmapped fallback)", () => {
  it("falls back to the ASCII-sanitized envelope message, else the generic message", () => {
    const unmappedCode = fc.string().filter((c) => !MAPPED_CODES.includes(c));

    fc.assert(
      fc.property(
        fc.integer({ min: 400, max: 500 }),
        unmappedCode,
        fc.string({ unit: "binary" }),
        (status, code, message) => {
          const result = mapAuditError(apiError(status, code, message));
          const ascii = expectedAscii(message);
          if (ascii.length > 0) {
            expect(result).toBe(ascii);
          } else {
            expect(result).toBe(GENERIC);
          }
        },
      ),
      { numRuns: 200 },
    );
  });

  it("passes through a plain-ASCII unmapped message verbatim", () => {
    const asciiMessage = fc
      .string()
      .filter((m) => m === expectedAscii(m) && m.length > 0);
    const unmappedCode = fc.string().filter((c) => !MAPPED_CODES.includes(c));

    fc.assert(
      fc.property(unmappedCode, asciiMessage, (code, message) => {
        expect(mapAuditError(apiError(500, code, message))).toBe(message);
      }),
      { numRuns: 100 },
    );
  });

  it("handles concrete unmapped examples", () => {
    expect(mapAuditError(apiError(500, "INTERNAL_ERROR", "boom"))).toBe("boom");
    expect(mapAuditError(apiError(500, "INTERNAL_ERROR", ""))).toBe(GENERIC);
  });

  it("returns the generic message for non-ApiError input", () => {
    expect(mapAuditError(new Error("nope"))).toBe(GENERIC);
    expect(mapAuditError("string error")).toBe(GENERIC);
    expect(mapAuditError(null)).toBe(GENERIC);
    expect(mapAuditError(undefined)).toBe(GENERIC);
  });
});

describe("mapAuditError (Property 4: ASCII-only output)", () => {
  it("produces ASCII-only output for any input", () => {
    const anyInput = fc.oneof(
      fc
        .record({
          status: fc.integer({ min: 400, max: 599 }),
          code: fc.string(),
          message: fc.string({ unit: "binary" }),
        })
        .map(({ status, code, message }) => apiError(status, code, message)),
      fc.anything(),
    );

    fc.assert(
      fc.property(anyInput, (input) => {
        expect(isAscii(mapAuditError(input))).toBe(true);
      }),
      { numRuns: 300 },
    );
  });
});