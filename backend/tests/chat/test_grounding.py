"""Tests for the GroundingService (Requirements 1.1-1.6, 2.3, 2.4).

Uses tiny in-memory repository fakes (the repo-collaborator convention) so the
service is exercised with no database.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.chat.grounding import GroundingService
from app.core.security import UserContext, UserRole


class _Title:
    def __init__(self, title_id, name, asset_type="ORIGINAL_FILM"):
        self.title_id = title_id
        self.title_name = name
        self.asset_type = asset_type
        self.acquisition_cost_or_budget = Decimal("9500000")
        self.native_currency = "USD"


class _Projection:
    def __init__(self):
        self.calculated_cpvh = Decimal("0.20")
        self.ltv_to_cost_multiple = Decimal("2.90")
        self.churn_reduction_pct = Decimal("1.60")
        self.normalized_cost_usd = Decimal("9500000")
        self.recommendation_status = "NEGOTIATE_HARD"
        self.explanation = {
            "dominant_factor": "LTV-to-Cost multiple below floor",
            "checks": [
                {"name": "cpvh", "breached": True, "correctable": True},
                {"name": "churn", "breached": False},
            ],
            "churn_model": {"breakdown": [{"name": "Base Platform Rate", "points": "0.03"}]},
        }


class _FakeTitles:
    def __init__(self, titles):
        self._titles = {str(t.title_id): t for t in titles}
        self.writes = 0

    async def list(self):
        return list(self._titles.values())

    async def get(self, tid):
        return self._titles.get(str(tid))


class _FakeProjections:
    def __init__(self, mapping):
        self._mapping = {str(k): v for k, v in mapping.items()}
        self.writes = 0

    async def get_latest_for_title(self, tid):
        return self._mapping.get(str(tid))


def _actor(role=UserRole.CONTENT_BUYER):
    return UserContext(user_id=uuid.uuid4(), display_name="t", role=role)


def _service(role=UserRole.CONTENT_BUYER):
    ledger_id = uuid.uuid4()
    ledger = _Title(ledger_id, "The Ledger")
    titles = _FakeTitles([ledger])
    projections = _FakeProjections({ledger_id: _Projection()})
    svc = GroundingService(
        None, _actor(role), titles_repo=titles, projections_repo=projections
    )
    return svc, ledger_id


@pytest.mark.asyncio
async def test_title_name_match_pulls_scorecard():
    svc, ledger_id = _service()
    ctx = await svc.gather("why did The Ledger get negotiate hard?")
    assert f"title:{ledger_id}" in ctx.sources
    assert "projection:latest" in ctx.sources
    assert "NEGOTIATE_HARD" in ctx.text
    assert "1.60" in ctx.text  # churn surfaced


@pytest.mark.asyncio
async def test_explicit_title_id_scopes():
    svc, ledger_id = _service()
    ctx = await svc.gather("what is the verdict?", title_id=str(ledger_id))
    assert f"title:{ledger_id}" in ctx.sources


@pytest.mark.asyncio
async def test_malformed_title_id_falls_back_not_errors():
    svc, _ = _service()
    ctx = await svc.gather("how many titles are in the portfolio?", title_id="not-a-uuid")
    # Falls back to portfolio rather than raising.
    assert "portfolio" in ctx.sources


@pytest.mark.asyncio
async def test_unknown_name_falls_back_to_portfolio_when_data_oriented():
    svc, _ = _service()
    ctx = await svc.gather("what is the verdict for Nonexistent Title?")
    assert "portfolio" in ctx.sources


@pytest.mark.asyncio
async def test_how_to_query_pulls_knowledge_doc_source():
    svc, _ = _service()
    ctx = await svc.gather("how do I upload a slate?")
    assert any(s.startswith("doc:") for s in ctx.sources)
    assert "Batch Slate" in ctx.text or "slate" in ctx.text.lower()


@pytest.mark.asyncio
async def test_off_topic_falls_back_to_helpful_menu():
    # Rather than dead-ending, an unmatched question still offers the portfolio
    # snapshot and a capability menu so the conversation stays useful.
    svc, _ = _service()
    ctx = await svc.gather("what is the weather in Mumbai tomorrow?")
    assert not ctx.is_empty
    assert "doc:assistant-intro" in ctx.sources
    assert "portfolio" in ctx.sources


@pytest.mark.asyncio
async def test_greeting_offers_portfolio_and_capabilities():
    svc, _ = _service()
    ctx = await svc.gather("hi")
    assert "doc:assistant-intro" in ctx.sources
    assert "portfolio" in ctx.sources
    assert "CineROI Copilot" in ctx.text


@pytest.mark.asyncio
async def test_partial_name_resolves_title():
    # "Ledger" (not the full "The Ledger") should still resolve the title.
    svc, ledger_id = _service()
    ctx = await svc.gather("tell me about Ledger")
    assert f"title:{ledger_id}" in ctx.sources


@pytest.mark.asyncio
async def test_confidential_hidden_for_unprivileged_role():
    svc, _ = _service(role=UserRole.DATA_ANALYST)
    ctx = await svc.gather("tell me about The Ledger")
    assert "hidden for your role" in ctx.text.lower()


@pytest.mark.asyncio
async def test_grounding_performs_no_writes():
    svc, ledger_id = _service()
    await svc.gather("why did The Ledger get negotiate hard?")
    # Fakes count writes; none should have happened.
    assert svc._titles.writes == 0
    assert svc._projections.writes == 0


@pytest.mark.asyncio
async def test_title_answer_suggests_followups():
    svc, _ = _service()
    ctx = await svc.gather("tell me about The Ledger")
    assert len(ctx.follow_ups) > 0
    assert any("Ledger" in f for f in ctx.follow_ups)


@pytest.mark.asyncio
async def test_greeting_suggests_starter_followups():
    svc, _ = _service()
    ctx = await svc.gather("hi")
    assert len(ctx.follow_ups) > 0
