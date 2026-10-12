"""Column-level encryption at rest for sensitive data (R28.1).

The platform stores sensitive material — unreleased scripts, deal/license terms,
and PII — and must encrypt it at rest (R28.1). The design permits either
column-level/pgcrypto or storage-level encryption; this module implements the
column-level approach so protection is enforced in application code regardless
of how the underlying PostgreSQL volume is provisioned.

Two pieces are provided:

* :class:`FernetEncryptor` — a thin wrapper over
  :class:`cryptography.fernet.Fernet` (AES-128-CBC + HMAC authentication) keyed
  from :attr:`~app.core.config.Settings.encryption_key`. Values are encrypted to
  a URL-safe base64 token and transparently decrypted on read.
* :class:`EncryptedString` / :class:`EncryptedJSON` — SQLAlchemy
  ``TypeDecorator`` s that encrypt on the way to the database and decrypt on the
  way out, so an ORM column declared with one of them stores only ciphertext at
  rest while the Python attribute reads/writes plaintext.

Key management (R28.1)
----------------------
The symmetric key comes from ``CINEROI_ENCRYPTION_KEY`` (a URL-safe base64
32-byte Fernet key). When no key is configured:

* with ``CINEROI_ENCRYPTION_REQUIRED=true`` (the default) any attempt to encrypt
  or decrypt raises :class:`EncryptionNotConfiguredError` — the platform refuses
  to silently persist sensitive data as plaintext;
* with ``CINEROI_ENCRYPTION_REQUIRED=false`` (local/dev only) the column types
  fall back to a transparent passthrough that stores plaintext, so the schema
  stays usable without a provisioned key. This must never be used in production.

Generate a key with::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.core.config import Settings, get_settings

__all__ = [
    "EncryptionError",
    "EncryptionNotConfiguredError",
    "DecryptionError",
    "FernetEncryptor",
    "get_encryptor",
    "EncryptedString",
    "EncryptedJSON",
]


class EncryptionError(Exception):
    """Base class for encryption/decryption failures."""


class EncryptionNotConfiguredError(EncryptionError):
    """Raised when encryption is required but no key is configured (R28.1).

    Signals a misconfiguration: a sensitive column was read or written while
    ``CINEROI_ENCRYPTION_REQUIRED`` is true but ``CINEROI_ENCRYPTION_KEY`` is
    absent. The platform refuses to store sensitive data in the clear.
    """


class DecryptionError(EncryptionError):
    """Raised when a stored ciphertext cannot be decrypted.

    Indicates the stored token is corrupt or was produced with a different key
    (e.g. after an unmanaged key rotation). Surfaced rather than silently
    returning plaintext so tampering/misconfiguration is never hidden.
    """


class FernetEncryptor:
    """Symmetric authenticated encryptor over a configured Fernet key.

    Encrypts ``str`` plaintext to a URL-safe base64 token and reverses it on
    decrypt. Fernet provides AES-128 in CBC mode with an HMAC authentication
    tag, so tampered ciphertext is rejected on read.
    """

    def __init__(self, key: str) -> None:
        if not key:
            raise EncryptionNotConfiguredError(
                "An encryption key is required to construct a FernetEncryptor."
            )
        try:
            self._fernet = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
        except (ValueError, TypeError) as exc:
            raise EncryptionError(
                "CINEROI_ENCRYPTION_KEY is not a valid url-safe base64 32-byte "
                "Fernet key. Generate one with "
                "`python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"`."
            ) from exc

    def encrypt(self, plaintext: str) -> str:
        """Return a URL-safe base64 ciphertext token for ``plaintext``."""
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, token: str) -> str:
        """Return the plaintext for a ciphertext ``token``.

        Raises:
            DecryptionError: The token is corrupt or was produced with a
                different key.
        """
        try:
            plaintext = self._fernet.decrypt(
                token.encode("utf-8") if isinstance(token, str) else token
            )
        except (InvalidToken, ValueError, TypeError) as exc:
            raise DecryptionError(
                "Failed to decrypt a stored value; the ciphertext is corrupt or "
                "was encrypted with a different key."
            ) from exc
        return plaintext.decode("utf-8")


@lru_cache
def _build_encryptor(key: str | None) -> FernetEncryptor | None:
    """Build (and cache) a :class:`FernetEncryptor` for ``key``.

    Keyed on the raw key string so the Fernet instance is constructed once per
    configured key and rebuilt if the key changes (e.g. across tests).
    """
    if not key:
        return None
    return FernetEncryptor(key)


def get_encryptor(settings: Settings | None = None) -> FernetEncryptor | None:
    """Return the process-wide :class:`FernetEncryptor`, or ``None`` if unset.

    Resolves the key from settings. Returns ``None`` when no key is configured
    (the caller decides whether that is a hard error based on
    ``encryption_required``). The underlying Fernet instance is cached per key.
    """
    settings = settings or get_settings()
    return _build_encryptor(settings.encryption_key)


def _resolve_encryptor() -> FernetEncryptor | None:
    """Resolve the encryptor, enforcing the ``encryption_required`` policy.

    Returns the encryptor when a key is configured. When no key is configured,
    raises :class:`EncryptionNotConfiguredError` if encryption is required, or
    returns ``None`` (passthrough) when it is explicitly not required.
    """
    settings = get_settings()
    encryptor = get_encryptor(settings)
    if encryptor is None and settings.encryption_required:
        raise EncryptionNotConfiguredError(
            "Sensitive column access requires CINEROI_ENCRYPTION_KEY to be set "
            "(CINEROI_ENCRYPTION_REQUIRED is true). Configure a key or, for "
            "local development only, set CINEROI_ENCRYPTION_REQUIRED=false."
        )
    return encryptor


class EncryptedString(TypeDecorator):
    """A ``TEXT`` column whose value is encrypted at rest (R28.1).

    Binds a Python ``str`` by encrypting it to a ciphertext token before it is
    written, and decrypts the stored token back to ``str`` on load. Use for
    free-text sensitive fields such as unreleased scripts and PII.

    When encryption is not configured and ``encryption_required`` is false the
    value passes through unchanged (local/dev only); when it is required a
    missing key raises :class:`EncryptionNotConfiguredError`.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        encryptor = _resolve_encryptor()
        plaintext = value if isinstance(value, str) else str(value)
        if encryptor is None:
            # Passthrough (encryption_required is false).
            return plaintext
        return encryptor.encrypt(plaintext)

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        encryptor = _resolve_encryptor()
        if encryptor is None:
            return value
        return encryptor.decrypt(value)


class EncryptedJSON(TypeDecorator):
    """A ``TEXT`` column holding a JSON-serializable value, encrypted at rest.

    Serializes the Python value to JSON, encrypts the JSON string, and stores
    the ciphertext; reverses on load. Use for structured sensitive data such as
    deal/license terms. The underlying storage is encrypted ``TEXT`` rather than
    JSONB because ciphertext is opaque to the database (it cannot be indexed or
    queried as JSON while encrypted).
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        encryptor = _resolve_encryptor()
        serialized = json.dumps(value, separators=(",", ":"), sort_keys=True)
        if encryptor is None:
            return serialized
        return encryptor.encrypt(serialized)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        encryptor = _resolve_encryptor()
        serialized = value if encryptor is None else encryptor.decrypt(value)
        return json.loads(serialized)
