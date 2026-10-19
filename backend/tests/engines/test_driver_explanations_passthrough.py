"""Driver-explanation passthrough through the Guardrails_Engine (Task 12).

# Feature: content-eval-model

The Content_Eval_System threads each model's per-driver breakdown through the
engine as a purely additive seam: ``ValuationInputs`` gains one optional field
``driver_explanations: Mapping[str, Any] | None = None`` and
:func:`app.engines.guardrails._jsonable_explanation` attaches it under
``explanation["content_eval"]`` — but *only* when it is present. When the field
is ``None`` (every construction in the demo path, with no fitted version active)
the serialized explanation must be byte-identical to the pre-feature output, so
the four thresholds, the recommendation logic, and the seeded demo verdicts are
untouched (design Component 8 "Explanation passthrough").

These tests pin that contract directly on the pure serializer and the dataclass
default — no database, no async engine wiring — because the passthrough is a
pure transformation of the explanation payload.

Validates: Requirements 1.4, 5.2, 5.4, 8.2
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.churn import ChurnResult
from app.domain.recommendation import Explanation, GuardrailCheck
from app.engines.guardrails import ValuationInputs, _jsonable_explanation


# --------------------------------------------------------------------------- #
# Fixtures / builders
# --------------------------------------------------------------------------- #


def _check(
    name: str,
    *,
    computed: Decimal | None,
    threshold: Decimal,
    passed: bool,
    breached: bool,
    shortfall: Decimal | None,
    correctable: bool | None,
) -> GuardrailCheck:
    return {
        "name": name,  # type: ignore[typeddict-item]
        "computed_value": computed,
        "threshold": threshold,
        "passed": passed,
        "breached": breached,
        "shortfall_magnitude": shortfall,
        "correctable": correctable,
    }


def _explanation() -> Explanation:
    """A representative multi-check explanation (one breach, one pass)."""
    return {
        "checks": [
            _check(
                "CPVH",
                computed=Decimal("0.40"),
                threshold=Decimal("0.50"),
                passed=True,
                breached=False,
                shortfall=None,
                correctable=None,
            ),
            _check(
                "LTV_TO_COST",
                computed=Decimal("2.10"),
                threshold=Decimal("3.20"),
                passed=False,
                breached=True,
                shortfall=Decimal("0.34"),
                correctable=True,
            ),
        ],
        "dominant_factor": "LTV_TO_COST",
        "unclassifiable": False,
    }


def _churn_detail() -> ChurnResult:
    """A SUPPLIED churn result (null breakdown) to exercise the churn_model key."""
    return ChurnResult(
        churn_reduction_pct=Decimal("1.80"),
        method="SUPPLIED",
        is_borderline=False,
        breakdown=None,
        missing_features=(),
        params_source="DEFAULTS",
        unclamped=None,
        assumed_features=(),
    )


def _driver_explanations() -> dict[str, object]:
    """A representative content_eval per-driver breakdown, as the provider builds."""
    return {
        "viewing_hours": {
            "method": "FITTED",
            "version_label": "vh-fit-3",
            "label_type": "PROXY",
            "value": "118.0",
            "breakdown": {
                "base_platform_hours": "80.0",
                "normalized_rating": "22.0",
                "franchise_flag": "16.0",
                "rounding_or_bounds_adjustment": "0.0",
            },
        },
        "watch_time_elasticity": {
            "method": "FALLBACK",
            "value": "1.05",
            "breakdown": {"intercept": "1.00", "runtime": "0.05"},
        },
    }


# --------------------------------------------------------------------------- #
# ValuationInputs: the new field is optional and defaults to None
# --------------------------------------------------------------------------- #


def _minimal_inputs(**overrides: object) -> ValuationInputs:
    base: dict[str, object] = {
        "churn_reduction_value": Decimal("10000"),
        "ltv": Decimal("120"),
        "watch_time_elasticity": Decimal("1.0"),
        "cpm": Decimal("18"),
        "ad_impressions": Decimal("1000000"),
        "monthly_margin": Decimal("50000"),
    }
    base.update(overrides)
    return ValuationInputs(**base)  # type: ignore[arg-type]


def test_driver_explanations_defaults_to_none() -> None:
    """Validates: Requirements 5.2, 8.2

    Constructing ValuationInputs the way every existing caller does (no
    ``driver_explanations``) leaves the field ``None`` — the additive field is
    optional and does not disturb existing construction.
    """
    inputs = _minimal_inputs()
    assert inputs.driver_explanations is None


def test_driver_explanations_round_trips_when_set() -> None:
    """Validates: Requirements 1.4, 5.4

    When the provider populates the field, it is carried verbatim on the frozen
    dataclass.
    """
    de = _driver_explanations()
    inputs = _minimal_inputs(driver_explanations=de)
    assert inputs.driver_explanations == de


# --------------------------------------------------------------------------- #
# Demo-invariant: absent field -> byte-identical serialized explanation
# --------------------------------------------------------------------------- #


def test_none_driver_explanations_is_byte_identical_to_absent() -> None:
    """Validates: Requirements 5.2, 8.2

    The serialized explanation with ``driver_explanations=None`` must be
    byte-identical to the output produced without passing the argument at all
    (the pre-feature call shape). No ``content_eval`` key is added, so demo
    explanations do not move when no fitted version is active.
    """
    explanation = _explanation()
    churn = _churn_detail()
    mv = uuid.uuid4()

    # Pre-feature call shape (no driver_explanations argument).
    before = _jsonable_explanation(explanation, churn, mv)
    # New call shape with the field explicitly None.
    after = _jsonable_explanation(explanation, churn, mv, None)

    assert "content_eval" not in before
    assert "content_eval" not in after
    # Byte-identical: identical JSON serialization with stable key order.
    assert json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True)
    assert before == after


def test_none_driver_explanations_without_churn_is_byte_identical() -> None:
    """Validates: Requirements 5.2, 8.2

    The byte-identity also holds on the no-churn-detail path (what-if style):
    neither ``churn_model`` nor ``content_eval`` keys appear, matching the
    pre-feature payload exactly.
    """
    explanation = _explanation()

    before = _jsonable_explanation(explanation)
    after = _jsonable_explanation(explanation, None, None, None)

    assert "churn_model" not in before
    assert "content_eval" not in before
    assert json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True)


# --------------------------------------------------------------------------- #
# Present field -> attached under content_eval, existing keys unchanged
# --------------------------------------------------------------------------- #


def test_present_driver_explanations_attached_under_content_eval() -> None:
    """Validates: Requirements 1.4, 5.4, 8.2

    When ``driver_explanations`` is present it is attached verbatim under the
    ``content_eval`` key, and the existing keys (``checks``, ``dominant_factor``,
    ``unclassifiable``, and the ``churn_model`` block) are untouched — i.e. the
    passthrough only ADDS one key.
    """
    explanation = _explanation()
    churn = _churn_detail()
    mv = uuid.uuid4()
    de = _driver_explanations()

    baseline = _jsonable_explanation(explanation, churn, mv)
    with_de = _jsonable_explanation(explanation, churn, mv, de)

    # The new key carries the breakdown verbatim.
    assert with_de["content_eval"] == de

    # Every pre-existing key is byte-identical to the no-passthrough output.
    assert with_de["checks"] == baseline["checks"]
    assert with_de["dominant_factor"] == baseline["dominant_factor"]
    assert with_de["unclassifiable"] == baseline["unclassifiable"]
    assert with_de["churn_model"] == baseline["churn_model"]

    # The ONLY difference between the two payloads is the added content_eval key.
    assert set(with_de) - set(baseline) == {"content_eval"}
    assert set(baseline) - set(with_de) == set()


def test_present_driver_explanations_without_churn_model() -> None:
    """Validates: Requirements 1.4, 8.2

    content_eval can be present while churn_model is absent (no churn detail):
    only ``content_eval`` is added, ``churn_model`` is not fabricated.
    """
    explanation = _explanation()
    de = _driver_explanations()

    payload = _jsonable_explanation(explanation, None, None, de)

    assert payload["content_eval"] == de
    assert "churn_model" not in payload


# --------------------------------------------------------------------------- #
# Property: None is always demo-invariant across arbitrary explanations
# --------------------------------------------------------------------------- #

_names = st.sampled_from(["CPVH", "LTV_TO_COST", "CHURN_MITIGATION", "PAYBACK_HORIZON"])
_decimals = st.decimals(
    min_value=Decimal("0"), max_value=Decimal("1000"), allow_nan=False, allow_infinity=False, places=2
)


@st.composite
def _checks(draw: st.DrawFn) -> list[GuardrailCheck]:
    n = draw(st.integers(min_value=0, max_value=4))
    out: list[GuardrailCheck] = []
    for _ in range(n):
        breached = draw(st.booleans())
        out.append(
            _check(
                draw(_names),
                computed=draw(st.none() | _decimals),
                threshold=draw(_decimals),
                passed=not breached,
                breached=breached,
                shortfall=draw(st.none() | _decimals),
                correctable=draw(st.none() | st.booleans()),
            )
        )
    return out


@settings(deadline=None, max_examples=75)
@given(checks=_checks(), dominant=st.none() | _names, unclassifiable=st.booleans())
def test_none_passthrough_is_demo_invariant_property(
    checks: list[GuardrailCheck], dominant: str | None, unclassifiable: bool
) -> None:
    """# Feature: content-eval-model, Property: None driver_explanations is a no-op

    Validates: Requirements 5.2, 8.2

    For ANY explanation payload, serializing with ``driver_explanations=None``
    yields byte-identical JSON to the pre-feature three-argument call, and never
    introduces a ``content_eval`` key.
    """
    explanation: Explanation = {
        "checks": checks,
        "dominant_factor": dominant,
        "unclassifiable": unclassifiable,
    }

    before = _jsonable_explanation(explanation)
    after = _jsonable_explanation(explanation, None, None, None)

    assert "content_eval" not in after
    assert json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True)
