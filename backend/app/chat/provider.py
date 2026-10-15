"""Chat_Provider abstraction + the no-cost deterministic Mock_Chat_Provider.

The provider is the only swappable piece: real hosted/self-hosted models become
new classes selected by :func:`select_provider`, with no change to the endpoint,
the grounding, or the widget. The provider receives an ordered message list
(system contract, prior turns, and the final grounded user turn) and returns the
answer text. It never fetches data itself - grounding happens upstream.
"""

from __future__ import annotations

import re

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

        # A greeting / capability answer (the grounding attaches the assistant
        # intro) reads better without the "for your question" framing.
        if "[Assistant]" in context:
            return context.replace("[Assistant] ", "").strip()

        # Grounded answer: present the retrieved context cleanly. Internal
        # "[Help: Title] body" markers become a readable "Related help: Title - body"
        # so nothing raw leaks into the UI. Deterministic.
        cleaned = re.sub(
            r"\[Help: ([^\]]+)\]\s*",
            lambda mm: f"Related help ({mm.group(1)}): ",
            context,
        )
        return cleaned.strip()


class OllamaChatProvider:
    """Chat_Provider backed by a local Ollama server.

    Sends the ordered message list to Ollama's /api/chat endpoint and returns
    the model's reply. Data stays on the local machine (no third-party egress),
    which suits confidential title/deal data. Implements the same ChatProvider
    protocol as the mock, so nothing upstream (grounding, endpoint, widget)
    changes when this is selected.

    The System_Prompt_Contract is the first message in the list, so the model is
    instructed to answer only from the grounded context and to redirect any
    governed-action request - the same guarantees the mock encodes.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.name = "ollama"
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds

    def complete(self, messages: list[ChatMessage]) -> str:
        import httpx

        payload = {
            "model": self._model,
            "stream": False,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            # Low temperature: we want faithful explanation of the grounded
            # context, not creative embellishment.
            "options": {"temperature": 0.2},
        }
        resp = httpx.post(
            f"{self._base_url}/api/chat",
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        content = (data.get("message") or {}).get("content", "")
        if not content:
            raise RuntimeError("Ollama returned an empty completion")
        return content.strip()


def select_provider(settings: object | None = None) -> ChatProvider:
    """Return the configured Chat_Provider, defaulting to the mock.

    ``settings`` is any object exposing a ``chat_provider`` string attribute
    (the app ``Settings``); an unknown/empty value selects the mock so the app
    always has a working provider with no external configuration.
    """
    choice = ""
    if settings is not None:
        choice = str(getattr(settings, "chat_provider", "") or "").strip().lower()

    if choice == "ollama":
        return OllamaChatProvider(
            base_url=str(getattr(settings, "chat_ollama_base_url", "http://host.docker.internal:11434")),
            model=str(getattr(settings, "chat_ollama_model", "llama3.1:latest")),
            timeout_seconds=float(getattr(settings, "chat_ollama_timeout_seconds", 60.0)),
        )

    # Default: the no-cost, no-network deterministic mock. Unknown values also
    # fall back to the mock so the app always has a working provider.
    return MockChatProvider()