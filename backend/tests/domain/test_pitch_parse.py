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


# --- Advanced driver recognition (Driver_Input_Capture, Component D) ---------
# Representative snippets per cue -> expected recognized facts (R4.1-R4.4), and
# a no-cue deck -> no driver keys added (R4.5, R8.4).


def test_franchise_sequel_sets_flag_without_order():
    # R4.1: a bare "sequel" cue sets the flag but captures no entry number.
    p = parse_pitch_text("Title: Aurora Protocol\nThe long-awaited sequel.\n")
    assert p["is_franchise"] is True
    assert "franchise_order" not in p


def test_franchise_season_number_sets_order():
    # R4.1: "season 2" -> is_franchise + franchise_order=2.
    p = parse_pitch_text("Title: Monsoon Lanes\nSeason 2 of the hit drama.\n")
    assert p["is_franchise"] is True
    assert p["franchise_order"] == 2


def test_franchise_roman_part_sets_order():
    # R4.1: "part III" -> franchise_order=3 via roman-numeral recognition.
    p = parse_pitch_text("Title: The Ledger\nPart III of the saga.\n")
    assert p["is_franchise"] is True
    assert p["franchise_order"] == 3


def test_franchise_chapter_number_sets_order():
    p = parse_pitch_text("Title: Echoes\nChapter 4 picks up the story.\n")
    assert p["is_franchise"] is True
    assert p["franchise_order"] == 4


def test_release_window_day_and_date():
    # R4.2
    p = parse_pitch_text("Title: X\nPlanned as a day-and-date release.\n")
    assert p["release_window"] == "DAY_AND_DATE"


def test_release_window_theatrical_30d():
    # R4.2
    p = parse_pitch_text("Title: X\nStandard theatrical release first.\n")
    assert p["release_window"] == "THEATRICAL_30D"


def test_release_window_theatrical_60d_plus():
    # R4.2
    p = parse_pitch_text("Title: X\nA 90-day exclusive theatrical run.\n")
    assert p["release_window"] == "THEATRICAL_60D_PLUS"


def test_release_window_direct_to_streaming():
    # R4.2
    p = parse_pitch_text("Title: X\nDirect-to-streaming launch.\n")
    assert p["release_window"] == "DIRECT_TO_STREAMING"


def test_source_ip_bestseller():
    # R4.3
    p = parse_pitch_text("Title: X\nBased on the bestselling novel.\n")
    assert p["source_ip_provenance"] == "BESTSELLER_BOOK"


def test_source_ip_true_crime():
    # R4.3
    p = parse_pitch_text("Title: X\nA gripping true-crime story.\n")
    assert p["source_ip_provenance"] == "TRUE_CRIME_IP"


def test_source_ip_webtoon():
    # R4.3
    p = parse_pitch_text("Title: X\nAdapted from the hit webtoon.\n")
    assert p["source_ip_provenance"] == "WEBTOON_MANGA"


def test_source_ip_original_screenplay():
    # R4.3
    p = parse_pitch_text("Title: X\nAn original screenplay by a newcomer.\n")
    assert p["source_ip_provenance"] == "ORIGINAL_SCREENPLAY"


def test_production_stage_acquisition_ready():
    # R4.4
    p = parse_pitch_text("Title: X\nAn acquisition-ready screener is available.\n")
    assert p["production_stage"] == "ACQUISITION_READY"


def test_production_stage_festival_preview():
    # R4.4
    p = parse_pitch_text("Title: X\nShown as a festival preview last month.\n")
    assert p["production_stage"] == "FESTIVAL_PREVIEW"


def test_production_stage_in_production():
    # R4.4
    p = parse_pitch_text("Title: X\nCurrently in production on location.\n")
    assert p["production_stage"] == "IN_PRODUCTION"


def test_production_stage_concept():
    # R4.4
    p = parse_pitch_text("Title: X\nStill at the concept stage.\n")
    assert p["production_stage"] == "CONCEPT_SCRIPT"


def test_no_cue_deck_adds_no_driver_keys():
    # R4.5, R8.4: a deck with no recognizable driver cues adds no driver keys.
    text = (
        "Title: Plain Pitch\n"
        "Genre: Drama\n"
        "Budget: USD 10 million\n"
        "Synopsis: A quiet story about a family.\n"
    )
    p = parse_pitch_text(text)
    for key in (
        "is_franchise",
        "franchise_order",
        "release_window",
        "source_ip_provenance",
        "production_stage",
    ):
        assert key not in p


def test_recognized_facts_are_json_safe_types():
    text = (
        "Title: Big Franchise\n"
        "Season 2 of the saga, a day-and-date release.\n"
        "Based on the bestselling novel. Acquisition-ready screener.\n"
    )
    p = parse_pitch_text(text)
    for v in p.values():
        assert isinstance(v, (str, float, int, bool))
