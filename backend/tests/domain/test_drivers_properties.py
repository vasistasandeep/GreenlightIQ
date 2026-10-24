"""Property tests for the Driver_Input_Capture shared domain module (task 1.2).

# Feature: driver-input-capture

Targets :mod:`app.domain.drivers`: the Buzz_Level mapping (bounded + monotonic
through the real :func:`app.domain.momentum.calculate_momentum`), the
out-of-bounds rejection surface (per-field reason, never written), and the
write contract (supplied facts persist under exact keys in the provider-expected
JSON type; omitted facts are absent, not defaulted).

Validates: Requirements 1.2, 2.3, 3.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7;
Properties 1, 2, 3, 4, 8.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.domain import drivers as drv
from app.domain import momentum as mom

_PRODUCTION_STAGES = sorted(mom.Production_Stage.__members__)
_IP_MEMBERS = sorted(drv.SOURCE_IP_PROVENANCE_SET)
_WINDOW_MEMBERS = sorted(drv.RELEASE_WINDOW_SET)

# Non-excluded stages where momentum actually composes a multiplier (R2.3).
_ACTIVE_STAGE = mom.Production_Stage.ACQUISITION_READY


def _multiplier_for(level: str) -> Decimal:
    """Resolve a Buzz_Level through the real momentum math at an active stage."""
    sig = drv.BUZZ_LEVEL_SIGNALS[level]
    features = mom.MomentumFeatures(
        production_stage=_ACTIVE_STAGE,
        v_trailer=sig.v_trailer,
        e_ratio=sig.e_ratio,
        s_velocity=sig.s_velocity,
    )
    result = mom.calculate_momentum(features, mom.DEFAULT_MOMENTUM_PARAMS)
    return result.multiplier


# ---------------------------------------------------------------------------
# Property 2: Buzz_Level mapping is bounded and monotonic.
# ---------------------------------------------------------------------------


# Feature: driver-input-capture, Property 2: Buzz_Level mapping is bounded and monotonic
def test_buzz_level_multipliers_are_bounded_and_monotonic() -> None:
    """Validates: Requirements 2.3

    Each of {LOW, MEDIUM, HIGH} fed through the real ``calculate_momentum`` at a
    non-excluded stage yields a multiplier within the inclusive [1.00, 1.50]
    band, and the three are monotonic non-decreasing in level.
    """
    low = _multiplier_for("LOW")
    medium = _multiplier_for("MEDIUM")
    high = _multiplier_for("HIGH")

    band_low = mom.NEUTRAL_MULTIPLIER  # 1.00
    band_high = mom.DEFAULT_MOMENTUM_PARAMS.momentum_multiplier_max  # 1.50
    for value in (low, medium, high):
        assert band_low <= value <= band_high

    assert low <= medium <= high

    # Pin the verified arithmetic from the design.
    assert low == Decimal("1.00")
    assert medium == Decimal("1.1850")
    assert high == Decimal("1.4450")


# ---------------------------------------------------------------------------
# Property 3: out-of-bounds facts are rejected with a per-field reason and never
# written; a valid sibling value in the same field persists.
# ---------------------------------------------------------------------------


# Feature: driver-input-capture, Property 3: Out-of-bounds facts rejected per-field, never written
@settings(max_examples=200)
@given(bad_order=st.integers(max_value=0))
def test_franchise_order_below_one_rejected(bad_order: int) -> None:
    """Validates: Requirements 5.2"""
    facts, errors = drv.build_driver_facts(
        {"is_franchise": True, "franchise_order": bad_order}
    )
    assert "franchise_order" not in facts
    assert any(e.field == "franchise_order" for e in errors)
    # A valid sibling value persists.
    ok_facts, ok_errors = drv.build_driver_facts(
        {"is_franchise": True, "franchise_order": 2}
    )
    assert ok_facts["franchise_order"] == 2
    assert ok_errors == []


# Feature: driver-input-capture, Property 3: Out-of-bounds facts rejected per-field, never written
@settings(max_examples=200)
@given(
    rate=st.decimals(allow_nan=False, allow_infinity=False, places=4).filter(
        lambda d: d < 0 or d > 1
    )
)
def test_completion_rate_outside_unit_interval_rejected(rate: Decimal) -> None:
    """Validates: Requirements 5.3"""
    facts, errors = drv.build_driver_facts(
        {"is_franchise": True, "parent_completion_rate": rate}
    )
    assert "parent_completion_rate" not in facts
    assert any(e.field == "parent_completion_rate" for e in errors)


# Feature: driver-input-capture, Property 3: Out-of-bounds facts rejected per-field, never written
@settings(max_examples=200)
@given(count=st.integers(max_value=0))
def test_vernacular_track_count_below_one_rejected(count: int) -> None:
    """Validates: Requirements 5.4"""
    facts, errors = drv.build_driver_facts({"vernacular_track_count": count})
    assert "vernacular_track_count" not in facts
    assert any(e.field == "vernacular_track_count" for e in errors)


# Feature: driver-input-capture, Property 3: Out-of-bounds facts rejected per-field, never written
@settings(max_examples=200)
@given(month=st.integers().filter(lambda m: m < 1 or m > 12))
def test_release_month_outside_range_rejected(month: int) -> None:
    """Validates: Requirements 5.5"""
    facts, errors = drv.build_driver_facts({"release_month": month})
    assert "release_month" not in facts
    assert any(e.field == "release_month" for e in errors)


# Feature: driver-input-capture, Property 3: Out-of-bounds facts rejected per-field, never written
@settings(max_examples=200)
@given(
    signal=st.sampled_from(("parent_title_viewing_hours", "v_trailer", "e_ratio", "s_velocity")),
    value=st.decimals(allow_nan=False, allow_infinity=False, places=4).filter(
        lambda d: d < 0
    ),
)
def test_negative_decimal_signals_rejected(signal: str, value: Decimal) -> None:
    """Validates: Requirements 5.6"""
    raw: dict[str, object] = {signal: value}
    if signal == "parent_title_viewing_hours":
        raw["is_franchise"] = True
    facts, errors = drv.build_driver_facts(raw)
    assert signal not in facts
    assert any(e.field == signal for e in errors)


# Feature: driver-input-capture, Property 3: Out-of-bounds facts rejected per-field, never written
@settings(max_examples=200)
@given(
    field=st.sampled_from(("source_ip_provenance", "release_window", "production_stage")),
    value=st.text(min_size=1, max_size=12).filter(
        lambda s: s.strip().upper()
        not in (
            drv.SOURCE_IP_PROVENANCE_SET
            | drv.RELEASE_WINDOW_SET
            | set(mom.Production_Stage.__members__)
        )
    ),
)
def test_unknown_enum_members_rejected(field: str, value: str) -> None:
    """Validates: Requirements 5.1"""
    assume(value.strip() != "")
    facts, errors = drv.build_driver_facts({field: value})
    assert field not in facts
    assert any(e.field == field for e in errors)


# ---------------------------------------------------------------------------
# Property 1 / Property 4: supplied facts persist under exact keys in the
# expected JSON type; omitted facts are absent, not defaulted.
# ---------------------------------------------------------------------------

_decimal_nonneg = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("100000"),
    allow_nan=False,
    allow_infinity=False,
    places=4,
)
_rate = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1"),
    allow_nan=False,
    allow_infinity=False,
    places=4,
)


@st.composite
def _valid_fact_subset(draw: st.DrawFn) -> dict[str, object]:
    """Draw a random subset of valid driver facts."""
    raw: dict[str, object] = {}
    if draw(st.booleans()):
        raw["is_franchise"] = True
        if draw(st.booleans()):
            raw["franchise_order"] = draw(st.integers(min_value=1, max_value=12))
        if draw(st.booleans()):
            raw["parent_title_viewing_hours"] = draw(_decimal_nonneg)
        if draw(st.booleans()):
            raw["parent_completion_rate"] = draw(_rate)
    if draw(st.booleans()):
        raw["production_stage"] = draw(st.sampled_from(_PRODUCTION_STAGES))
    for signal in ("v_trailer", "e_ratio", "s_velocity"):
        if draw(st.booleans()):
            raw[signal] = draw(_decimal_nonneg)
    if draw(st.booleans()):
        raw["source_ip_provenance"] = draw(st.sampled_from(_IP_MEMBERS))
    if draw(st.booleans()):
        raw["release_window"] = draw(st.sampled_from(_WINDOW_MEMBERS))
    if draw(st.booleans()):
        raw["release_month"] = draw(st.integers(min_value=1, max_value=12))
    if draw(st.booleans()):
        raw["vernacular_track_count"] = draw(st.integers(min_value=1, max_value=8))
    return raw


_STRING_DECIMAL_KEYS = frozenset(
    {
        "parent_title_viewing_hours",
        "parent_completion_rate",
        "v_trailer",
        "e_ratio",
        "s_velocity",
    }
)
_INT_KEYS = frozenset({"franchise_order", "release_month", "vernacular_track_count"})
_ENUM_KEYS = frozenset({"production_stage", "source_ip_provenance", "release_window"})


# Feature: driver-input-capture, Property 1: Supplied facts persist under exact keys, typed
@settings(max_examples=200)
@given(raw=_valid_fact_subset())
def test_supplied_facts_persist_under_exact_keys_in_expected_type(
    raw: dict[str, object],
) -> None:
    """Validates: Requirements 1.2, 2.3, 5.7, 6.1, 6.4"""
    facts, errors = drv.build_driver_facts(raw)
    assert errors == []

    for key, value in raw.items():
        assert key in facts, f"supplied fact {key} missing from output"
        out = facts[key]
        if key == "is_franchise":
            assert out is True
        elif key in _STRING_DECIMAL_KEYS:
            # Serialized as a string that round-trips to the same Decimal value.
            assert isinstance(out, str)
            assert Decimal(out) == Decimal(str(value))
        elif key in _INT_KEYS:
            assert isinstance(out, int) and not isinstance(out, bool)
            assert out == value
        elif key in _ENUM_KEYS:
            assert isinstance(out, str)
            assert out == str(value).strip().upper()

    # No extra / unexpected keys were invented.
    assert set(facts) <= set(drv.DRIVER_FACT_KEYS)


# Feature: driver-input-capture, Property 4: Omitted facts are absent, not neutral literals
@settings(max_examples=200)
@given(raw=_valid_fact_subset())
def test_omitted_facts_are_absent_not_defaulted(raw: dict[str, object]) -> None:
    """Validates: Requirements 1.5, 2.5, 3.4"""
    facts, errors = drv.build_driver_facts(raw)
    assert errors == []
    for key in drv.DRIVER_FACT_KEYS:
        if key not in raw:
            assert key not in facts, f"omitted fact {key} was written anyway"


# Feature: driver-input-capture, Property 4: Omitted facts are absent, not neutral literals
def test_empty_input_produces_no_keys() -> None:
    """Validates: Requirements 1.5, 2.5, 3.4, 8.5

    An input supplying no driver facts produces an empty, error-free result (a
    Neutral_Title writes nothing).
    """
    facts, errors = drv.build_driver_facts({})
    assert facts == {}
    assert errors == []


# Feature: driver-input-capture, Property 8: No comps anchor fact is ever written
@settings(max_examples=200)
@given(raw=_valid_fact_subset())
def test_no_comps_anchor_key_is_ever_written(raw: dict[str, object]) -> None:
    """Validates: Requirements 9.1, 9.3

    Even when a caller slips a ``comps`` entry into the raw mapping, the builder
    recognizes only the twelve driver keys and never emits a comps anchor.
    """
    raw_with_comps = dict(raw)
    raw_with_comps["comps"] = {"viewing_hours": [1, 2, 3]}
    raw_with_comps["base_hours_override"] = "9999"
    facts, _errors = drv.build_driver_facts(raw_with_comps)
    assert "comps" not in facts
    assert "base_hours_override" not in facts
    assert "base_churn_override" not in facts


# Feature: driver-input-capture, Property 4: Omitted facts are absent, not neutral literals
def test_lineage_parent_fields_ignored_when_not_franchise() -> None:
    """Validates: Requirements 1.6

    Parent lineage fields are considered only when ``is_franchise`` is truthy;
    with it false/unset they are omitted without error.
    """
    facts, errors = drv.build_driver_facts(
        {
            "is_franchise": False,
            "franchise_order": 3,
            "parent_title_viewing_hours": Decimal("6000"),
            "parent_completion_rate": Decimal("0.80"),
        }
    )
    assert errors == []
    assert facts == {"is_franchise": False}
