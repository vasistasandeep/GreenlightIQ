/**
 * Pure mapper from an audit request failure to a readable, ASCII-only message.
 *
 * The Backtesting Studio posts a ground-truth audit to `POST /backtest/audit`.
 * On rejection the backend returns a typed error envelope with an `error_code`.
 * This mapper branches on that code (and the HTTP status for the 404 pair) to
 * produce an actionable, user-facing string instead of a raw technical error.
 *
 * The function is total: it always returns a readable ASCII string, including for
 * non-ApiError values and for ApiErrors with an unknown or missing error_code.
 * The unmapped-code fallback surfaces the backend envelope message (Requirement
 * 3.5) but strips any non-ASCII characters first so the ASCII-only invariant
 * (Requirement 3.6) always holds. Kept pure (no React, no DOM, no fetch) so it is
 * directly property-testable.
 */

import { ApiError } from "@/lib/api-client";

const GENERIC_MESSAGE = "Something went wrong. Please try again.";

const MESSAGES = {
  invalidTitle:
    "The selected title identifier is invalid or missing. Please select an auditable title.",
  notFound: "The selected title no longer exists in the system.",
  noPrediction:
    "The selected title has no stored prediction to audit against.",
  invalidActuals:
    "The entered actual values are invalid. Enter numeric values only.",
} as const;

/**
 * Drop every non-ASCII character (code point >= 128) and collapse the surrounding
 * whitespace, so a backend message can be surfaced without breaking the ASCII-only
 * invariant. Returns an empty string when nothing printable remains.
 */
function toAscii(value: string): string {
  let out = "";
  for (const ch of value) {
    if (ch.codePointAt(0)! < 128) {
      out += ch;
    }
  }
  return out.replace(/\s+/g, " ").trim();
}

/**
 * Map an audit request failure to a readable, ASCII-only user-facing message.
 *
 * Branches on the backend error_code (and HTTP status for the 404 pair). Unknown
 * codes fall back to the ASCII-sanitized envelope message when present, else a
 * generic message.
 */
export function mapAuditError(err: unknown): string {
  if (!(err instanceof ApiError)) {
    return GENERIC_MESSAGE;
  }

  const code = err.errorCode;

  switch (code) {
    case "VALIDATION_FAILED":
      return MESSAGES.invalidTitle;
    case "GROUND_TRUTH_INVALID":
      return MESSAGES.invalidActuals;
    case "TITLE_NOT_FOUND":
      if (err.status === 404) {
        return MESSAGES.notFound;
      }
      break;
    case "GROUND_TRUTH_MISSING":
      if (err.status === 404) {
        return MESSAGES.noPrediction;
      }
      break;
    default:
      break;
  }

  const envelopeMessage = err.envelope?.message;
  if (typeof envelopeMessage === "string") {
    const ascii = toAscii(envelopeMessage);
    if (ascii.length > 0) {
      return ascii;
    }
  }
  return GENERIC_MESSAGE;
}