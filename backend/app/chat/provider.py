"""Chat_Provider abstraction + the no-cost deterministic Mock_Chat_Provider.

The provider is the only swappable piece: real hosted/self-hosted models become
new classes selected by :func:`select_provider`, with no change to the endpoint,
the grounding, or the widget. The provider receives an ordered message list
(system contract, prior turns, and the final grounded user turn) and returns the
answer text. It never fetches data itself - grounding happens upstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.chat.system_prompt import (
    GOVERNANCE_REDIRECT,
    GOVERNED_ACTION_TRIGGERS,
)

#: Marker the endpoint places before the grounded context inside the final user
#: message, so a provider (and the mock in particular) can separate the retrieved
#: context from the user's actual question deterministically.
CONTEXT_MARKER = "<<GROUNDED_CONTEXT>>"
QUESTION_MARKER = "<<QUESTION>>"

#: Honest fallback when the grounded context is empty / insufficient.
NO_INFORMATION = (
    "I don't have that information in the platform data or help content I can "
    "see. Try naming a specific title, or ask about a feature shown in the "
    "How It Works guide."
)


@dataclass(frozen=True)
class ChatMessage:
    """One ordered turn in a chat exchange.

    ``role`` is one of ``"system"``, ``"user"``, or ``"assistant"``.
    """

    role: str
    content: str


@runtime_checkable
class ChatProvider(Protocol):
    """A language-model backend for the assistant.

    Implementations MUST be side-effect free with respect to platform data:
    they only turn an ordered message list into answer text.
    """

    def complete(self, messages: list[ChatMessage]) -> str:
        """Return the assistant's answer for the given ordered messages."""
        ...


def _final_user_message(messages: list[ChatMessage]) -> ChatMessage | None:
    for message in reversed(messages):
        if message.role == "user":
            return message
    return None


def _split_context_and_question(content: str) -> tuple[str, str]:
    """Split a grounded user turn into (context, question).

    The endpoint formats the final user turn as::

        <<GROUNDED_CONTEXT>>
        ...retrieved context text...
        <<QUESTION>>
        ...the user's question...

    When the markers are absent (e.g. a raw message), the whole content is
    treated as the question with no context.
    """
    if CONTEXT_MARKER in content and QUESTION_MARKER in content:
        after_ctx = content.split(CONTEXT_MARKER, 1)[1]
        context, question = after_ctx.split(QUESTION_MARKER, 1)
        return context.strip(), question.strip()
    return "", content.strip()


class MockChatProvider:
    """Deterministic, no-network, no-key Chat_Provider.

    It composes an answer purely from the grounded context in the final user
    turn, so the whole request lifecycle is exercisable in CI at zero cost:

    * A governed-action request (override/greenlight/approve/...) returns the
      governance redirect, honoring the System_Prompt_Contract.
    * With non-empty grounded context, it returns a concise answer that quotes
      the retrieved context (never inventing beyond it).
    * With empty context, it returns the honest "I don't have that information".
    """

    name = "mock"

    def complete(self, messages: list[ChatMessage]) -> str:
        user = _final_user_message(messages)
        if user is None:
            return NO_INFORMATION

        context, question = _split_context_and_question(user.content)

        # Honor the governance redirect deterministically (a real model would
        # follow the system prompt; the mock encodes the same behavior).
        lowered = question.lower()
        if any(trigger in lowered for trigger in GOVERNED_ACTION_TRIGGERS):
            return GOVERNANCE_REDIRECT

        if not context:
            return NO_INFORMATION

        # Grounded answer: lead with a direct line, then surface the retrieved
        # context so the user sees exactly what the answer rests on. Deterministic.
        intro = "Here's what the platform data and help content show"
        if question:
            intro = f'For "{question.rstrip("?")}", here is what I can see'
        return f"{intro}:\n\n{context}"


def select_provider(settings: object | None = None) -> ChatProvider:
    """Return the configured Chat_Provider, defaulting to the mock.

    ``settings`` is any object exposing a ``chat_provider`` string attribute
    (the app ``Settings``); an unknown/empty value selects the mock so the app
    always has a working provider with no external configuration.
    """
    choice = ""
    if settings is not None:
        choice = str(getattr(settings, "chat_provider", "") or "").strip().lower()
    # Only the mock ships in this scope; real providers register here later.
    if choice in ("", "mock"):
        return MockChatProvider()
    return MockChatProvider()