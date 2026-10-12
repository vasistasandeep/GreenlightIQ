# CineROI AI - Production Readiness Runbook

This document covers deploying CineROI AI beyond the local demo. The application
code is complete and verified; the items below are the deployment, credential,
and infrastructure steps that only you can finish because they need real secrets
and managed infrastructure.

## 1. One-time setup

1. **Generate secrets**

   ```bash
   ./scripts/generate-secrets.sh
   ```

   Paste the three values into `.env.prod` (copy from `.env.prod.example`).

2. **Fill in `.env.prod`.** Every value is required. The backend refuses to
   boot in a production environment if any are left at a dev default - see
   `Settings.production_safety_errors()` in `backend/app/core/config.py`. The
   guard checks: debug off, strong 32+ char secret key, encryption key present
   and required, non-default database URL, pinned trusted hosts, and a set SSO
   audience.

3. **Provision managed infrastructure.** Point `CINEROI_DATABASE_URL` at a
   managed PostgreSQL 16 with the `pgvector` extension available, and the broker
   URLs at a managed Redis. The bundled `db`/`redis` containers are convenient
   defaults; a managed service is recommended for production durability.

4. **TLS certificates.** Place `fullchain.pem` and `privkey.pem` in
   `nginx/certs/` (from Let's Encrypt / your cert manager). Nginx terminates TLS
   and is the only public ingress.

## 2. Deploy

```bash
docker compose --env-file .env.prod \
  -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The production overlay: loads everything from `.env.prod`, keeps `db`/`redis`
off the public network, runs an nginx TLS proxy on 80/443, sets
`restart: always`, and applies resource limits.

Verify: `curl -fsS https://<your-host>/health` returns `"status":"ok"` with all
three components (`database`, `task_queue`, `telemetry`) up.

## 3. Integration wiring points (require your credentials)

These are deliberately abstracted so they plug in without touching core logic:

- **Embedding provider (Narrative_DNA, R2.1).** Default is a deterministic,
  dependency-free provider (dev/demo only - not semantic). For production set
  `CINEROI_EMBEDDING_PROVIDER=openai` and supply `CINEROI_EMBEDDING_API_KEY`.
  Implement the vendor call in `backend/app/engines/embedding_provider.py` as a
  thin `BaseEmbeddingProvider` subclass returning a 1536-length vector with each
  component in `[-1.0, 1.0]`. It plugs in behind the `EmbeddingProvider`
  protocol with no caller changes.
- **SSO (R19.1).** Set `CINEROI_SSO_AUDIENCE` to the audience/issuer your IdP
  stamps on OIDC/SAML assertions; the Auth_Service validates against it.
- **Secrets management.** Inject `.env.prod` values from your secrets manager
  (AWS Secrets Manager, Vault, etc.) rather than a file on disk where possible.

## 4. Pre-launch checklist

- [ ] `.env.prod` complete; `generate-secrets.sh` run; no dev defaults left
- [ ] Managed PostgreSQL 16 + pgvector reachable; migrations applied by `db-init`
- [ ] Managed Redis reachable
- [ ] TLS certs in `nginx/certs/`; HTTPS reachable; HTTP redirects to HTTPS
- [ ] `CINEROI_TRUSTED_HOSTS` and `CINEROI_CORS_ALLOW_ORIGINS` pinned to real host
- [ ] Real embedding provider configured and smoke-tested
- [ ] SSO audience set and a real login tested end to end
- [ ] `GET /health` returns ok for all three components
- [ ] Backups configured for the database; retention policy reviewed (R28.3)
- [ ] Log aggregation collecting the structured JSON logs (`CINEROI_LOG_JSON=true`)

## 5. What is NOT included (future infra work)

CI/CD pipeline, Kubernetes/managed-orchestration manifests, autoscaling,
centralized metrics/alerting dashboards, and DR/backup automation. The compose
overlay is production-shaped and sufficient for a single-host deployment; the
above are environment-specific and left to your platform team.