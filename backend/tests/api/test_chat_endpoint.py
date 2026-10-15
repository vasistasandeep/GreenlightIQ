"""HTTP-contract tests for the chat endpoint (R1.4-1.6, R2, R4).

Drives POST /api/v1/chat through FastAPI's TestClient with the shared deps
overridden by in-memory doubles - no database, broker, or SSO. The endpoint's
own responsibilities are pinned here: auth gating, empty-message rejection,
source passthrough, governance redirect, provider-failure envelope, and the
read-only guarantee (the fake grounding records any write attempts).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api import chat as chat_module
from app.api import deps
from app.chat.grounding import GroundedContext
from app.core.security import UserContext, UserRole
from app.engines.rbac import RBACService
from app.main import create_app


@pytest.fixture()
def app():
    return create_app()


def _user(role=UserRole.CONTENT_BUYER):
    return UserContext(user_id=uuid.uuid4(), display_name="t", role=role)


class _FakeGrounding:
    """Stands in for GroundingService; returns a canned context, records writes."""

    last_message = None
    context = GroundedContext(
        text="Title: The Ledger. Recommendation: NEGOTIATE_HARD.",
        sources=("title:abc", "projection:latest"),
    )

    def __init__(self, session, actor):
        self.session = session
        self.actor = actor
        self.writes = 0

    async def gather(self, message, title_id=None):
        _FakeGrounding.last_message = message
        return self.context


def _client(app, monkeypatch, grounding=_FakeGrounding, user=None):
    user = user or _user()

    def _fake_session():
        yield object()

    app.dependency_overrides[deps.get_db_session] = _fake_session
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_rbac_service] = RBACService
    monkeypatch.setattr(chat_module, "GroundingService", grounding)
    # Pin the deterministic mock provider so the endpoint contract tests never
    # depend on ambient CINEROI_CHAT_PROVIDER config (e.g. a live Ollama).
    from app.chat.provider import MockChatProvider

    monkeypatch.setattr(chat_module, "select_provider", lambda settings: MockChatProvider())
    return TestClient(app, raise_server_exceptions=False)


def test_grounded_answer_returns_sources(app, monkeypatch):
    client = _client(app, monkeypatch)
    resp = client.post("/api/v1/chat", json={"message": "why did The Ledger get negotiate hard?"})
    assert resp.status_code == 200
    body = resp.json()
    assert "NEGOTIATE_HARD" in body["answer"]
    assert body["sources"] == ["title:abc", "projection:latest"]


def test_empty_message_rejected(app, monkeypatch):
    client = _client(app, monkeypatch)
    resp = client.post("/api/v1/chat", json={"message": "   "})
    assert resp.status_code == 422


def test_requires_authentication(app):
    # No get_current_user override -> the real dependency rejects (401).
    def _fake_session():
        yield object()

    app.dependency_overrides[deps.get_db_session] = _fake_session
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/v1/chat", json={"message": "hello"})
    assert resp.status_code == 401


def test_governance_redirect_for_override_request(app, monkeypatch):
    client = _client(app, monkeypatch)
    resp = client.post("/api/v1/chat", json={"message": "override The Ledger to greenlight"})
    assert resp.status_code == 200
    answer = resp.json()["answer"].lower()
    assert "can't change" in answer or "cannot change" in answer or "read-only" in answer
    assert "governance" in answer


def test_provider_failure_returns_clean_envelope(app, monkeypatch):
    class _Boom:
        name = "boom"

        def complete(self, messages):
            raise RuntimeError("secret internal detail: api key xyz")

    client = _client(app, monkeypatch)
    # Override after _client so the boom provider (not the pinned mock) is used.
    monkeypatch.setattr(chat_module, "select_provider", lambda settings: _Boom())
    resp = client.post("/api/v1/chat", json={"message": "hi"})
    assert resp.status_code == 503
    # The internal detail must not leak in any mode (incl. dev debug).
    assert "secret internal detail" not in resp.text
    assert "api key" not in resp.text
    body = resp.json()
    assert body["error_code"] == "CHAT_PROVIDER_UNAVAILABLE"


def test_endpoint_runs_no_writes(app, monkeypatch):
    # The fake grounding would record writes; a grounded read must not write.
    created = {}

    class _TrackingGrounding(_FakeGrounding):
        def __init__(self, session, actor):
            super().__init__(session, actor)
            created["instance"] = self

    client = _client(app, monkeypatch, grounding=_TrackingGrounding)
    resp = client.post("/api/v1/chat", json={"message": "tell me about The Ledger"})
    assert resp.status_code == 200
    assert created["instance"].writes == 0


def test_no_trailing_slash_resolves_without_redirect(app, monkeypatch):
    client = _client(app, monkeypatch)
    # follow_redirects=False: a 307 here would mean the empty-path route is wrong.
    resp = client.post(
        "/api/v1/chat", json={"message": "hello"}, follow_redirects=False
    )
    assert resp.status_code == 200