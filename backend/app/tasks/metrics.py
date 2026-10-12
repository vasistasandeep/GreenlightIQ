"""Lightweight structured metrics emission for jobs (R29.1).

The platform has no metrics backend wired yet (no Prometheus/StatsD dependency
is declared), so metrics are emitted as structured log events on a dedicated
``metrics`` logger. Each event carries a stable ``metric`` name plus typed
fields, so a log-based collector (or a future exporter that subscribes to this
logger) can derive counters, gauges, and histograms without any code change at
the call sites.

Emitting through the structured logger keeps "structured logs **and** metrics"
(R29.1) a single, uniform surface and means the behaviour is observable in
tests by capturing log records rather than reaching for a live backend.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

_log = get_logger("metrics")


def emit_counter(name: str, *, value: int = 1, **tags: Any) -> None:
    """Emit a counter increment (e.g. ``jobs.completed``) with tag fields."""
    _emit("counter", name, value=value, **tags)


def emit_gauge(name: str, *, value: float, **tags: Any) -> None:
    """Emit a gauge sample (e.g. a queue depth) with tag fields."""
    _emit("gauge", name, value=value, **tags)


def emit_timing(name: str, *, seconds: float, **tags: Any) -> None:
    """Emit a timing/histogram sample in seconds (e.g. job duration)."""
    _emit("timing", name, value=seconds, **tags)


def _emit(metric_type: str, name: str, **fields: Any) -> None:
    """Render a metric as a structured log event.

    The message string embeds the metric name/type so the stdlib-logging
    fallback (which drops structured keyword fields) still produces a parseable
    line, while structlog backends additionally retain the typed fields.
    """
    rendered = " ".join(f"{k}={v}" for k, v in fields.items())
    _log.info("metric type=%s name=%s %s", metric_type, name, rendered, **_safe(fields))


def _safe(fields: dict[str, Any]) -> dict[str, Any]:
    """Return kwargs for structlog, or empty for the stdlib fallback.

    ``logging``'s ``info`` rejects arbitrary keyword fields, so when structlog is
    unavailable the structured kwargs must be dropped; the formatted message
    above already carries the same information.
    """
    try:  # structlog loggers accept arbitrary bound keywords; stdlib does not.
        from app.core.logging import _HAS_STRUCTLOG  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive
        return {}
    return dict(fields) if _HAS_STRUCTLOG else {}
