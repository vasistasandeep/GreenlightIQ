"""Pure currency-normalization domain functions (PBT target).

Multi-currency normalization for the Guardrails_Engine (Requirement 21).

These functions are pure: no database access and no I/O. The engine layer is
responsible for looking up the applicable ``exchange_rates`` row and passing the
rate (value + date, and optionally its id) into these helpers. Here we only do
the deterministic arithmetic and carry the rate provenance back out so the
engine can persist ``normalized_cost_usd``, ``exchange_rate_id`` and the rate
date on the financial projection (R21.2, R21.4).

Design references:
- ``normalized_cost_usd = acquisition_cost * rate`` rounded to 2 dp
  (``financial_projections.normalized_cost_usd`` is ``NUMERIC(16,2)``).
- ``exchange_rates.rate`` is ``NUMERIC(18,8)`` with a ``rate_date`` (DATE).
- A missing rate (R21.5) raises :class:`MissingExchangeRateError`; the engine
  maps this to the ``EXCHANGE_RATE_UNAVAILABLE`` (HTTP 422) error envelope and
  rejects the valuation without persisting normalized values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Union

__all__ = [
    "BASE_CURRENCY",
    "USD_QUANTUM",
    "MissingExchangeRateError",
    "ExchangeRate",
    "NormalizedCost",
    "normalize_to_usd",
]

# Canonical reporting currency (Base_Currency) that all costs normalize into.
BASE_CURRENCY = "USD"

# Currency amounts are carried to 2 decimal places (NUMERIC(16,2)).
USD_QUANTUM = Decimal("0.01")

Number = Union[Decimal, int, str]


class MissingExchangeRateError(Exception):
    """Raised when a required exchange rate is unavailable (R21.5).

    The engine catches this to reject the valuation without persisting any
    normalized values and to surface a descriptive ``EXCHANGE_RATE_UNAVAILABLE``
    error identifying the currency and (optionally) rate date that could not be
    resolved.
    """

    def __init__(
        self,
        from_currency: Optional[str] = None,
        to_currency: str = BASE_CURRENCY,
        rate_date: Optional[date] = None,
    ) -> None:
        self.from_currency = from_currency
        self.to_currency = to_currency
        self.rate_date = rate_date

        who = from_currency or "the required currency"
        when = f" on {rate_date.isoformat()}" if rate_date is not None else ""
        super().__init__(
            f"No exchange rate available to convert {who} to {to_currency}{when}."
        )


@dataclass(frozen=True)
class ExchangeRate:
    """A dated exchange rate from a native currency into the base currency.

    Carries the provenance the engine must persist alongside the normalized
    amount (R21.4): the rate value, the rate date, and optionally the
    ``exchange_rate_id`` of the originating ``exchange_rates`` row.
    """

    rate: Decimal
    rate_date: date
    from_currency: Optional[str] = None
    to_currency: str = BASE_CURRENCY
    exchange_rate_id: Optional[str] = None


@dataclass(frozen=True)
class NormalizedCost:
    """Result of normalizing a native cost into the base currency.

    Carries the normalized USD amount together with the rate value, rate date,
    and (if provided) the ``exchange_rate_id`` so the engine can persist
    ``normalized_cost_usd`` + ``exchange_rate_id`` + rate date on the projection.
    """

    amount_usd: Decimal
    rate: Decimal
    rate_date: date
    from_currency: Optional[str] = None
    to_currency: str = BASE_CURRENCY
    exchange_rate_id: Optional[str] = None


def _to_decimal(value: Number) -> Decimal:
    """Coerce a numeric input to ``Decimal`` without binary-float error.

    ``float`` is intentionally not accepted: currency math must stay exact.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # bool is an int subclass; reject it explicitly.
        raise TypeError("cost and rate must be numeric, not bool")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    raise TypeError(
        f"cost and rate must be Decimal, int, or str; got {type(value).__name__}"
    )


def normalize_to_usd(
    cost: Number,
    rate: Union[ExchangeRate, Number, None],
    *,
    rate_date: Optional[date] = None,
    from_currency: Optional[str] = None,
    exchange_rate_id: Optional[str] = None,
) -> NormalizedCost:
    """Normalize a native-currency cost into base-currency (USD).

    Computes ``amount_usd = cost * rate`` rounded half-up to 2 decimal places
    and returns a :class:`NormalizedCost` carrying the normalized amount plus
    the rate value, rate date, and (if supplied) the ``exchange_rate_id`` so the
    engine can persist them (R21.2, R21.4).

    The rate may be supplied either as an :class:`ExchangeRate` (which also
    carries the rate date and provenance) or as a bare numeric value together
    with the ``rate_date`` keyword.

    Args:
        cost: The acquisition cost in its native currency.
        rate: An :class:`ExchangeRate`, a bare numeric rate value, or ``None``
            when the required rate is unavailable.
        rate_date: The rate date, required when ``rate`` is a bare numeric value.
        from_currency: Optional native currency code, used only for error
            context / provenance when ``rate`` is a bare value.
        exchange_rate_id: Optional id of the originating ``exchange_rates`` row.

    Returns:
        A :class:`NormalizedCost` with the USD amount and rate provenance.

    Raises:
        MissingExchangeRateError: If ``rate`` is ``None`` (R21.5).
        ValueError: If a bare numeric rate is supplied without a ``rate_date``.
    """
    if rate is None:
        raise MissingExchangeRateError(
            from_currency=from_currency,
            rate_date=rate_date,
        )

    cost_dec = _to_decimal(cost)

    if isinstance(rate, ExchangeRate):
        rate_value = rate.rate
        effective_date = rate.rate_date
        effective_from = rate.from_currency if rate.from_currency is not None else from_currency
        effective_to = rate.to_currency
        effective_id = rate.exchange_rate_id if rate.exchange_rate_id is not None else exchange_rate_id
    else:
        rate_value = _to_decimal(rate)
        if rate_date is None:
            raise ValueError(
                "rate_date is required when rate is provided as a bare value"
            )
        effective_date = rate_date
        effective_from = from_currency
        effective_to = BASE_CURRENCY
        effective_id = exchange_rate_id

    amount_usd = (cost_dec * rate_value).quantize(USD_QUANTUM, rounding=ROUND_HALF_UP)

    return NormalizedCost(
        amount_usd=amount_usd,
        rate=rate_value,
        rate_date=effective_date,
        from_currency=effective_from,
        to_currency=effective_to,
        exchange_rate_id=effective_id,
    )
