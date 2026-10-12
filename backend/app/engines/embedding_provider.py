"""Embedding provider selection (production wiring point).

The EmbeddingProvider protocol (see app.engines.feature_extraction) lets the
1536-dim Narrative_DNA model be swapped without touching the extraction engine.
This module centralizes *which* provider is used so there is a single,
config-driven production wiring point:

* "deterministic" (default) -> DeterministicEmbeddingProvider, a dependency-free
  reproducible provider suitable for local/offline use, tests, and demos. It is
  NOT a semantic embedding.
* "openai" -> a real NLP embedding model reached over HTTP. Selecting it
  requires CINEROI_EMBEDDING_API_KEY (and optionally CINEROI_EMBEDDING_MODEL /
  CINEROI_EMBEDDING_BASE_URL). The adapter is intentionally left for the
  production integrator to complete against the chosen vendor API -- the point
  is that it plugs in here, behind the same protocol, with no caller changes.

Production rollout: set CINEROI_EMBEDDING_PROVIDER=openai and supply the API key
via your secrets manager. Until then the deterministic provider keeps the whole
pipeline runnable end to end.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.engines.feature_extraction import (
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
)

__all__ = ["get_embedding_provider", "EmbeddingProviderNotConfiguredError"]


class EmbeddingProviderNotConfiguredError(RuntimeError):
    """Raised when a non-local provider is selected without required credentials."""


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Return the embedding provider selected by configuration.

    Defaults to the deterministic provider so the system is always runnable.
    A production deployment selects a real model via CINEROI_EMBEDDING_PROVIDER.
    """
    settings = settings or get_settings()
    provider = (settings.embedding_provider or "deterministic").strip().lower()

    if provider in ("deterministic", "local", "", "demo"):
        return DeterministicEmbeddingProvider()

    if provider in ("openai", "http", "remote"):
        if not settings.embedding_api_key:
            raise EmbeddingProviderNotConfiguredError(
                "CINEROI_EMBEDDING_PROVIDER requested a remote model but "
                "CINEROI_EMBEDDING_API_KEY is not set. Supply the key via your "
                "secrets manager, or set CINEROI_EMBEDDING_PROVIDER=deterministic."
            )
        # Production integrator: implement a thin BaseEmbeddingProvider subclass
        # that calls the vendor embeddings API here and returns a 1536-length
        # vector with every component in [-1.0, 1.0]. It plugs in behind the
        # EmbeddingProvider protocol with no caller changes.
        raise EmbeddingProviderNotConfiguredError(
            "Remote embedding provider adapter is a documented production wiring "
            "point and is not implemented in this build. See docs/PRODUCTION.md."
        )

    raise EmbeddingProviderNotConfiguredError(
        f"Unknown CINEROI_EMBEDDING_PROVIDER={provider!r}. "
        "Expected 'deterministic' or 'openai'."
    )