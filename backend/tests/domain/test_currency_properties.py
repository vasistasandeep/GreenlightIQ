"""Property-based tests for multi-currency normalization into Base_Currency.

# Feature: cineroi-ai, Property 24: Currency normalization round-trip
# Feature: cineroi-ai, Property 25: Missing exchange rate rejection

Properties 24 and 25 (design.md) -- Validates: Requirements 21.1, 21.2, 21.4, 21.5.

* R21.1 / R21.2 / R21.4: for any native acquisition cost, supported currency,
  and dated exchange rate, ``normalize_to_usd`` yields ``amount_usd ==
  round(cost * rate, 2)`` and the returned :class:`NormalizedCost` carries the
  rate value and rate date as provenance. Dividing the normalized amount by the
  same rate recovers the native cost within rounding tolerance.
* R21.5: when the required rate is unavailable (``None``), ``normalize_to_usd``
  raises :class:`MissingExchangeRateError` and produces no normalized value.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.currency import (
    BASE_CURRENCY,
    USD_QUANTUM,
    ExchangeRate,
    MissingExchangeRateError,
    NormalizedCost,
    normalize_to_usd,
)

# The module rejects floats to keep currency math exact, so every numeric input
# is drawn as a Decimal. Costs are strictly positive native amounts; the schema
# bounds acquisition cost at 999,999,999.99 (NUMERIC(14,2)) so 2 decimal places
# and that ceiling model the real input space.
_cost = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999999.99"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)
# Exchange rates are stored as NUMERIC(18,8): strictly positive, up to 8 dp.
# A broad but finite span covers weak-to-strong currencies (e.g. INR->USD at
# ~0.012 through to high-value conversions) without overflowing the Decimal
# context during multiplication / the reverse division.
_rate = st.decimals(
    min_value=Decimal("0.00000001"),
    max_value=Decimal("1000000"),
    allow_nan=False,
    allow_infinity=False,
    places=8,
)
# Supported native currencies (R21.1) plus other three-letter codes.
_currency = st.sampled_from(["INR", "USD", "EUR", "GBP"])
# A plausible range of rate dates for provenance.
_rate_date = st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31))


# Feature: cineroi-ai, Property 24: Currency normalization round-trip
@settings(max_examples=150)
@given(cost=_cost, rate=_rate, rate_date=_rate_date, currency=_currency)
def test_normalize_round_trip_with_exchange_rate(
    cost: Decimal, rate: Decimal, rate_date: date, currency: str
) -> None:
    """R21.1/R21.2/R21.4: normalized amount == round(cost*rate, 2); provenance
    (rate value + rate date) is carried; reverse division recovers the cost."""
    xr = ExchangeRate(rate=rate, rate_date=rate_date, from_currency=currency)
    result = normalize_to_usd(cost, xr)

    assert isinstance(result, NormalizedCost)

    # R21.2: amount_usd is exactly cost * rate rounded HALF_UP to 2 dp.
    expected = (cost * rate).quantize(USD_QUANTUM, rounding=ROUND_HALF_UP)
    assert result.amount_usd == expected

    # The rounding: no finer precision than 2 decimal places.
    assert result.amount_usd == result.amount_usd.quantize(
        USD_QUANTUM, rounding=ROUND_HALF_UP
    )

    # R21.4: provenance -- the exact rate value and rate date are recorded.
    assert result.rate == rate
    assert result.rate_date == rate_date
    assert result.from_currency == currency
    assert result.to_currency == BASE_CURRENCY

    # Round-trip: dividing the normalized amount by the same rate recovers the
    # native cost. Tolerance is half a USD quantum (the rounding of amount_usd)
    # propagated back through the division by the rate.
    recovered = result.amount_usd / rate
    tolerance = (USD_QUANTUM / 2) / rate
    assert abs(recovered - cost) <= tolerance


# Feature: cineroi-ai, Property 24: Currency normalization round-trip
@settings(max_examples=150)
@given(cost=_cost, rate=_rate, rate_date=_rate_date, currency=_currency)
def test_normalize_round_trip_with_bare_rate(
    cost: Decimal, rate: Decimal, rate_date: date, currency: str
) -> None:
    """R21.2/R21.4: a bare numeric rate + rate_date keyword produces the same
    normalized amount and records the supplied provenance."""
    result = normalize_to_usd(
        cost, rate, rate_date=rate_date, from_currency=currency
    )

    expected = (cost * rate).quantize(USD_QUANTUM, rounding=ROUND_HALF_UP)
    assert result.amount_usd == expected
    assert result.rate == rate
    assert result.rate_date == rate_date
    assert result.from_currency == currency


# Feature: cineroi-ai, Property 25: Missing exchange rate rejection
@settings(max_examples=150)
@given(cost=_cost, rate_date=_rate_date, currency=_currency)
def test_normalize_rejects_missing_rate(
    cost: Decimal, rate_date: date, currency: str
) -> None:
    """R21.5: a None rate raises MissingExchangeRateError and yields no value."""
    with pytest.raises(MissingExchangeRateError):
        normalize_to_usd(
            cost, None, rate_date=rate_date, from_currency=currency
        )


# Feature: cineroi-ai, Property 24: Currency normalization round-trip
def test_normalize_known_example() -> None:
    """R21.2 (anchor example): INR 100,000,000 at 0.012 -> USD 1,200,000.00."""
    xr = ExchangeRate(
        rate=Decimal("0.012"),
        rate_date=date(2024, 1, 15),
        from_currency="INR",
    )
    result = normalize_to_usd(Decimal("100000000.00"), xr)
    assert result.amount_usd == Decimal("1200000.00")
    assert result.rate == Decimal("0.012")
    assert result.rate_date == date(2024, 1, 15)


# Feature: cineroi-ai, Property 24: Currency normalization round-trip
def test_normalize_half_up_rounding_example() -> None:
    """R21.2 (anchor example): 0.005 at the cent boundary rounds HALF_UP."""
    # 1.00 * 0.125 = 0.125 -> rounds HALF_UP to 0.13 at 2 dp.
    result = normalize_to_usd(
        Decimal("1.00"), Decimal("0.125"), rate_date=date(2024, 6, 1)
    )
    assert result.amount_usd == Decimal("0.13")


# Feature: cineroi-ai, Property 25: Missing exchange rate rejection
def test_missing_rate_error_identifies_currency_and_date() -> None:
    """R21.5 (anchor example): the error identifies the unavailable rate."""
    with pytest.raises(MissingExchangeRateError) as exc_info:
        normalize_to_usd(
            Decimal("500.00"),
            None,
            rate_date=date(2024, 3, 10),
            from_currency="EUR",
        )
    err = exc_info.value
    assert err.from_currency == "EUR"
    assert err.rate_date == date(2024, 3, 10)
    assert "EUR" in str(err)
