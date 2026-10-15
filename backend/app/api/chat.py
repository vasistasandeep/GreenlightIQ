"""Data_Chat_Assistant endpoint: POST /api/v1/chat (R4).

Read-only. Authorized through the existing RBAC dependency; gathers grounded
context via :class:`GroundingService`; prepends the System_Prompt_Contract and a
bounded slice of the client-supplied Conversation_History; calls the configured
Chat_Provider; returns the answer plus the source identifiers used.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.api.deps import CurrentUser, SessionDep, require_operation
from app.chat.grounding import GroundingService
from app.chat.provider import (
    CONTEXT_MARKER,
    QUESTION_MARKER,
    ChatMessage,
    select_provider,
)
from app.chat.system_prompt import SYSTEM_PROMPT_CONTRACT
from app.core.config import get_settings
from app.core.errors import ErrorEnvelope
from app.core.logging import get_logger
from app.engines.rbac import Operation

router = APIRouter(prefix="/chat", tags=["chat"])

_log = get_logger("chat")

_ALLOWED_ROLES = ("user", "assistant")


class ChatTurn(BaseModel):
    """One prior turn in the client-maintained Conversation_History."""

    role: str = Field(description="'user' or 'assistant'.")
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str) -> str:
        low = v.strip().lower()
        if low not in _ALLOWED_ROLES:
            raise ValueError(f"role must be one of {_ALLOWED_ROLES}")
        return low


class ChatRequest(BaseModel):
    """Inbound chat payload (R4.2, R4.5)."""

    message: str = Field(max_length=4000)
    title_id: str | None = Field(default=None)
    history: list[ChatTurn] = Field(default_factory=list)

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("message must not be empty")
        return v.strip()


class ChatResponse(BaseModel):
    """Outbound chat payload: answer, source identifiers (R1.6), and suggested
    one-click follow-up questions the UI can render as chips."""

    answer: str
    sources: list[str]
    follow_ups: list[str] = Field(default_factory=list)


@router.post(
    "",
    response_model=ChatResponse,
    dependencies=[Depends(require_operation(Operation.VALUATION))],
    summary="Ask the read-only, grounded chat assistant a question (R1-R4).",
)
async def chat(
    body: ChatRequest,
    actor: CurrentUser,
    session: SessionDep,
) -> ChatResponse:
    """Return a grounded answer. Read-only: no writes, no engine runs, no audit."""
    settings = get_settings()

    grounding = GroundingService(session, actor)
    context = await grounding.gather(body.message, body.title_id)

    # Build the ordered message list: system contract, bounded prior turns, and
    # the final grounded user turn (context + question wrapped in markers).
    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=SYSTEM_PROMPT_CONTRACT)
    ]
    max_turns = max(0, int(getattr(settings, "chat_history_max_turns", 6)))
    for turn in body.history[-max_turns:]:
        messages.append(ChatMessage(role=turn.role, content=turn.content))
    grounded_user = (
        f"{CONTEXT_MARKER}\n{context.text}\n{QUESTION_MARKER}\n{body.message}"
    )
    messages.append(ChatMessage(role="user", content=grounded_user))

    provider = select_provider(settings)
    try:
        answer = provider.complete(messages)
    except Exception:  # noqa: BLE001 - never leak provider internals (R4.4)
        # Log the real cause internally; return a clean envelope to the client.
        # Returning the JSONResponse directly (rather than raising) keeps the
        # message generic in every mode, including the dev debug middleware.
        _log.exception("chat provider failed")
        envelope = ErrorEnvelope(
            error_code="CHAT_PROVIDER_UNAVAILABLE",
            message="The assistant is temporarily unavailable. Please try again.",
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=jsonable_encoder(envelope),
        )

    return ChatResponse(
        answer=answer,
        sources=list(context.sources),
        follow_ups=list(context.follow_ups),
    )