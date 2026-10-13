"""Pure heuristics to pre-fill Asset Studio fields from pitch-deck text.

Given the plain text extracted from a pitch / script PDF, best-effort parse the
fields the Asset Studio form collects (title, synopsis, genre, budget, talent
pedigree, exclusivity). This is intentionally forgiving: it returns whatever it
can recognize and leaves the rest for the user to review and edit - the UI never
auto-submits a parsed deck.

Pure module: no I/O, no PDF library (the caller extracts the text). Directly
unit-testable over representative deck text.
"""

from __future__ import annotations

import re
from typing import Optional, TypedDict

__all__ = ["ParsedPitch", "parse_pitch_text"]

# Shorthand money suffixes -> multiplier (mirrors the frontend parser).
_MONEY_FACTOR = {
    "k": 1_000, "l": 100_000, "lakh": 100_000, "lakhs": 100_000,
    "m": 1_000_000, "mn": 1_000_000, "million": 1_000_000,
    "cr": 10_000_000, "crore": 10_000_000, "crores": 10_000_000,
    "b": 1_000_000_000, "bn": 1_000_000_000, "billion": 1_000_000_000,
}

_GENRES = [
    "sci-fi", "science fiction", "drama", "thriller", "comedy", "horror",
    "action", "romance", "documentary", "fantasy", "crime", "mystery",
    "animation", "adventure",
]

_LABELLED = {
    "title": re.compile(r"^\s*(?:title|project|working title)\s*[:\-]\s*(.+)$", re.I | re.M),
    "synopsis": re.compile(r"^\s*(?:synopsis|logline|premise|summary)\s*[:\-]\s*(.+)$", re.I | re.M),
    "genre": re.compile(r"^\s*genre\s*[:\-]\s*(.+)$", re.I | re.M),
    "budget": re.compile(r"^\s*(?:budget|cost|acquisition cost|ask|price)\s*[:\-]\s*(.+)$", re.I | re.M),
    "talent": re.compile(r"^\s*(?:talent|cast|director|starring|showrunner)\s*[:\-]\s*(.+)$", re.I | re.M),
}

_MONEY = re.compile(
    r"(?:(?:USD|EUR|GBP|INR|\$|&#8377;|&#8364;|&#163;)\s*)?"
    r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*"
    r"(k|l|lakh|lakhs|m|mn|million|cr|crore|crores|b|bn|billion)?",
    re.I,
)

_CURRENCY_HINT = [
    (re.compile(r"\b(?:inr|rs\.?|&#8377;|crore|lakh)\b", re.I), "INR"),
    (re.compile(r"\b(?:eur|&#8364;|euro)\b", re.I), "EUR"),
    (re.compile(r"\b(?:gbp|&#163;|pound)\b", re.I), "GBP"),
    (re.compile(r"\b(?:usd|\$|dollar)\b", re.I), "USD"),
]


class ParsedPitch(TypedDict, total=False):
    """Best-effort fields parsed from pitch text; any field may be absent."""

    title_name: Optional[str]
    synopsis: Optional[str]
    genre_tag: Optional[str]
    acquisition_cost_or_budget: Optional[float]
    native_currency: Optional[str]
    is_exclusive: Optional[bool]


def _money_to_number(text: str) -> Optional[float]:
    m = _MONEY.search(text)
    if not m:
        return None
    base = float(m.group(1).replace(",", ""))
    suffix = (m.group(2) or "").lower()
    return base * _MONEY_FACTOR.get(suffix, 1)


def _currency(text: str) -> Optional[str]:
    for pattern, code in _CURRENCY_HINT:
        if pattern.search(text):
            return code
    return None


def parse_pitch_text(text: str) -> ParsedPitch:
    """Parse Asset Studio fields from pitch text. Returns only what it finds."""
    out: ParsedPitch = {}
    if not text or not text.strip():
        return out

    # Labelled lines take priority.
    for key, pattern in _LABELLED.items():
        m = pattern.search(text)
        if not m:
            continue
        value = m.group(1).strip()
        if key == "title":
            out["title_name"] = value[:300]
        elif key == "synopsis":
            out["synopsis"] = value[:2000]
        elif key == "genre":
            g = value.lower()
            match = next((cand for cand in _GENRES if cand in g), value.split(",")[0].strip())
            out["genre_tag"] = match[:60]
        elif key == "budget":
            amt = _money_to_number(value)
            if amt is not None and amt > 0:
                out["acquisition_cost_or_budget"] = amt
            cur = _currency(value)
            if cur:
                out["native_currency"] = cur
        elif key == "talent":
            # Talent is only used as a signal; we do not force a pedigree score.
            pass

    # Fallbacks when fields are unlabelled.
    if "title_name" not in out:
        # First non-empty line, trimmed, as a title candidate.
        for line in text.splitlines():
            s = line.strip()
            if s:
                out["title_name"] = s[:300]
                break
    if "genre_tag" not in out:
        low = text.lower()
        match = next((g for g in _GENRES if g in low), None)
        if match:
            out["genre_tag"] = match
    if "acquisition_cost_or_budget" not in out:
        amt = _money_to_number(text)
        if amt is not None and amt > 0:
            out["acquisition_cost_or_budget"] = amt
    if "native_currency" not in out:
        cur = _currency(text)
        if cur:
            out["native_currency"] = cur

    # Exclusivity hint.
    low = text.lower()
    if "exclusive" in low:
        out["is_exclusive"] = "non-exclusive" not in low and "non exclusive" not in low

    return out