# Design Document

## Overview

The Data_Chat_Assistant adds a read-only conversational layer to CineROI AI. A user asks a plain-language question; the backend gathers real platform data (the Retrieved_Context), prepends a fixed System_Prompt_Contract, hands the question plus context to a pluggable Chat_Provider, and returns the provider's answer together with the identifiers of the records used. This first scope ships a deterministic Mock_Chat_Provider (no API key, no network) behind the provider interface so the full flow is testable and demoable at zero cost; a real hosted or self-hosted provider drops in later without changing the endpoint, the grounding, or the widget.

The governing principle is a hard Read_Only_Boundary: the assistant explains numbers the deterministic engines already produced and never computes, alters, or overrides a verdict, guardrail result, or churn value, and never performs a state-changing action.

## Architecture

### Component placement

- `backend/app/chat/provider.py` (new): the `ChatProvider` protocol (`complete(messages: list[ChatMessage]) -> str`), the `ChatMessage` dataclass (`role`, `content`), the `MockChatProvider`, and `select_provider(settings)` which returns the configured provider, defaulting to `MockChatProvider`.
- `backend/app/chat/grounding.py` (new): `GroundingService` - resolves the title in scope (explicit id or Title_Resolution by name), pulls the Retrieved_Context from existing repositories, and renders it into (a) a compact text block for the provider and (b) a list of source record identifiers for the response. Confidential fields are included only when the actor is authorized.
- `backend/app/chat/system_prompt.py` (new): the `SYSTEM_PROMPT_CONTRACT` constant.
- `backend/app/api/chat.py` (new): `router = APIRouter(prefix="/chat", tags=["chat"])` with the handler declared as `@router.post("")` (empty path, so `POST /api/v1/chat` resolves without a 307 redirect that could drop the body), authorized by `Depends(require_operation(Operation.VALUATION))`. It injects the request-scoped `SessionDep` and the `CurrentUser` actor, constructs `GroundingService(session, actor)`, validates the request, builds the message list (system prompt + bounded history + grounded user turn), calls the provider, and returns `ChatResponse`.
- `backend/app/api/support_routers.py`: add `chat` to the imports and `_PREFIXED_ROUTERS` tuple so it mounts under `/api/v1` exactly like the other business routers.
- `frontend/app/_components/chat-widget.tsx` (new): a `"use client"` floating action button + expanding panel, mounted once in the root layout so it is present across the portal. Local Conversation_History, a Context_Chip, pending state, error handling, accessible markup.
- `frontend/lib/api-client.ts` + `frontend/lib/types.ts`: a `chat(request)` method and the `ChatRequest` / `ChatResponse` / `ChatTurn` types.

### Request flow

```mermaid
sequenceDiagram
    participant U as User (widget)
    participant FE as frontend (Next.js proxy)
    participant API as backend POST /api/v1/chat
    participant G as GroundingService
    participant DB as repositories
    participant P as ChatProvider (Mock now)

    U->>FE: message + title scope + trailing history
    FE->>API: same-origin /api/v1/chat
    API->>API: require_operation(VALUATION); validate message
    API->>G: resolve scope + gather context (actor-authorized)
    G->>DB: dashboard summary and/or title scorecard + decision + churn
    DB-->>G: real records
    G-->>API: context text + source record ids
    API->>P: [system prompt] + bounded history + grounded question
    P-->>API: answer text
    API-->>FE: { answer, sources }
    FE-->>U: render answer + Context_Chip
```

### Request/response contract

Request:

```json
{
  "message": "Why is the churn breach non-correctable?",
  "title_id": "7b1c3771-... (optional)",
  "history": [
    { "role": "user", "content": "What is the verdict for The Ledger?" },
    { "role": "assistant", "content": "The Ledger is NEGOTIATE HARD..." }
  ]
}
```

Response:

```json
{
  "answer": "The Ledger's churn mitigation is below the 1.5% hurdle...",
  "sources": ["title:7b1c3771-...", "projection:latest", "model_version:v..."]
}
```

The backend bounds `history` to the last N turns (N small, e.g. 6) and ignores any extra. `title_id` absent triggers Title_Resolution. An empty/blank `message` is rejected through the standard error envelope.

## Components and Interfaces

### GroundingService (the heart of the feature)

Title_Resolution:
- If `title_id` is supplied, load that title.
- Else, load the active title names via `TitleRepository` and select those whose `title_name.lower()` is a substring of `message.lower()` (a direct, deterministic scan - no NLP/NER dependency; the active set is small). Exactly one match -> scope to it. Zero or many -> portfolio scope.
- Robustness: a malformed `title_id` (not a UUID) or one that resolves to no row is caught and falls back to portfolio scope rather than erroring.

Retrieved_Context sources (all existing, read-only):
- Portfolio: `DashboardSummaryResponse` (KPIs + grid rows) via the dashboard aggregation.
- Title scope: the persisted `ValuationScorecardResponse` (via `TitleRepository` + `FinancialProjectionRepository`), the decision/negotiation data, and the churn breakdown read from the persisted `financial_projections.explanation` dict (`checks`, `dominant_factor`, and the `churn_model` sub-object when present).

Confidential handling: the service only includes confidential fields when `RBACService` would permit the actor `READ_CONFIDENTIAL`; otherwise those fields are omitted from the context entirely, so the provider cannot surface them regardless of the prompt.

The service returns a `GroundedContext { text, sources }`. It performs reads only - no writes, no engine runs, no audit entries.

### ChatProvider and MockChatProvider

- `ChatProvider` is a `Protocol` with `complete(messages) -> str`.
- `MockChatProvider.complete` ignores no data and composes a deterministic answer from the grounded user turn: it summarizes the context block in plain English and, when the context lacks the answer, returns an explicit "I don't have that information" sentence. No network, no key. Determinism makes it unit-testable and CI-safe.
- `select_provider(settings)` reads a config value (e.g. `CINEROI_CHAT_PROVIDER`); unknown/empty -> `MockChatProvider`. Real providers (Bedrock/Anthropic/OpenAI/Ollama) are added as new classes selected here, with no change to the endpoint, grounding, or widget.

### System_Prompt_Contract

A fixed instruction prepended to every provider message list: the assistant explains platform data only, has zero authority to change verdicts or deal terms, and must direct any override/greenlight/number-change request to the official executive governance controls on the title page. Applied now (the mock honors the "redirect override requests" behavior) so real models inherit it unchanged.

### Frontend chat widget

- A fixed-position floating action button opens an expanding panel, mounted in the root layout so it persists across routes.
- Context_Chip: shows the in-scope title (name + a key fact) when on a title route, else "Portfolio Overview". The widget derives title scope from the current route when available.
- Conversation_History is kept in local component state; only the last N turns are sent. The backend stays stateless.
- Responsive sizing: full-width minus margins on small screens, a fixed width from the `sm` breakpoint up, capped by `max-h` so it never overflows or collides with navigation on tablet/mobile.
- Source citations: each assistant message renders its `sources` as subtle chips/accordion (e.g. "The Ledger Scorecard", "Portfolio Summary") so the user sees the answer is grounded, not hallucinated.
- Pending state disables submit and shows a spinner; a second submit is blocked while in flight. Errors render a readable message and leave the input usable.
- Accessibility: labeled input, managed focus when the panel opens, and an `aria-live` region announcing new answers and errors.

## Data Models

No database schema changes. The feature adds in-memory/transport models only:

- `ChatMessage { role: "user" | "assistant" | "system", content: str }` - a single turn used both in the request `history` and in the provider message list.
- `ChatRequest { message: str, title_id: str | null, history: ChatMessage[] }` - the inbound payload; `history` is bounded to the last N turns server-side.
- `ChatResponse { answer: str, sources: str[] }` - the outbound payload; `sources` are opaque record identifiers (e.g. `title:<id>`, `projection:latest`, `model_version:<id>`).
- `GroundedContext { text: str, sources: str[] }` - internal result of `GroundingService`, consumed by the endpoint; not serialized directly.

All reads reuse existing persisted models (`titles`, `financial_projections` and its `explanation` JSON, `model_versions`, and the dashboard aggregation). No new tables, columns, or migrations.

## Error Handling

- Empty/blank `message` -> `422`/standard envelope (R4.2).
- Provider raises -> caught, returned as a standard error envelope; provider internals (stack traces, keys, model ids) are never forwarded (R4.4).
- Title_Resolution finding nothing is not an error - it falls back to portfolio scope (R1.3).
- Unauthorized/unauthenticated -> the existing `require_operation` dependency raises `403`/`401` through the envelope before any work (R2.2).

## Testing Strategy

Backend (pytest):
- Grounding returns real data for a known seeded title (e.g. The Ledger) and includes its source ids.
- Insufficient context yields the honest "I don't know" answer (no fabrication).
- Read_Only_Boundary: answering a question performs no writes and creates no audit entries; a request phrased as "override to GREENLIGHT" is answered with the governance-redirect, not an action.
- Empty message is rejected through the envelope.
- Confidential fields are omitted for a role lacking `READ_CONFIDENTIAL`.
- `select_provider` defaults to the mock; the mock is deterministic for identical input.

Frontend (Vitest + Testing Library):
- The widget sends a message and renders the returned answer.
- Error response renders a readable message and the input stays usable.
- The Context_Chip reflects title vs portfolio scope.

## Correctness Properties

These invariants map to the tests in the Testing Strategy and to the acceptance criteria.

### Property 1: Read-only invariance

Answering any Chat_Request performs no persistent write and creates no audit-log entry.

**Validates: Requirements 2.1, 2.4, 1.6**

### Property 2: Grounded or honest

Every answer is derived only from the Retrieved_Context; when the context is insufficient the answer explicitly states the information is not available rather than inventing it.

**Validates: Requirements 1.4, 1.3**

### Property 3: Traceability

Every Chat_Response lists the source record identifiers for the data used as Retrieved_Context.

**Validates: Requirements 1.5**

### Property 4: Confidential containment

For an actor lacking READ_CONFIDENTIAL, confidential fields never appear in the Retrieved_Context or the answer, regardless of the message content.

**Validates: Requirements 2.3**

### Property 5: Provider pluggability + mock determinism

The active provider is selected from configuration and defaults to the Mock_Chat_Provider, which makes no network call, requires no key, and returns an identical answer for identical input.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

### Property 6: System prompt applied

The System_Prompt_Contract is the first message sent to the provider on every request, and an override/greenlight/number-change request is answered with the governance redirect, never an action.

**Validates: Requirements 3.6, 2.1**

### Property 7: Stateless bounded history

The backend persists no conversation and uses at most the configured number of trailing turns from the request.

**Validates: Requirements 4.5, 4.6**

### Property 8: Title resolution

An explicit title scopes to that title; an unambiguous name match scopes to the matched title; no match or multiple matches falls back to the portfolio summary.

**Validates: Requirements 1.2, 1.3**