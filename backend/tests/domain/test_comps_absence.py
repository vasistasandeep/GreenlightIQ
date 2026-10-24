"""Comps-absence property test for Driver_Input_Capture (task 5.4).

# Feature: driver-input-capture

Comps_Engine (Driver A) has no user-entered fact: the comp set is auto-retrieved
via pgvector budget-band similarity, so no capture path may ever write a comps
anchor into a title's ``source_snapshot`` (R9.1, R9.3). The shared write-side
builder :func:`app.domain.drivers.build_driver_facts` is the single seam every
capture path (Asset Studio quick-evaluate, batch CSV/JSON, pitch-parse pre-fill)
funnels through, so proving it never emits a comps anchor key proves the
guarantee for all three paths at once.

This module asserts that ``build_driver_facts`` NEVER emits a ``comps``,
``base_hours_override``, or ``base_churn_override`` key -- even when a caller
slips those entries into the raw input -- across random valid driver-fact
subsets.

Validates: Requirements 9.1, 9.3; Property 8.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain import drivers as drv
from app.domain import momentum as mom

_PRODUCTION_STAGES = sorted(mom.Production_Stage.__members__)
_IP_MEMBERS = sorted(drv.SOURCE_IP_PROVENANCE_SET)
_WINDOW_MEMBERS = sorted(drv.RELEASE_WINDOW_SET)

#: Comps-anchor keys that the write-side builder must never emit (R9.1, R9.3).
#: ``comps`` is the anchor set itself; the resolver's override outputs
#: ``base_hours_override`` / ``base_churn_override`` are the only way comps could
#: ever move an evaluation, so none of the three may appear in a written snapshot.
_COMPS_ANCHOR_KEYS: tuple[str, ...] = (
    "comps",
    "base_hours_override",
    "base_churn_override",
)

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
    """Draw a random subset of valid driver facts (every subset is error-free)."""
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


#: Comps-anchor entries a hostile / confused caller might slip into the raw input.
_slipped_comps = st.fixed_dictionaries(
    {
        "comps": st.sampled_from(
            [
                {"viewing_hours": [1, 2, 3]},
                [{"title_id": "x"}],
                "AUTO",
                42,
            ]
        ),
        "base_hours_override": st.sampled_from(["9999", 9999, Decimal("6000.00")]),
        "base_churn_override": st.sampled_from(["0.05", 0.05, Decimal("0.05")]),
    }
)


# Feature: driver-input-capture, Property 8: No comps anchor fact is ever written
@settings(max_examples=200)
@given(raw=_valid_fact_subset(), slipped=_slipped_comps)
def test_build_driver_facts_never_emits_a_comps_anchor(
    raw: dict[str, object], slipped: dict[str, object]
) -> None:
    """Validates: Requirements 9.1, 9.3

    Across random valid driver-fact subsets, even when a caller slips ``comps``,
    ``base_hours_override``, and ``base_churn_override`` into the raw mapping, the
    shared write-side builder recognizes only the twelve driver keys and emits no
    comps anchor -- and raises no error for the ignored keys.
    """
    raw_with_comps = {**raw, **slipped}

    facts, errors = drv.build_driver_facts(raw_with_comps)

    for key in _COMPS_ANCHOR_KEYS:
        assert key not in facts, f"comps anchor key {key!r} leaked into the snapshot"

    # The builder emits only the twelve known driver keys -- nothing else.
    assert set(facts) <= set(drv.DRIVER_FACT_KEYS)

    # Slipped comps keys are silently ignored, not reported as field errors:
    # they are not driver facts, so they produce neither a write nor a rejection.
    assert all(e.field not in _COMPS_ANCHOR_KEYS for e in errors)


# Feature: driver-input-capture, Property 8: No comps anchor fact is ever written
def test_comps_only_input_produces_empty_snapshot() -> None:
    """Validates: Requirements 9.1, 9.3

    An input carrying only comps-anchor keys (no driver facts) yields an empty,
    error-free result: comps is never a written fact.
    """
    facts, errors = drv.build_driver_facts(
        {
            "comps": {"viewing_hours": [1, 2, 3]},
            "base_hours_override": "9999",
            "base_churn_override": "0.05",
        }
    )
    assert facts == {}
    assert errors == []
