"""Tests for the pure pitch-text parser (PDF auto-fill heuristics)."""

from __future__ import annotations

from app.domain.pitch_parse import parse_pitch_text


def test_parses_labelled_fields():
    text = (
        "Title: Aurora Protocol\n"
        "Genre: Sci-Fi\n"
        "Budget: USD 42 million\n"
        "Synopsis: A rogue AI awakens aboard a derelict station.\n"
        "Exclusive SVOD rights.\n"
    )
    p = parse_pitch_text(text)
    assert p["title_name"] == "Aurora Protocol"
    assert p["genre_tag"] == "sci-fi"
    assert p["acquisition_cost_or_budget"] == 42_000_000
    assert p["native_currency"] == "USD"
    assert "rogue AI" in p["synopsis"]
    assert p["is_exclusive"] is True


def test_parses_indian_shorthand_and_currency():
    text = "Project: Monsoon Lanes\nGenre: Drama\nAsk: INR 18 Cr\n"
    p = parse_pitch_text(text)
    assert p["title_name"] == "Monsoon Lanes"
    assert p["acquisition_cost_or_budget"] == 180_000_000
    assert p["native_currency"] == "INR"


def test_non_exclusive_detected():
    p = parse_pitch_text("Title: Open Window\nNon-exclusive AVOD window.\n")
    assert p["is_exclusive"] is False


def test_empty_text_returns_empty():
    assert parse_pitch_text("") == {}
    assert parse_pitch_text("   \n  ") == {}


def test_unlabelled_first_line_is_title_fallback():
    p = parse_pitch_text("The Ledger\nA tense financial thriller.\n")
    assert p["title_name"] == "The Ledger"
    # genre inferred from the body text
    assert p.get("genre_tag") == "thriller"


def test_all_values_are_json_safe_types():
    p = parse_pitch_text("Title: X\nBudget: 1.5M\n")
    for v in p.values():
        assert isinstance(v, (str, float, int, bool))