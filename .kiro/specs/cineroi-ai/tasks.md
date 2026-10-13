# Implementation Plan: CineROI AI

## Overview

This plan converts the CineROI AI design into a series of incremental, test-driven coding steps for a code-generation LLM. Work proceeds from the foundation outward: monorepo scaffold → database schema and migrations → pure domain functions (the property-based-testing core) → repositories → backend engines → auth/RBAC/approvals → async job processing → cross-cutting concerns (currency, licensing, versioning, audit, concurrency) → REST API → frontend views → deployment orchestration. Each task builds on the previous ones and ends by wiring new code into the existing structure, so there is no orphaned code.

The pure financial and determinism core lives in `backend/app/domain/` and is validated with [Hypothesis](https://hypothesis.readthedocs.io/) property-based tests (Properties 1–40 from the design). Each property test is tagged `# Feature: cineroi-ai, Property {n}: {text}` and runs at least 100 generated examples. Property/unit/integration test sub-tasks are marked optional with `*`; core implementation tasks are never optional.

## Tasks

- [x] 1. Scaffold the monorepo and shared tooling
  - Create `/backend` (FastAPI, async), `/frontend` (Next.js App Router + TypeScript), and `/database` (Alembic migrations + seed) directory trees per the design's monorepo layout.
  - Set up `backend/pyproject.toml` with FastAPI, SQLAlchemy (async), Pydantic, Alembic, Celery, Redis client, psycopg/pgvector driver, pytest, and Hypothesis; configure `app/main.py` ASGI app factory and `app/core/` (config, settings, logging, security stubs).
  - Set up `frontend/package.json` with Next.js, Tailwind, Shadcn UI, Recharts, and a typed API client stub in `frontend/lib/`.
  - _Requirements: 18.1_

- [x] 2. Database schema, migrations, and seed data
  - [x] 2.1 Create core-table migrations and ORM models
    - Enable the pgvector extension; create Alembic migrations and SQLAlchemy models for `titles`, `metadata_vectors` (VECTOR(1536) + IVFFlat cosine index), `financial_projections`, `historical_ground_truth`, and `market_telemetry_cache`.
    - Enforce UUID PKs, foreign keys on `title_id`, `asset_type`/`recommendation_status` enum CHECKs, `acquisition_cost_or_budget` range CHECK, `target_territories` JSONB, and the `(genre_tag, territory)` unique key on telemetry.
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6_
  - [x] 2.2 Create expanded-table migrations and ORM models
    - Add migrations and models for `users`, `sessions`, `approval_workflows`, `approval_actions`, `audit_log`, `jobs`, `model_versions`, `license_terms`, `exchange_rates`, and `title_versions`.
    - Enforce the model-version partial unique index (exactly one active), the `talent_pedigree_weight + narrative_trope_weight = 1.00` CHECK, the title-version `(title_id, version_number)` unique and one-active-per-title rule, `jobs.idempotency_key` UNIQUE, `exchange_rates` `(from,to,date)` UNIQUE, and `row_version` optimistic-lock columns on `titles` and `financial_projections`.
    - Make `audit_log` append-only by revoking UPDATE/DELETE and adding a mutation-blocking trigger.
    - _Requirements: 17.1, 17.2, 19.2, 19.4, 20.1, 20.3, 20.4, 20.5, 21.4, 22.1, 23.2, 24.2, 24.4, 25.2, 26.1, 27.1, 27.2_
  - [x] 2.3 Author database initialization and mock seed scripts
    - Create `/database/seed` scripts that build the full schema and load mock seed data (titles, subscriber cluster preference vectors, exchange rates, an initial active model version, users with each role).
    - _Requirements: 17.7_
  - [x] 2.4 Write schema integrity integration tests
    - Verify UUID PKs, FK enforcement, enum/range CHECKs, VECTOR(1536) storage, exactly-one-active partial indexes, and the audit-log append-only trigger against a real PostgreSQL 16 + pgvector instance.
    - _Requirements: 17.1, 17.2, 17.4, 17.5, 17.6, 25.2_

- [x] 3. Pure domain functions: CPVH and recommendation core
  - [x] 3.1 Implement CPVH computation and ceiling selection in `app/domain/cpvh.py`
    - `compute_cpvh(cost_usd, viewing_hours)` rounding to 4 dp with a positive-viewing-hours precondition; `cpvh_ceiling(asset_type)` returning 0.18 for Premium_Original, 0.05 for Library_Filler, and `None` otherwise; breach-boundary helper (strictly `>` ceiling breaches, `<=` passes).
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6, 4.7_
  - [x] 3.2 Write property tests for CPVH computation and divide-by-zero guard
    - **Property 8: CPVH computation and divide-by-zero guard**
    - **Validates: Requirements 4.1, 4.5**
  - [x] 3.3 Write property tests for CPVH ceiling selection and breach boundary
    - **Property 9: CPVH ceiling selection** and **Property 10: CPVH breach boundary**
    - **Validates: Requirements 4.2, 4.3, 4.4, 4.6, 4.7**
  - [x] 3.4 Implement LTV-to-Cost and recommendation determination in `app/domain/ltv.py` and `app/domain/recommendation.py`
    - `compute_ltv_to_cost(...)` per the design formula; `determine_recommendation(checks)` returning exactly one of {GREENLIGHT, NEGOTIATE_HARD, PASS} with the correctable/non-correctable/unclassifiable logic, plus the structured `Explanation` (per-check status, dominant factor by largest shortfall).
    - _Requirements: 5.1, 5.3, 8.1, 8.2, 8.3, 8.4, 8.5, 30.1, 30.2, 30.3_
  - [x] 3.5 Write property tests for LTV formula and breach boundary
    - **Property 11: LTV-to-Cost formula** and **Property 12: LTV-to-Cost breach boundary**
    - **Validates: Requirements 5.1, 5.3**
  - [x] 3.6 Write property tests for recommendation determination, explanation, and dominant factor
    - **Property 15: Recommendation determination and totality**, **Property 39: Explanation completeness**, **Property 40: Dominant factor selection**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 30.1, 30.2, 30.3**

- [x] 4. Pure domain functions: MAPE, currency, windowing/payback
  - [x] 4.1 Implement MAPE in `app/domain/mape.py`
    - `compute_mape(pairs)` excluding zero-actual pairs, returning `None` with a no-eligible-metrics indicator when all excluded, rounded to 2 dp.
    - _Requirements: 11.5, 11.7, 11.8_
  - [x] 4.2 Write property test for MAPE with zero-actual exclusion
    - **Property 16: MAPE computation with zero-actual exclusion**
    - **Validates: Requirements 11.5, 11.7, 11.8**
  - [x] 4.3 Implement currency normalization in `app/domain/currency.py`
    - `normalize_to_usd(cost, rate)` and recording of rate value + rate date; raise a typed error when the required rate is absent.
    - _Requirements: 21.1, 21.2, 21.4, 21.5_
  - [x] 4.4 Write property tests for currency normalization round-trip and missing-rate rejection
    - **Property 24: Currency normalization round-trip** and **Property 25: Missing exchange rate rejection**
    - **Validates: Requirements 21.1, 21.2, 21.4, 21.5**
  - [x] 4.5 Implement windowing and milestone-based payback in `app/domain/windowing.py`
    - `validate_windowing(terms)` rejecting when summed windowing periods exceed license duration; `compute_payback_horizon(milestone_schedule, monthly_margin)` returning the first month cumulative contribution turns positive under milestone disbursement; distinguish exclusive from non-exclusive windows in value projection.
    - _Requirements: 7.1, 7.2, 7.3, 22.2, 22.3, 22.4_
  - [x] 4.6 Write property tests for payback-from-milestones and windowing bounds
    - **Property 30: Payback uses milestone schedule** and **Property 31: Windowing within license duration**
    - **Validates: Requirements 7.1, 7.3, 22.2, 22.4**
  - [x] 4.7 Implement weight-offset normalization in `app/domain/weights.py`
    - Compute offsets within [-1.00, 1.00]; re-weight talent-pedigree and narrative-trope so each is in [0.00, 1.00] and the pair sums to exactly 1.00; reject out-of-range results.
    - _Requirements: 12.1, 12.2, 12.4_
  - [x] 4.8 Write property tests for calibration weight bounds and out-of-range rejection
    - **Property 18: Calibration weight bounds and normalization** and **Property 19: Calibration out-of-range rejection**
    - **Validates: Requirements 12.1, 12.2, 12.4**

- [x] 5. Checkpoint - domain core verified
  - Ensure all domain property tests and unit tests pass, ask the user if questions arise.

- [x] 6. Repository layer and error envelope
  - [x] 6.1 Implement the repository access layer in `app/repositories/`
    - Async repositories for titles, metadata_vectors, financial_projections, ground_truth, telemetry, users/sessions, approvals, audit_log, jobs, model_versions, license_terms, exchange_rates, and title_versions, including optimistic-lock-aware update methods.
    - _Requirements: 17.2, 27.2_
  - [x] 6.2 Implement the shared error envelope and HTTP mapping in `app/core/errors.py`
    - Define the `{error_code, message, details}` envelope and the exception-to-HTTP mapping table from the design (415/422/404/409/401/403/500 and partial-batch 200).
    - _Requirements: 1.4, 1.5, 9.3, 10.3, 11.2, 11.4, 12.4, 19.3, 19.6, 20.2, 21.5, 22.4, 27.2_
  - [x] 6.3 Write integration test for optimistic-lock conflict rejection
    - **Property 34: Optimistic-lock conflict rejection**
    - **Validates: Requirements 27.2**

- [x] 7. Model versioning service
  - [x] 7.1 Implement model-version management in `app/engines/model_versioning.py`
    - Read active version; insert a new immutable version with `supersedes_id` and flip active; never mutate in place; stamp valuations with the active id.
    - _Requirements: 26.1, 26.2, 26.3, 26.4_
  - [x] 7.2 Write property tests for immutable version creation, stamping, and reproducibility
    - **Property 21: Calibration creates a new immutable model version**, **Property 22: Valuation model-version stamp**, **Property 23: Historical reproducibility**
    - **Validates: Requirements 12.3, 26.1, 26.2, 26.3, 26.4**

- [x] 8. Audit logging service
  - [x] 8.1 Implement the Audit_Log_Service in `app/engines/audit.py`
    - `record(actor, action, before, after, model_version_id)` writing one append-only entry; `lineage(subject_id)` returning entries in chronological order; associate valuations with the active model version.
    - _Requirements: 25.1, 25.2, 25.3, 25.4_
  - [x] 8.2 Write property tests for audit append-only completeness and lineage ordering
    - **Property 37: Audit append-only completeness** and **Property 38: Lineage ordering and completeness**
    - **Validates: Requirements 25.1, 25.2, 25.4**

- [x] 9. Guardrails_Engine orchestration
  - [x] 9.1 Implement the Guardrails_Engine orchestrator in `app/engines/guardrails.py`
    - Normalize cost to USD first (reject on missing rate), run CPVH/LTV/churn/payback checks via the domain functions, build the explanation, determine the recommendation, apply territory-weighted CPM/LTV across target territories, persist `calculated_cpvh`/`ltv_to_cost_multiple`/`churn_reduction_pct`/`payback_horizon_months`/`recommendation_status`/`normalized_cost_usd`/`exchange_rate_id`/`model_version_id`/`explanation`, retry persistence up to 3× preserving prior value, and emit an audit entry.
    - _Requirements: 4.5, 4.8, 5.4, 6.1, 6.2, 6.3, 7.4, 8.6, 8.7, 21.2, 21.3, 25.1, 25.3, 30.4_
  - [x] 9.2 Write property test for churn mitigation breach boundary
    - **Property 13: Churn mitigation breach boundary** and **Property 14: Payback horizon breach boundary**
    - **Validates: Requirements 6.3, 7.3**
  - [x] 9.3 Write integration tests for guardrail persistence, ordering, retries, and concurrency
    - Verify persistence within the 5-second bound, retry-on-failure preserving prior value, CPVH null when viewing hours = 0, and concurrent valuations producing no partial writes (row-level locking).
    - **Property 34 (persistence angle)** reused for conflict; concurrency per design.
    - _Requirements: 4.5, 4.8, 5.4, 7.4, 8.6, 8.7, 27.3_

- [x] 10. Feature_Extraction_Engine and Vector_Search_Engine
  - [x] 10.1 Implement the EmbeddingProvider abstraction and Feature_Extraction_Engine in `app/engines/feature_extraction.py`
    - Generate a 1536-dim Narrative_DNA vector in [-1.0, 1.0], an Affective_Tone_Score with exactly one primary and one secondary trigger, and `talent_pedigree_score`/`production_scale_metric` in [0.0, 10.0] to 2 dp using active model-version weights; persist all four artifacts atomically; on empty source record extraction-failure; on persist failure roll back; on parse failure retain prior data.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_
  - [x] 10.2 Write property tests for extraction output shape and bounds
    - **Property 4: Narrative DNA vector shape**, **Property 5: Affective tone cardinality**, **Property 6: Extraction score bounds**
    - **Validates: Requirements 2.1, 2.3, 2.4, 2.5**
  - [x] 10.3 Write unit/integration tests for extraction failure and atomic persistence
    - Empty/whitespace source failure (R2.2), persist-failure rollback (R2.7), parse-failure retain-prior (R2.8), and atomic four-artifact persistence in one transaction (R2.6).
    - _Requirements: 2.2, 2.6, 2.7, 2.8_
  - [x] 10.4 Implement the Vector_Search_Engine in `app/engines/vector_search.py`
    - pgvector cosine similarity (`<=>`), results ranked descending by similarity; empty set with NO_CLUSTERS status when no clusters exist.
    - _Requirements: 3.1, 3.2, 3.3_
  - [x] 10.5 Write property/unit tests for similarity ranking and no-cluster case
    - **Property 7: Similarity ranking order**; unit test for the NO_CLUSTERS empty-set case.
    - **Validates: Requirements 3.1, 3.2, 3.3**

- [x] 11. Ingestion_Service
  - [x] 11.1 Implement the Ingestion_Service in `app/engines/ingestion.py`
    - Parse CSV/JSON/PDF; reject unsupported formats and CSV over 10,000 rows as whole-request errors; per-row required-field and value-range validation rejecting only bad rows while continuing; capture native currency and License_Terms; store new submissions as versioned title children with incrementing version numbers (one active per title); honor the idempotency key to replay the stored result; trigger feature extraction per accepted record; return a summary where `accepted + rejected == total`.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 21.1, 22.1, 24.1, 24.2, 24.3, 24.4, 27.1_
  - [x] 11.2 Write property tests for batch invariants, mixed-batch acceptance, and format rejection
    - **Property 1: Batch summary conservation**, **Property 2: Mixed-batch partial acceptance**, **Property 3: Unsupported format rejection**
    - **Validates: Requirements 1.1, 1.4, 1.7, 1.8, 1.9, 1.10**
  - [x] 11.3 Write property tests for idempotent replay and title versioning
    - **Property 33: Idempotent ingestion replay** and **Property 32: Title versioning immutability and increment**
    - **Validates: Requirements 24.1, 24.2, 24.3, 24.4, 27.1**
  - [x] 11.4 Write unit test for the row-limit boundary
    - Exactly 10,000 rows accepted, 10,001 rejected as whole-batch.
    - _Requirements: 1.5_

- [x] 12. Backtesting_Module and Calibration_Controller
  - [x] 12.1 Implement the Backtesting_Module in `app/engines/backtesting.py`
    - Validate and persist Ground_Truth_Records (reject missing fields / non-numeric actuals without persisting); retrieve ground truth for `is_historical` titles matching on identifier; exclude historical titles without ground truth with an error; compute MAPE via the domain function; build the audit scorecard reporting predicted/actual/MAPE and excluded metrics.
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8_
  - [x] 12.2 Write property/unit tests for ground-truth validation and missing-ground-truth exclusion
    - **Property 17: Ground-truth validation rejects invalid records**; unit test for the historical-title-without-ground-truth exclusion (R11.4).
    - **Validates: Requirements 11.2, 11.4**
  - [x] 12.3 Implement the Calibration_Controller in `app/engines/calibration.py`
    - When MAPE > 10% compute offsets, normalize coupled weights, validate bounds, and create+activate a new model version via the versioning service; when MAPE ≤ 10% report no adjustment and leave weights unchanged; reject out-of-range offsets preserving prior weights.
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_
  - [x] 12.4 Write property test for calibration no-op below threshold
    - **Property 20: Calibration no-op below threshold**
    - **Validates: Requirements 12.5**

- [x] 13. Checkpoint - engines verified
  - Ensure all engine property, unit, and integration tests pass, ask the user if questions arise.

- [x] 14. Auth, RBAC, and Approval Workflow
  - [x] 14.1 Implement the Auth_Service in `app/engines/auth.py` and `app/core/security.py`
    - SSO login via OIDC/SAML, session issuance bound to identity, 30-minute idle expiry, service-to-service API credentials, and rejection of missing/expired/revoked credentials with descriptive errors.
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6_
  - [x] 14.2 Implement the RBAC_Service in `app/engines/rbac.py`
    - One role per user; operation-level authorization; override allowed only for CONTENT_BUYER/CCO/CFO; confidential-record and field scoping by role and authorized territory with field withholding + authorization indication.
    - _Requirements: 20.1, 20.2, 28.2, 28.4_
  - [x] 14.3 Implement the Approval_Workflow in `app/engines/approvals.py`
    - Require CCO + CFO sign-off when `normalized_cost_usd` > 25,000,000 USD for a GREENLIGHT decision; record approve/reject/override actions with actor and timestamp; block finalization until all required approvals are recorded and report outstanding approvals.
    - _Requirements: 20.3, 20.4, 20.5_
  - [x] 14.4 Write property tests for the authorization and approval matrix
    - **Property 26: High-budget approval threshold in base currency**, **Property 27: Finalization gating**, **Property 28: Override authorization matrix**, **Property 29: Confidential access scoping**
    - **Validates: Requirements 20.2, 20.3, 20.5, 28.2, 28.4**
  - [x] 14.5 Write integration tests for auth flows
    - SSO login, session issuance, 30-minute idle expiry, credential rejection, and service-to-service credentials.
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6_

- [x] 15. Async job processing and telemetry
  - [x] 15.1 Implement Celery tasks and the job lifecycle in `app/tasks/`
    - Define `ingest_batch`, `extract_features`, `run_backtest_audit`, and `poll_telemetry` on dedicated queues; drive the `jobs` lifecycle PENDING → PROCESSING → COMPLETED|FAILED recording failure reasons; fire a terminal-status webhook with a per-event dedupe key; route exhausted-retry jobs to the DLQ; emit structured logs and metrics; raise an SLA alert past 15 minutes.
    - _Requirements: 23.1, 23.3, 23.5, 23.6, 27.4, 29.1, 29.2, 29.3_
  - [x] 15.2 Write property tests for job lifecycle and webhook idempotency
    - **Property 36: Job status lifecycle** and **Property 35: Webhook idempotent processing**
    - **Validates: Requirements 23.3, 23.5, 27.4**
  - [x] 15.3 Implement the Telemetry_Connector in `app/engines/telemetry.py`
    - Pluggable `TelemetrySource` connectors polled asynchronously; upsert social sentiment / chart velocity / licensing inflation keyed by `(genre_tag, territory)`; on source unavailability retain last cached values and mark the source unavailable.
    - _Requirements: 13.1, 13.2, 13.4_
  - [x] 15.4 Write integration tests for telemetry caching, DLQ re-dispatch, and SLA alerting
    - Source-unavailable retains cache and marks unavailable; DLQ routing and operator re-dispatch; SLA alert past 15 minutes.
    - _Requirements: 13.4, 29.3, 29.5_

- [x] 16. REST API surface
  - [x] 16.1 Implement core routers in `app/api/`
    - `POST /titles/ingest` (202 + job id, idempotency header), `POST /valuation/calculate`, `GET /valuation/{title_id}` (scorecard + metadata breakdown + explanation), `POST /backtest/audit`, `GET /market/telemetry`; wire auth/RBAC/audit middleware and the error envelope; dispatch heavy operations to the Task_Queue and return a job id inline.
    - _Requirements: 1.1, 9.1, 9.2, 9.3, 10.1, 10.2, 10.3, 11.1, 11.6, 13.3, 23.1, 23.2, 30.4_
  - [x] 16.2 Implement supporting routers in `app/api/`
    - `GET /jobs/{job_id}`, `POST /jobs/{job_id}/retry`, auth login/logout/session, decision override/approve/reject/finalization, model-version catalog + `POST /calibration/apply`, `GET /audit/lineage/{subject_id}`, `GET /titles/{id}/versions`, and `GET /health` (DB/queue/telemetry status).
    - _Requirements: 12.3, 16.3, 20.2, 20.4, 20.5, 23.4, 24.5, 25.4, 26.3, 29.4, 29.5_
  - [x] 16.3 Write integration tests for the API surface
    - 202 dispatch + job polling, not-found mapping for valuation, partial-batch 200, approval gating 409, calibration-apply flow, and health reporting.
    - _Requirements: 9.3, 10.3, 20.5, 23.2, 23.4, 29.4_

- [x] 17. Data protection: encryption at rest and retention
  - [x] 17.1 Implement encryption-at-rest and retention policy in `app/core/`
    - Column-level/pgcrypto encryption for unreleased scripts, deal terms, and PII; configurable retention periods that purge or archive eligible records.
    - _Requirements: 28.1, 28.3_
  - [x] 17.2 Write integration tests for encryption and retention
    - Verify sensitive columns are encrypted at rest and that elapsed-retention records are purged or archived per policy.
    - _Requirements: 28.1, 28.3_

- [x] 18. Checkpoint - backend complete
  - Ensure all backend property, unit, and integration tests pass, ask the user if questions arise.

- [x] 19. Frontend: typed client and Executive Command Dashboard
  - [x] 19.1 Implement the typed API client and shared components in `frontend/lib/` and `frontend/components/`
    - Fetch wrapper with session handling and the error envelope; `RecommendationBadge` mapping status → GREENLIGHT / NEGOTIATE HARD / PASS label.
    - _Requirements: 14.3_
  - [x] 19.2 Build the Executive Command Dashboard at `/dashboard`
    - `KpiCards` (active pipeline valuation, avg LTV-to-Cost, portfolio risk exposure, model accuracy); sortable `AssetDataGrid` (title, asset type, asking price, CPVH status, LTV multiple, badge); row-click navigation to the Title Evaluation view.
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_
  - [x] 19.3 Write component/interaction tests for the dashboard
    - KPI cards, badge mapping, column sorting, and row-click navigation.
    - _Requirements: 14.1, 14.3, 14.4, 14.5_

- [x] 20. Frontend: Deep-Dive Title Evaluation view
  - [x] 20.1 Build the Title Evaluation view at `/titles/[id]`
    - `MetadataRadar` (Narrative DNA, Affective Tone, Talent Pedigree, Production Scale); `FinancialAccordion` (CPVH ceiling checks, churn mitigation curves, `PaybackTimeline` bar chart); `NegotiationLeverage` panel from license terms; `ExplanationPanel` surfacing passed/breached checks, computed vs threshold, shortfall, and dominant factor; pending state when no completed valuation.
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 30.4_
  - [x] 20.2 Write component tests for the title evaluation view
    - Radar chart, financial accordion, negotiation panel, explanation panel, and the pending-valuation state.
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 30.4_

- [x] 21. Frontend: Backtesting & Calibration Studio
  - [x] 21.1 Build the Backtest Studio at `/backtest`
    - Split-pane layout with `GroundTruthForm` on the left; `VarianceChart` side-by-side Predicted vs Actual for CPVH and LTV multiples on the right after submission; `CalibrationController` that requests auto-tuning offsets from historical MAPE and displays applied weight offsets; high-budget sign-off panel showing required roles and outstanding approvals.
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 20.5_
  - [x] 21.2 Write component/interaction tests for the studio
    - Ground-truth submission driving variance charts, calibration request, applied-offset confirmation, and the sign-off panel.
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

- [x] 22. Deployment orchestration
  - [x] 22.1 Author docker-compose, Dockerfiles, and README
    - `docker-compose.yml` orchestrating PostgreSQL+pgvector, FastAPI backend, Celery workers + Redis/RabbitMQ broker, and the Next.js frontend; initialize the database from the provided scripts on startup; backend and frontend Dockerfiles; README documenting setup, environment configuration, and run instructions.
    - _Requirements: 18.2, 18.3, 18.4_
  - [x] 22.2 Write a deployment smoke test
    - `docker compose up` initializes the DB from scripts, loads seed data, brings services healthy, and `GET /health` reports DB, Task_Queue, and Telemetry_Connector status.
    - _Requirements: 18.4, 29.4_

- [x] 23. Final checkpoint - full stack verified
  - Ensure all backend and frontend tests pass and the deployment smoke test succeeds, ask the user if questions arise.

## Post-Launch Enhancements (Requirements 31-37)

The following capabilities were implemented and shipped after the core plan (tasks 1-23). They are recorded here, marked complete, for a single source of truth. All reuse existing engine outputs, repository/error conventions, and frontend patterns; none change the four guardrail thresholds or the recommendation logic. Each sub-task ends by wiring new code into the existing structure.

- [x] 24. Comparable Titles - Top 3 historical comps (R31)
  - [x] 24.1 Add title-to-title similarity to the data access layer and valuation API
    - `MetadataVectorRepository.rank_similar_titles(title_vector, exclude_title_id, limit=3)` using pgvector cosine over `narrative_dna`, joined to `titles` for name/genre, with a correlated subquery for each neighbour's latest `recommendation_status`; order by the derived `1 - distance` similarity (forcing an exact scan so the IVFFlat index does not return zero rows at demo scale) and de-dupe to one row per neighbour; add `ComparableTitles`/`TitleComp` schemas and `GET /valuation/{title_id}/comps` (VALUATION-gated, 404 on missing title, `found=false` on no embedding).
    - _Requirements: 31.1, 31.2, 31.3, 31.4, 31.5_
  - [x] 24.2 Build the comps panel on the title page
    - `getComps` typed client method + types; `ComparableTitlesPanel` on `/titles/[id]` linking each comp with a `RecommendationBadge` and similarity, with loading/empty/error states.
    - _Requirements: 31.6_
  - [x]* 24.3 Tests for comparable titles
    - Backend example tests (ranked / `found=false` / 404); frontend `comparable-titles.test.tsx` (ranked, pending-badge, empty, error).
    - **Property 43: Comparable-titles ranking and self-exclusion**
    - _Requirements: 31.1, 31.2, 31.3, 31.5, 31.6_

- [x] 25. Market Telemetry Card (R32)
  - [x] 25.1 Expose genre and primary territory on the valuation scorecard
    - Add `genre_tag` and `primary_territory` (first of `target_territories`) to `ValuationScorecardResponse` and populate them in `GET /valuation/{title_id}`.
    - _Requirements: 32.1_
  - [x] 25.2 Build the Market Telemetry card
    - `getTelemetry` client method + `MarketTelemetry` type; `MarketTelemetryCard` on `/titles/[id]` consuming `GET /market/telemetry`, with data / stale-source / never-polled / absent-genre-territory states.
    - _Requirements: 32.2, 32.3, 32.4, 32.5_
  - [x] 25.3 Seed the telemetry cache consistently with territory weighting
    - Seed `market_telemetry_cache` for every genre/territory pair the seeded titles target; back-fill each title's modeled inputs by dividing out the resulting CPM/LTV weights so stored scorecards are unchanged and a live recompute still reproduces them; add the cache to the demo-reset truncation set.
    - _Requirements: 13.2, 32.2, 36.1_
  - [x]* 25.4 Tests for the telemetry card
    - Backend example test for scorecard genre/territory; frontend `market-telemetry-card.test.tsx` (four states).
    - _Requirements: 32.1, 32.2, 32.3, 32.4, 32.5_

- [x] 26. Dashboard filtering, search, and shareable view state (R33)
  - [x] 26.1 Make the asset grid a pure function of the URL
    - Read search (`q`), recommendation filter (`rec`), deal-stage filter (`stage`), and sort (`sort`,`dir`) from `useSearchParams`; write via `router.replace` (history-replacing, scroll-preserving); add the search box, filter dropdowns, clear control, and a visible result count with a no-match state; wrap the grid in a `<Suspense>` boundary on the dashboard page.
    - _Requirements: 33.1, 33.2, 33.3, 33.4, 33.5, 33.6_
  - [x]* 26.2 Tests for dashboard view state
    - `asset-data-grid.test.tsx` with a stateful `next/navigation` mock: search, both filters, URL hydration, no-match, and query-string writes.
    - **Property 47: Dashboard view state is a pure function of the URL**
    - _Requirements: 33.1, 33.2, 33.3, 33.4, 33.5_

- [x] 27. Deal-stage acquisition lifecycle (R34)
  - [x] 27.1 Implement the pure deal-stage state machine in `app/domain/deal_stage.py`
    - `DealStage` enum, `ALLOWED_TRANSITIONS` matrix (one forward step; abandon-to-PASSED from any live stage; APPROVED to CLOSED_WON/CLOSED_LOST), `validate_transition`, `allowed_next_stages`, `coerce_stage` (null -> SCREENING), and terminal-stage handling. No I/O.
    - _Requirements: 34.1, 34.4, 34.8_
  - [x] 27.2 Add the deal_stage column and migration
    - `titles.deal_stage` TEXT NOT NULL DEFAULT 'SCREENING' with a CHECK on the enumerated set; Alembic migration `0004_deal_stage` back-filling existing rows; seed each title with a stage spanning the pipeline.
    - _Requirements: 34.1_
  - [x] 27.3 Implement the deal-stage endpoints
    - `GET /titles/{id}/deal-stage` (VALUATION-gated: current + allowed next); `PATCH /titles/{id}/deal-stage` (OVERRIDE-gated; validate via the state machine - illegal 422 with allowed set, unauthorized 403; persist under optimistic lock; write a `deal_stage_transition` audit entry).
    - _Requirements: 34.2, 34.3, 34.4, 34.5_
  - [x] 27.4 Surface deal stage in the frontend
    - Shared `DealStageBadge`; `DealStageControl` on `/titles/[id]` (legal next stages only; read-only on 403; message on 422); a sortable Deal Stage column and a stage filter on the dashboard grid; `deal_stage` on the dashboard summary row.
    - _Requirements: 34.6, 34.7_
  - [x]* 27.5 Tests for the deal-stage lifecycle
    - `test_deal_stage.py` (example + Hypothesis properties 41, 42); API example tests (advance / illegal 422 / unauthorized 403 / audit); frontend `deal-stage-control.test.tsx` (advance / terminal / 403 / 422) and the grid stage-filter test.
    - **Property 41: Deal-stage transition legality**, **Property 42: Allowed-next-stages matches the matrix**
    - _Requirements: 34.2, 34.3, 34.4, 34.5, 34.6, 34.7, 34.8_

- [x] 28. Responsive tablet layout (R35)
  - [x] 28.1 Tablet/iPad refinements
    - Confirm the `width=device-width` viewport and mobile-first breakpoints; give the what-if sliders a taller touch hit area with `touch-none`; reduce the metadata radar `outerRadius` (72% -> 65%) so axis labels do not clip in the half-width column.
    - _Requirements: 35.1, 35.2, 35.3, 35.4_

- [x] 29. Demo and operational integrity (R36)
  - [x] 29.1 Fix the optimistic-locked update
    - `BaseRepository.update_with_version` resolves the pk column from the model class (`type(self).pk`) instead of the repository instance, repairing recompute of a title that already has a persisted projection.
    - _Requirements: 27.2, 36.3_
  - [x] 29.2 Exchange-rate latest-date fallback
    - `Guardrails_Engine._normalize_cost` falls back to the latest available dated rate when the exact rate date is missing, rejecting only when the currency pair has no rate at all.
    - _Requirements: 21.5, 36.2_
  - [x] 29.3 Self-consistent seed data
    - Milestone-based payback back-fill (`monthly_margin = normalized / (payback - 0.5)`, single month-1 milestone) so a recompute lands on the seeded payback; correct seeded churn and verdict labels so every seeded title recomputes to its stored verdict.
    - _Requirements: 36.1_
  - [x] 29.4 Demo reset script
    - `scripts/demo-reset.ps1` / `.sh` truncate the demo-mutable tables (including `market_telemetry_cache`) and re-apply the generated seed via `docker compose cp` + `psql -f`.
    - _Requirements: 36.4_
  - [x] 29.5 How It Works guide
    - `/guide` page explaining each guardrail in plain language with worked arithmetic from the seeded titles and a step-by-step walkthrough from raw deal to verdict to negotiation target.
    - _Requirements: 36.5_
  - [x] 29.6 Decision resolution + demo sign-off endpoints
    - `GET /valuation/{title_id}/decision` (resolve title to its latest decision id); `POST /decisions/{id}/demo-sign-off` (dev/demo-only, attributes an approval to the seeded role-holder so a single-identity demo clears the two-role gate; absent in production).
    - _Requirements: 36.6, 36.7_
  - [x]* 29.7 Tests for operational integrity
    - DB-less regression `test_base_update_with_version.py` (Property 44); FX fallback test (Property 45); seed recompute consistency verified against the running engine (Property 46); generator `--check` sync guard.
    - **Property 44: Optimistic-locked update builds against the model class**, **Property 45: Exchange-rate latest-date fallback**, **Property 46: Seed recompute consistency**
    - _Requirements: 21.5, 36.1, 36.2, 36.3_

- [x] 30. Asset Studio - instant evaluation and intake (R37)
  - [x] 30.1 Instant single-title evaluation endpoint
    - `POST /titles/quick-evaluate` (INGEST-gated): create title + active version, estimate viewing hours from budget/pedigree when blank, normalize non-USD cost with the latest-rate fallback, run the engine inline, return the full `QuickEvaluateResponse` scorecard.
    - _Requirements: 37.1, 37.2, 37.3_
  - [x] 30.2 Pitch PDF auto-fill endpoint
    - `POST /titles/parse-pitch`: best-effort extraction of title/synopsis/genre/budget/currency for review; never creates a title or runs a valuation.
    - _Requirements: 37.4_
  - [x] 30.3 Asset Studio UI
    - `/studio` with the Single Asset form (shorthand cost preview + quick presets), the Batch Slate tab (async ingest with accepted/rejected summary), the pitch-PDF drop zone, and the instant scorecard with a deep-dive link.
    - _Requirements: 37.5, 37.6, 37.7_
  - [x]* 30.4 Tests for the Asset Studio
    - Shorthand-expansion unit tests (`_components/helpers.test.ts`) and the studio component/interaction tests.
    - _Requirements: 37.5, 37.6, 37.7_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; they are test-related (property, unit, integration, component, smoke) sub-tasks. Core implementation sub-tasks are never optional.
- Property tests target the pure domain functions in `backend/app/domain/` and deterministic engine orchestration via in-memory repository fakes, running at least 100 generated examples each with Hypothesis, tagged `# Feature: cineroi-ai, Property {n}: {text}`.
- Each property sub-task names the specific design Property number(s) and the requirement clause(s) it validates for full traceability.
- Checkpoints (tasks 5, 13, 18, 23) provide incremental validation at the domain, engine, backend, and full-stack boundaries.
- Database schema/constraints, Docker/deployment, SSO/session infrastructure, external telemetry, and UI rendering are verified by integration/smoke/component tests rather than property-based tests, matching the design's testing strategy.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["2.3", "2.4", "3.1", "3.4", "4.1", "4.3", "4.5", "4.7"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.5", "3.6", "4.2", "4.4", "4.6", "4.8", "6.1", "6.2"] },
    { "id": 4, "tasks": ["6.3", "7.1", "8.1"] },
    { "id": 5, "tasks": ["7.2", "8.2", "9.1", "10.1", "10.4"] },
    { "id": 6, "tasks": ["9.2", "9.3", "10.2", "10.3", "10.5", "11.1", "12.1", "12.3"] },
    { "id": 7, "tasks": ["11.2", "11.3", "11.4", "12.2", "12.4", "14.1", "14.2", "14.3", "15.3", "17.1"] },
    { "id": 8, "tasks": ["14.4", "14.5", "15.1", "17.2"] },
    { "id": 9, "tasks": ["15.2", "15.4", "16.1", "16.2"] },
    { "id": 10, "tasks": ["16.3", "19.1"] },
    { "id": 11, "tasks": ["19.2", "20.1", "21.1"] },
    { "id": 12, "tasks": ["19.3", "20.2", "21.2", "22.1"] },
    { "id": 13, "tasks": ["22.2"] }
  ]
}
```
