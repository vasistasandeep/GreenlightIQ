"""Application configuration and settings.

Settings are loaded from environment variables (and an optional ``.env`` file)
via pydantic-settings. A cached accessor (:func:`get_settings`) provides a single
shared instance across the application.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings.

    Values default to local-development-friendly placeholders so the app can
    boot without a fully provisioned environment. Production deployments supply
    real values through environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="CINEROI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "CineROI AI"
    environment: str = Field(default="development")
    debug: bool = Field(default=True)
    api_v1_prefix: str = "/api/v1"

    # --- CORS / host hardening (production) ---
    #: Allowed browser origins for the API. Empty list = same-origin only
    #: (no cross-origin browser access). Production sets the frontend origin(s),
    #: e.g. CINEROI_CORS_ALLOW_ORIGINS=["https://app.example.com"].
    cors_allow_origins: list[str] = Field(default_factory=list)
    #: Host/Host-header allowlist enforced by TrustedHostMiddleware. "*" (the
    #: default) accepts any host and is intended for local/dev only; production
    #: pins the real hostname(s), e.g. ["app.example.com"].
    trusted_hosts: list[str] = Field(default_factory=lambda: ["*"])

    # --- Base currency (R21 canonicalization) ---
    base_currency: str = "USD"

    # --- Database (PostgreSQL 16 + pgvector, async psycopg driver) ---
    database_url: str = Field(
        default="postgresql+psycopg://cineroi:cineroi@localhost:5432/cineroi",
    )

    # --- Task queue broker / result backend (Celery + Redis) ---
    broker_url: str = Field(default="redis://localhost:6379/0")
    result_backend_url: str = Field(default="redis://localhost:6379/1")

    # --- Embedding provider (R2.1 Narrative_DNA; production wiring point) ---
    #: Which embedding model powers Narrative_DNA extraction. "deterministic"
    #: (default) needs no external service and is used for local/dev/demo; set
    #: "openai" in production and supply embedding_api_key via a secrets manager.
    embedding_provider: str = Field(default="deterministic")
    embedding_api_key: str | None = Field(default=None)
    embedding_model: str = Field(default="text-embedding-3-small")
    embedding_base_url: str | None = Field(default=None)

    # --- Security / session (task 14, Requirement 19) ---
    secret_key: str = Field(default="change-me-in-production")
    session_idle_timeout_minutes: int = Field(default=30)
    access_token_algorithm: str = "HS256"
    #: Expected audience/issuer the SSO identity provider stamps on OIDC/SAML
    #: assertions. The Auth_Service rejects assertions whose audience does not
    #: match (R19.1). ``None`` disables the audience check (local/dev only).
    sso_audience: str | None = Field(default=None)
    #: Shared signing secret for internal service-to-service API credentials
    #: (R19.5). Distinct from ``secret_key`` so a leaked user-session key does
    #: not grant service identity (and vice versa). Falls back to ``secret_key``
    #: when unset so the app still boots in local/dev.
    service_credential_secret: str | None = Field(default=None)

    # --- Encryption at rest (R28.1) ---
    #: Base64 url-safe 32-byte Fernet key used to encrypt sensitive column
    #: values (unreleased scripts, deal terms, PII). When unset, the
    #: EncryptedType decorator raises on use rather than silently storing
    #: plaintext — generate one with
    #: ``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``.
    encryption_key: str | None = Field(default=None)
    #: When True (default), using an encrypted column without a configured
    #: ``encryption_key`` is a hard error. Set False only in local/dev to allow
    #: a transparent passthrough that stores values unencrypted (never in prod).
    encryption_required: bool = Field(default=True)

    # --- Data retention (R28.3) ---
    #: Default action applied to records whose retention window has elapsed:
    #: ``"purge"`` deletes them, ``"archive"`` moves them to cold storage.
    retention_default_action: str = Field(default="archive")
    #: Configurable retention windows, in days, keyed by data category. A value
    #: of ``None`` (or an absent key) means "retain indefinitely" for that
    #: category. Overridable per-category via ``CINEROI_RETENTION_PERIODS``
    #: (JSON object) in the environment.
    retention_periods_days: dict[str, int | None] = Field(
        default_factory=lambda: {
            "unreleased_script": 1825,  # 5 years
            "deal_terms": 2555,  # 7 years
            "pii": 1095,  # 3 years
            "audit_log": 2555,  # 7 years (append-only; archived, never purged)
            "market_telemetry_cache": 90,
            "job": 180,
        }
    )

    # --- Logging ---
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)

    @property
    def is_production(self) -> bool:
        """True when running in a production-like environment."""
        return self.environment.strip().lower() in ("production", "prod", "staging")

    def production_safety_errors(self) -> list[str]:
        """Return a list of insecure-configuration problems for a prod deploy.

        Empty list means the configuration is safe to run in production. The
        app refuses to start when this is non-empty and ``is_production`` is
        True (fail fast, never boot a prod process with dev defaults).
        """
        errors: list[str] = []
        if not self.is_production:
            return errors

        if self.debug:
            errors.append("CINEROI_DEBUG must be false in production.")
        if self.secret_key in ("", "change-me-in-production"):
            errors.append("CINEROI_SECRET_KEY must be set to a strong unique value.")
        if len(self.secret_key) < 32:
            errors.append("CINEROI_SECRET_KEY must be at least 32 characters.")
        if self.encryption_required and not self.encryption_key:
            errors.append(
                "CINEROI_ENCRYPTION_KEY must be set when encryption is required."
            )
        if not self.encryption_required:
            errors.append(
                "CINEROI_ENCRYPTION_REQUIRED must be true in production "
                "(unencrypted passthrough is dev-only)."
            )
        if "localhost" in self.database_url or "cineroi:cineroi@" in self.database_url:
            errors.append(
                "CINEROI_DATABASE_URL still points at the local/dev database "
                "with default credentials."
            )
        if self.trusted_hosts == ["*"]:
            errors.append(
                "CINEROI_TRUSTED_HOSTS must pin real hostname(s) (not '*')."
            )
        if self.sso_audience is None:
            errors.append(
                "CINEROI_SSO_AUDIENCE must be set so SSO assertions are validated."
            )
        return errors


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
