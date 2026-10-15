# Requirements Document

## Introduction

CineROI AI (GreenlightIQ) is an OTT content-acquisition decision-support platform (FastAPI backend, Next.js frontend). Its Guardrails_Engine evaluates each candidate title against four quantitative guardrails and produces a deterministic greenlight recommendation (GREENLIGHT, NEGOTIATE_HARD, PASS) with a structured, auditable explanation. Every number the platform shows is produced by deterministic engines and persisted; big decisions require dual sign-off and every state change is written to an append-only audit log.

This feature, the **Data_Chat_Assistant**, adds a conversational surface that lets a user ask plain-language questions of two kinds: questions about the data the platform already holds (the portfolio, a title's verdict, its guardrail checks, its churn breakdown), and how-to/concept questions about using the platform (how to upload a slate, what CPVH means, how overrides work). It returns grounded, plain-English answers. The assistant is a read-and-explain layer: it retrieves real data through the platform's existing repositories and curated how-to snippets from a shipped Knowledge_Base, hands the relevant material plus the question to a pluggable language-model provider, and returns the provider's answer.

The assistant MUST NOT compute, alter, or override any verdict, number, guardrail result, or churn value; those remain the exclusive output of the deterministic engines. The assistant MUST NOT take any state-changing action (no ingest, valuation, override, approval, rejection, or calibration). It only reads data the current user is already authorized to see and explains it.

This first scope is deliberately bounded to establish the plumbing safely: a swappable provider interface with a no-cost mock implementation (no external language-model calls, no API keys), the backend endpoint and its data grounding, a frontend chat widget, tests, and documentation. Real hosted or self-hosted providers are added later behind the same interface without changing the endpoint, the grounding, or the widget.

### Grounding (verified against the current codebase)

- Backend routers live under `backend/app/api/*.py`, each defining `router = APIRouter(prefix=..., tags=[...])`, and are mounted under the API prefix by `backend/app/api/support_routers.py` (`_PREFIXED_ROUTERS` tuple + `register_support_routers`). The API prefix is `/api/v1`.
- Authentication/authorization dependencies are in `backend/app/api/deps.py`: `CurrentUser` resolves the acting `UserContext`; `require_operation(op)` builds a dependency that calls `RBACService.authorize(actor, op)` and raises `403` through the error envelope when not permitted.
- `backend/app/engines/rbac.py` defines `class Operation(str, Enum)` with members `INGEST`, `VALUATION`, `OVERRIDE`, `APPROVE`, `REJECT`, `CALIBRATE`, `READ_CONFIDENTIAL`. Confidential-field access is gated by `CONFIDENTIAL_ACCESS_ROLES` (CONTENT_BUYER, CHIEF_CONTENT_OFFICER, CFO); DATA_ANALYST is intentionally excluded.
- Real data the assistant can retrieve already exists behind endpoints: `GET /api/v1/dashboard/summary` (portfolio aggregate), `GET /api/v1/valuation/{title_id}` (scorecard), `GET /api/v1/valuation/{title_id}/decision` (recommendation + negotiation), and the churn breakdown persisted on the valuation explanation (calculable-churn-model). Repositories under `backend/app/repositories/*.py` back these.
- Decimal values are serialized as JSON strings over the wire; the frontend coerces defensively.
- The frontend calls the backend same-origin: the browser hits `/api/...` and `frontend/next.config.mjs` rewrites proxy to the backend, so a new endpoint needs no new UI origin configuration. Client components are marked `"use client"`.
- Backend tests use pytest (+ Hypothesis for pure domain functions) under `backend/tests/{domain,engines,api}`; the frontend uses Vitest + Testing Library.

## Glossary

- **Data_Chat_Assistant**: The feature described by this document - a read-only conversational layer that answers plain-language questions about platform data AND how-to/concept questions, by retrieving real records and curated knowledge snippets and having a Chat_Provider phrase the answer.
- **Chat_Provider**: The pluggable language-model abstraction with a single completion operation (`complete(messages) -> text`). Implementations are selected by configuration. This scope ships only the Mock_Chat_Provider.
- **Mock_Chat_Provider**: A Chat_Provider implementation that makes no external call and deterministically composes an answer from the Retrieved_Context, so the end-to-end flow is exercisable with no API key and no cost.
- **Retrieved_Context**: The grounding material gathered for a question before the provider is called. It is drawn from two sources: live platform data (the portfolio summary and, when a title is in scope, that title's scorecard, decision, and churn breakdown - limited to what the current user is authorized to see) and the Knowledge_Base (curated how-to and concept snippets). A single question may draw from either or both.
- **Chat_Request**: The inbound payload: the user's natural-language message and an optional title scope reference.
- **Chat_Response**: The outbound payload: the assistant's answer text plus the identifiers of the records used as Retrieved_Context (for traceability).
- **Grounding**: The rule that the assistant answers only from the Retrieved_Context and must not invent data; absent supporting data, it states it does not know.
- **Knowledge_Base**: A curated, versioned set of how-to and concept snippets (feature recipes and glossary term definitions) sourced from the platform's own documentation and in-portal guide. It is static read-only reference content shipped with the backend - not user data and not confidential.
- **How_To_Query**: A question about how to use the platform or what a concept means (e.g. "how do I upload a slate?", "what is CPVH?") that is answered from the Knowledge_Base rather than from a title's records.- **Read_Only_Boundary**: The rule that the assistant performs no state-changing operation and computes no verdict or number itself.
- **Conversation_History**: The ordered trailing turns (user and assistant messages) the frontend widget maintains locally and sends with each Chat_Request so follow-up questions have context. The backend remains stateless - it stores no conversation.
- **Title_Resolution**: The process of determining which title a question is about: an explicit title scope when supplied, otherwise a lightweight case-insensitive name match against the title records; an unambiguous match scopes to that title, while no match or multiple matches falls back to the portfolio summary.
- **Context_Chip**: The small label at the top of the chat widget showing the current retrieval scope (a specific title, or the portfolio overview), so the user can see what the next answer will be grounded in.
- **System_Prompt_Contract**: The fixed instruction, established now and applied when any real Chat_Provider is plugged in, that constrains the assistant to explaining platform data only and directs any override/greenlight/number-change request to the official governance controls.
## Requirements

### Requirement 1: Read-only, grounded answers

**User Story:** As a content executive, I want to ask plain-language questions about my portfolio and titles and get answers backed by the platform's real data, so that I can understand verdicts without clicking through every panel.

#### Acceptance Criteria

1. WHEN a Chat_Request is received, THE Data_Chat_Assistant SHALL gather Retrieved_Context from the platform's existing data sources before composing an answer.
2. WHEN a Chat_Request references a specific title, THE Data_Chat_Assistant SHALL include that title's scorecard, decision, and churn breakdown in the Retrieved_Context when the current user is authorized to see them.
3. WHEN a Chat_Request does not reference a specific title, THE Data_Chat_Assistant SHALL perform Title_Resolution by case-insensitive name match: an unambiguous single match SHALL scope the Retrieved_Context to that title, and no match or multiple matches SHALL fall back to the portfolio summary.
4. WHEN a Chat_Request is a How_To_Query, THE Data_Chat_Assistant SHALL retrieve the relevant Knowledge_Base snippets into the Retrieved_Context so how-to and concept questions are answered from curated documentation rather than invented.
5. THE Data_Chat_Assistant SHALL answer only from the Retrieved_Context, and WHEN the Retrieved_Context does not contain information sufficient to answer, THE Data_Chat_Assistant SHALL state that it does not have that information rather than inventing an answer.
6. THE Data_Chat_Assistant SHALL return, in the Chat_Response, identifiers for every source used as Retrieved_Context - both data records and Knowledge_Base snippets - so the answer is traceable to its sources.
7. THE Data_Chat_Assistant SHALL NOT compute, alter, or override any verdict, guardrail result, churn value, or other number; it SHALL only report values already produced by the deterministic engines.

### Requirement 2: No state-changing actions

**User Story:** As a governance owner, I want the assistant to be strictly read-only, so that decisions, overrides, and sign-offs stay on the explicit audited controls.

#### Acceptance Criteria

1. THE Data_Chat_Assistant SHALL NOT perform any ingest, valuation, override, approval, rejection, or calibration operation.
2. THE Data_Chat_Assistant endpoint SHALL be authorized through the existing RBAC dependency so that only an authenticated, permitted user may call it.
3. WHEN gathering Retrieved_Context, THE Data_Chat_Assistant SHALL respect the existing confidential-access policy so that a user is never shown, through the assistant, data they could not see directly.
4. THE Data_Chat_Assistant SHALL NOT write to the audit log or mutate any persistent record as part of answering a question.

### Requirement 3: Pluggable provider with a no-cost mock

**User Story:** As an engineer, I want the language-model behind the assistant to be swappable, so that we can demo with no cost or keys now and adopt a hosted or self-hosted model later without reworking the feature.

#### Acceptance Criteria

1. THE Data_Chat_Assistant SHALL define a Chat_Provider abstraction exposing a single completion operation that accepts an ordered message list and returns answer text.
2. THE Data_Chat_Assistant SHALL select the active Chat_Provider from configuration, defaulting to the Mock_Chat_Provider when no external provider is configured.
3. THE Mock_Chat_Provider SHALL make no network call and SHALL require no API key.
4. THE Mock_Chat_Provider SHALL compose its answer deterministically from the Retrieved_Context so that the same question with the same context yields the same answer.
5. THE Data_Chat_Assistant SHALL allow a real Chat_Provider implementation to be added behind the same abstraction without changing the endpoint contract, the Grounding behavior, or the frontend widget.
6. THE Data_Chat_Assistant SHALL define the System_Prompt_Contract now and SHALL prepend it to the message list sent to any Chat_Provider, so that a real model is constrained to explaining platform data and directs any override, greenlight, or number-change request to the official governance controls.

### Requirement 4: Backend endpoint

**User Story:** As a frontend developer, I want a single chat endpoint consistent with the platform's other routers, so that the widget can call it the same way every other feature calls the API.

#### Acceptance Criteria

1. THE Data_Chat_Assistant SHALL expose a chat endpoint mounted under the existing API prefix in the same manner as the platform's other routers.
2. WHEN a Chat_Request has an empty or missing message, THE Data_Chat_Assistant SHALL reject it through the platform's standard error envelope.
3. THE Data_Chat_Assistant SHALL return the Chat_Response as JSON matching a declared response schema.
4. WHEN the active Chat_Provider fails, THE Data_Chat_Assistant SHALL return a standard error envelope and SHALL NOT leak provider internals to the caller.
5. THE Chat_Request SHALL accept an optional Conversation_History of prior turns, and THE Data_Chat_Assistant SHALL remain stateless - it SHALL NOT persist any conversation and SHALL rely only on the history supplied in the request.
6. THE Data_Chat_Assistant SHALL bound the Conversation_History it uses to a small number of trailing turns so a long client-side thread cannot grow the request unbounded.
### Requirement 5: Frontend chat widget

**User Story:** As a user, I want a simple chat panel in the portal, so that I can ask questions without leaving the page I am on.

#### Acceptance Criteria

1. THE Data_Chat_Assistant SHALL provide a client-side chat widget that sends the user's message to the chat endpoint through the existing same-origin API path and renders the answer.
2. WHEN a title page is in view, THE chat widget SHALL pass that title as the title scope on the Chat_Request so answers are about the title in context.
3. WHILE a request is in flight, THE chat widget SHALL show a pending indicator and SHALL prevent duplicate concurrent submissions.
4. WHEN the endpoint returns an error, THE chat widget SHALL show a readable message and SHALL remain usable for the next question.
5. THE chat widget SHALL be keyboard-operable and accessible (labeled input, focus handling, and status announced to assistive technology).
6. THE chat widget SHALL present as a persistent floating action button in a portal corner that opens an expanding chat panel, available across the portal without navigating away from the current page.
7. THE chat widget SHALL display a Context_Chip at the top of the panel showing the current retrieval scope (the in-context title, or the portfolio overview).
8. THE chat widget SHALL maintain the Conversation_History locally and send only a bounded number of trailing turns with each Chat_Request.
### Requirement 6: Tests and documentation

**User Story:** As a maintainer, I want the assistant covered by tests and documented everywhere the platform is documented, so that it stays correct and discoverable.

#### Acceptance Criteria

1. THE Data_Chat_Assistant SHALL include backend tests covering grounded answers, the honest "I do not know" path when context is insufficient, the Read_Only_Boundary, and rejection of an empty message.
2. THE Data_Chat_Assistant SHALL include a frontend test covering the widget sending a message and rendering the returned answer.
3. THE Data_Chat_Assistant SHALL update the in-portal How It Works guide, the knowledge-base and architecture documents, and the NotebookLM export so the feature is documented in every place the platform documents its features, and the shipped Knowledge_Base how-to/concept snippets SHALL be consistent with that same documentation.