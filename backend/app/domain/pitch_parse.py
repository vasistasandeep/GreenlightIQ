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

# --- Advanced driver recognition (Driver_Input_Capture, Component D) ---------
# Best-effort recognition of franchise / release-window / source-IP /
# production-stage cues. Recognized facts are surfaced for pre-fill; anything
# unrecognized is omitted (never guessed) and nothing here is ever persisted.

# Franchise cue: a sequel / entry-number signal. The capture groups hold any
# recognized numeric entry (season N / part N / chapter N) for ``franchise_order``.
_FRANCHISE = re.compile(
    r"\b(?:sequel|season\s*(\d+)|part\s+(II|III|IV|V|2|3|4|5)|chapter\s+(\d+))\b",
    re.I,
)

# Roman-numeral entry numbers that appear in "part II" style cues.
_ROMAN_ORDER = {"ii": 2, "iii": 3, "iv": 4, "v": 5}

# Release window cues -> Release_Window_Set member. First/most-specific wins.
_RELEASE_WINDOW = [
    (re.compile(r"\bday[\s-]and[\s-]date\b", re.I), "DAY_AND_DATE"),
    (re.compile(r"\b(?:60|90)[\s-]day|theatrical[^.\n]*60", re.I), "THEATRICAL_60D_PLUS"),
    (re.compile(r"\b30[\s-]day theatrical|theatrical window\b", re.I), "THEATRICAL_30D"),
    (re.compile(r"\btheatrical release\b", re.I), "THEATRICAL_30D"),
    (
        re.compile(r"\b(?:direct[\s-]to[\s-]streaming|streaming[\s-]only)\b", re.I),
        "DIRECT_TO_STREAMING",
    ),
]

# Source-IP provenance cues -> Source_IP_Provenance_Set member.
_SOURCE_IP = [
    (re.compile(r"\b(?:based on the|adapted from the)?\s*bestsell", re.I), "BESTSELLER_BOOK"),
    (re.compile(r"\btrue[\s-]crime\b", re.I), "TRUE_CRIME_IP"),
    (re.compile(r"\b(?:webtoon|manga|manhwa)\b", re.I), "WEBTOON_MANGA"),
    (re.compile(r"\bpublic[\s-]domain\b", re.I), "PUBLIC_DOMAIN"),
    (re.compile(r"\boriginal screenplay\b", re.I), "ORIGINAL_SCREENPLAY"),
]

# Production-stage cues -> Production_Stage member. Most-specific (later-stage)
# cues are ordered first so an "acquisition-ready screener" is not mistaken for
# a "concept".
_STAGE = [
    (re.compile(r"\bacquisition[\s-]ready|screener\b", re.I), "ACQUISITION_READY"),
    (re.compile(r"\bfestival (?:preview|premiere|cut)\b", re.I), "FESTIVAL_PREVIEW"),
    (re.compile(r"\bin production|principal photography\b", re.I), "IN_PRODUCTION"),
    (re.compile(r"\bconcept|script stage|in development\b", re.I), "CONCEPT_SCRIPT"),
]


class ParsedPitch(TypedDict, total=False):
    """Best-effort fields parsed from pitch text; any field may be absent."""

    title_name: Optional[str]
    synopsis: Optional[str]
    genre_tag: Optional[str]
    acquisition_cost_or_budget: Optional[float]
    native_currency: Optional[str]
    is_exclusive: Optional[bool]
    # Advanced driver pre-fill facts (recognized only; never persisted here).
    is_franchise: bool | None
    franchise_order: int | None
    release_window: str | None
    source_ip_provenance: str | None
    production_stage: str | None


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


def _first_match(text: str, table: list[tuple[re.Pattern[str], str]]) -> str | None:
    """Return the member for the first matching pattern in a cue table."""
    for pattern, member in table:
        if pattern.search(text):
            return member
    return None


def _recognize_franchise(out: ParsedPitch, text: str) -> None:
    """Set ``is_franchise`` / ``franchise_order`` from a sequel/entry cue."""
    m = _FRANCHISE.search(text)
    if not m:
        return
    out["is_franchise"] = True
    # Capture groups: 1=season N, 2=part (roman or arabic), 3=chapter N.
    season, part, chapter = m.group(1), m.group(2), m.group(3)
    order: int | None = None
    if season is not None:
        order = int(season)
    elif part is not None:
        order = _ROMAN_ORDER.get(part.lower(), None)
        if order is None and part.isdigit():
            order = int(part)
    elif chapter is not None:
        order = int(chapter)
    if order is not None and order >= 1:
        out["franchise_order"] = order


def _recognize_drivers(out: ParsedPitch, text: str) -> None:
    """Pre-fill the advanced driver facts recognizable from pitch text.

    Only recognized facts are set; anything unrecognized is left absent (no
    guessing). This never persists - the caller returns the facts for the user
    to review and edit in the Asset Studio form.
    """
    _recognize_franchise(out, text)

    release_window = _first_match(text, _RELEASE_WINDOW)
    if release_window is not None:
        out["release_window"] = release_window

    source_ip = _first_match(text, _SOURCE_IP)
    if source_ip is not None:
        out["source_ip_provenance"] = source_ip

    stage = _first_match(text, _STAGE)
    if stage is not None:
        out["production_stage"] = stage


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

    # Advanced driver pre-fill (franchise / release window / source IP / stage).
    _recognize_drivers(out, text)

    return out