# syntax=docker/dockerfile:1

# =============================================================================
# CineROI AI frontend image (Next.js App Router) — Requirement 18.2, 18.3
# =============================================================================
# Multi-stage build producing a minimal standalone runtime:
#   deps  -> install node_modules from the lockfile
#   build -> compile the Next.js app into .next/standalone
#   run   -> copy only the traced server bundle + static assets
# `output: "standalone"` in next.config.mjs is what makes the slim final stage
# possible.
# =============================================================================

# ---- deps: install dependencies against the lockfile --------------------------
FROM node:20-alpine AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# ---- build: compile the Next.js production bundle -----------------------------
FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./
# The public base URL is baked at build time for NEXT_PUBLIC_* vars; it can be
# overridden at build via --build-arg and defaults to the compose service name.
ARG NEXT_PUBLIC_API_BASE_URL=
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
# Where the Next.js server proxies same-origin /api and /health at runtime.
# Baked into the rewrite config at build; defaults to the compose backend host.
ARG API_BASE_URL_INTERNAL=http://backend:8000
ENV API_BASE_URL_INTERNAL=${API_BASE_URL_INTERNAL}
RUN npm run build

# ---- run: minimal standalone server ------------------------------------------
FROM node:20-alpine AS run
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# wget (bundled with busybox in alpine) powers the container HEALTHCHECK.
# The standalone output includes a minimal server.js plus traced node_modules.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

# Run as the built-in unprivileged node user.
USER node

EXPOSE 3000

CMD ["node", "server.js"]
