"""Tests for the Chat_Provider interface, Mock_Chat_Provider, and system prompt.

Pure unit tests - no DB, no network, no API key (Requirements 3.2, 3.3, 3.4, 3.6).
"""

from __future__ import annotations

from app.chat.provider import (
    CONTEXT_MARKER,
    NO_INFORMATION,
    QUESTION_MARKER,
    ChatMessage,
    ChatProvider,
    MockChatProvider,
    select_provider,
)
from app.chat.system_prompt import (
    GOVERNANCE_REDIRECT,
    SYSTEM_PROMPT_CONTRACT,
)


class _Settings:
    def __init__(self, chat_provider: str) -> None:
        self.chat_provider = chat_provider


def _grounded_user(context: str, question: str) -> ChatMessage:
    return ChatMessage(
        role="user",
        content=f"{CONTEXT_MARKER}\n{context}\n{QUESTION_MARKER}\n{question}",
    )


def test_select_provider_defaults_to_mock() -> None:
    assert isinstance(select_provider(None), MockChatProvider)
    assert isinstance(select_provider(_Settings("")), MockChatProvider)
    assert isinstance(select_provider(_Settings("mock")), MockChatProvider)
    # Unknown provider still yields a working provider (the mock), never crashes.
    assert isinstance(select_provider(_Settings("some-future-llm")), MockChatProvider)


def test_mock_is_a_chat_provider() -> None:
    assert isinstance(MockChatProvider(), ChatProvider)


def test_mock_is_deterministic() -> None:
    provider = MockChatProvider()
    msgs = [
        ChatMessage(role="system", content=SYSTEM_PROMPT_CONTRACT),
        _grounded_user("Title: The Ledger. Recommendation: NEGOTIATE_HARD.", "what is the verdict?"),
    ]
    first = provider.complete(msgs)
    second = provider.complete(msgs)
    assert first == second
    assert "NEGOTIATE_HARD" in first


def test_mock_honest_when_context_empty() -> None:
    provider = MockChatProvider()
    msgs = [_grounded_user("", "what is the meaning of life?")]
    assert provider.complete(msgs) == NO_INFORMATION


def test_mock_redirects_governed_action_requests() -> None:
    provider = MockChatProvider()
    for ask in ("override The Ledger to greenlight", "approve this deal", "make it pass"):
        msgs = [_grounded_user("Title: The Ledger.", ask)]
        assert provider.complete(msgs) == GOVERNANCE_REDIRECT


def test_mock_no_user_message_is_honest() -> None:
    provider = MockChatProvider()
    assert provider.complete([ChatMessage(role="system", content="x")]) == NO_INFORMATION


def test_system_prompt_contract_present_and_constraining() -> None:
    assert SYSTEM_PROMPT_CONTRACT
    lowered = SYSTEM_PROMPT_CONTRACT.lower()
    assert "read-only" in lowered or "read only" in lowered
    assert "governance" in lowered
    assert "override" in lowered