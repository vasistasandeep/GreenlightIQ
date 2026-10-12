"""Terminal-status webhook delivery with per-event idempotency (R23.6, R27.4).

When a job reaches a terminal status (``COMPLETED`` / ``FAILED``) the lifecycle
service fires a webhook carrying ``{job_id, status}`` (R23.6). Delivery is made
*idempotent* by a per-event dedupe key: the first delivery for a given key is
sent and the key is recorded; any repeated delivery of the same key is a no-op
(R27.4). This mirrors the "processed-event dedupe table" the design describes,
but the dedupe *store* is pluggable so the behaviour is unit-testable without a
database (an in-memory set) and swappable for a durable store in production.

The dedupe key is derived deterministically from the event identity
(:func:`build_dedupe_key`) so the same terminal event always maps to the same
key regardless of how many times it is delivered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.core.logging import get_logger
from app.tasks import metrics

_log = get_logger("webhooks")

#: Terminal statuses that trigger a webhook notification (R23.6).
TERMINAL_STATUSES = ("COMPLETED", "FAILED")


def build_dedupe_key(job_id: str | UUID, status: str) -> str:
    """Build the deterministic per-event dedupe key for a terminal event (R27.4).

    The key is a function of the event identity — the job and its terminal
    status — so every delivery of the *same* event collapses to one key, while
    distinct terminal events (different job, or the same job reported at a
    different status) remain distinct.
    """
    return f"job:{job_id}:status:{status}"


@dataclass(frozen=True)
class WebhookEvent:
    """The payload reported to webhook receivers on a terminal status (R23.6)."""

    job_id: str
    status: str

    def payload(self) -> dict[str, str]:
        """Return the JSON-serializable body ``{job_id, status}`` (R23.6)."""
        return {"job_id": self.job_id, "status": self.status}


class DedupeStore(Protocol):
    """A store of already-processed webhook dedupe keys (R27.4).

    ``add`` records a key and reports whether it was newly added. An
    implementation backed by a database ``processed_webhook_events`` table makes
    delivery idempotent across process restarts; the in-memory default is enough
    for a single worker and for tests.
    """

    def add(self, key: str) -> bool:
        """Record ``key``; return ``True`` if newly added, ``False`` if seen before."""
        ...

    def seen(self, key: str) -> bool:
        """Return whether ``key`` was already recorded."""
        ...


class InMemoryDedupeStore:
    """Process-local dedupe store backed by a ``set`` (default, test-friendly)."""

    def __init__(self) -> None:
        self._keys: set[str] = set()

    def add(self, key: str) -> bool:
        if key in self._keys:
            return False
        self._keys.add(key)
        return True

    def seen(self, key: str) -> bool:
        return key in self._keys


class Transport(Protocol):
    """Delivers a webhook payload to its receiver(s)."""

    def send(self, event: WebhookEvent) -> None:
        """Deliver the event's payload. May raise on transport failure."""
        ...


class LoggingTransport:
    """Default transport that records the delivery as a structured log line.

    No HTTP endpoint is configured in this environment, so the default transport
    simply logs the notification; swap in an HTTP transport in deployment. The
    dedupe guarantee (R27.4) is independent of the transport.
    """

    def send(self, event: WebhookEvent) -> None:
        _log.info(
            "webhook_delivery job_id=%s status=%s",
            event.job_id,
            event.status,
        )


class WebhookDispatcher:
    """Idempotent terminal-status webhook dispatcher (R23.6, R27.4).

    Collaborators are injected so the dedupe store and transport can be faked in
    tests and replaced with durable/HTTP implementations in production.
    """

    def __init__(
        self,
        *,
        store: DedupeStore | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.store: DedupeStore = store or InMemoryDedupeStore()
        self.transport: Transport = transport or LoggingTransport()

    def deliver(self, job_id: str | UUID, status: str) -> bool:
        """Deliver a terminal-status webhook exactly once per event (R23.6, R27.4).

        Returns ``True`` when this call actually sent the notification and
        ``False`` when it was suppressed as a duplicate of an already-processed
        event. Repeated calls for the same ``(job_id, status)`` therefore produce
        the same effect as a single call — a later duplicate performs no send.

        Args:
            job_id: The job whose terminal status is being reported.
            status: The terminal status (``COMPLETED`` or ``FAILED``).

        Returns:
            Whether the notification was sent on this call.
        """
        key = build_dedupe_key(job_id, status)
        if not self.store.add(key):
            _log.info("webhook_duplicate_suppressed dedupe_key=%s", key)
            metrics.emit_counter("webhooks.suppressed", status=status)
            return False

        event = WebhookEvent(job_id=str(job_id), status=status)
        self.transport.send(event)
        metrics.emit_counter("webhooks.sent", status=status)
        return True
