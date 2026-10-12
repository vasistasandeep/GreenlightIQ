#!/usr/bin/env bash
# Generate strong production secrets for .env.prod. Run once per environment.
set -euo pipefail
echo "# Paste these into .env.prod (keep them secret, never commit):"
echo "CINEROI_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
echo "CINEROI_SERVICE_CREDENTIAL_SECRET=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
echo "CINEROI_ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"