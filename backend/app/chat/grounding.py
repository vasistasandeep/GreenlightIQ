"""GroundingService: gather read-only Retrieved_Context for a chat question.

Two source families feed the context and may both contribute:

* Live platform data - the portfolio summary, and (when a title is in scope) that
  title's scorecard, decision, and churn breakdown - read through the existing
  repositories, limited to what the actor may see.
* The Knowledge_Base - curated how-to/concept snippets for How_To_Query questions.

The service performs reads only: no writes, no engine runs, no audit entries, and
no confidential field reaches an actor without READ_CONFIDENTIAL clearance.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.knowledge import DEFAULT_KNOWLEDGE_BASE, KnowledgeBase
from app.core.security import UserContext
from app.engines.rbac import CONFIDENTIAL_ACCESS_ROLES
from app.repositories.financial_projections import FinancialProjectionRepository
from app.repositories.titles import TitleRepository


@dataclass(frozen=True)
class GroundedContext:
    """The retrieved grounding material for one question.

    ``text`` is a compact plain-text block the provider reads; ``sources`` are
    opaque identifiers (``title:<id>``, ``projection:latest``, ``doc:<id>``,
    ``portfolio``) surfaced to the caller for traceability; ``follow_ups`` are
    suggested next questions the UI can render as one-click chips.
    """

    text: str
    sources: tuple[str, ...]
    follow_ups: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


_CAPABILITY_MENU = (
    "[Assistant] I'm CineROI Copilot - a read-only helper. I can: "
    "(1) explain any title's verdict and the four guardrail checks "
    "(try 'why did The Ledger get NEGOTIATE HARD?'); "
    "(2) summarize the portfolio ('how many titles are GREENLIGHT?'); "
    "(3) explain churn, CPVH, LTV, payback, and the content-format/genre drivers; "
    "(4) walk you through how-to tasks (uploading a slate, overrides, backtests, "
    "the CSV template). Ask me anything along those lines, or name a title to dig in. "
    "I report what the platform already computed and never change a decision."
)


def _num(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


class GroundingService:
    """Resolve scope and gather Retrieved_Context for the chat endpoint."""

    def __init__(
        self,
        session: AsyncSession | None,
        actor: UserContext,
        knowledge_base: KnowledgeBase = DEFAULT_KNOWLEDGE_BASE,
        *,
        titles_repo: object | None = None,
        projections_repo: object | None = None,
    ) -> None:
        self._session = session
        self._actor = actor
        # Repositories are normally built from the request session; tests may
        # inject in-memory fakes (the repo-collaborator convention) so grounding
        # is exercisable without a database.
        self._titles = titles_repo if titles_repo is not None else TitleRepository(session)
        self._projections = (
            projections_repo if projections_repo is not None else FinancialProjectionRepository(session)
        )
        self._kb = knowledge_base

    @property
    def _can_read_confidential(self) -> bool:
        return self._actor.role in CONFIDENTIAL_ACCESS_ROLES

    async def gather(self, message: str, title_id: str | None = None) -> GroundedContext:
        """Return the Retrieved_Context for ``message`` under optional ``title_id``.

        Non-exclusive routing: always consult the Knowledge_Base; additionally
        gather data context when a title resolves. Nothing matching -> empty
        context (the provider then answers honestly that it does not know).
        """
        parts: list[str] = []
        sources: list[str] = []

        # 1) Resolve the title in scope (explicit id or name match), robustly.
        title = await self._resolve_title(message, title_id)

        # 2) Data context. A resolved title scopes to that title; otherwise a
        #    data-oriented question (portfolio mention or data keywords) falls
        #    back to the portfolio summary. This is independent of any knowledge
        #    match, so "what is the verdict for <unknown>?" still grounds in the
        #    portfolio rather than only in a concept snippet (R1.3).
        if title is not None:
            data_text, data_sources = await self._title_context(title)
            if data_text:
                parts.append(data_text)
                sources.extend(data_sources)
        elif self._mentions_portfolio(message) or self._looks_data_oriented(message):
            port_text, port_sources = await self._portfolio_context()
            if port_text:
                parts.append(port_text)
                sources.extend(port_sources)

        # 3) Knowledge context (how-to / concepts), always consulted.
        matched_snippets = self._kb.search(message)
        for snippet in matched_snippets:
            parts.append(f"[Help: {snippet.title}] {snippet.body}")
            sources.append(f"doc:{snippet.id}")

        # 4) Greeting / vague-intent handling: a hello, a bare "help", or a
        #    general "how it works" should never dead-end. Offer a live portfolio
        #    snapshot plus a short menu of what the assistant can do, so every
        #    conversation starts somewhere useful (not an "I don't know").
        if self._is_greeting_or_help(message) and "portfolio" not in sources:
            port_text, port_sources = await self._portfolio_context()
            if port_text:
                parts.append(port_text)
                sources.extend(port_sources)
            parts.append(_CAPABILITY_MENU)
            sources.append("doc:assistant-intro")

        # 5) Last-resort fallback: if nothing matched at all, still be helpful -
        #    surface the portfolio snapshot and the capability menu rather than a
        #    bare "I don't know", so the user always has a next step.
        if not sources:
            port_text, port_sources = await self._portfolio_context()
            if port_text:
                parts.append(port_text)
                sources.extend(port_sources)
            parts.append(_CAPABILITY_MENU)
            sources.append("doc:assistant-intro")

        follow_ups = self._follow_ups(
            message=message,
            title=title,
            snippet_ids=[s.id for s in matched_snippets],
            sources=sources,
        )
        return GroundedContext(
            text="\n\n".join(parts).strip(),
            sources=tuple(sources),
            follow_ups=tuple(follow_ups),
        )

    def _follow_ups(
        self, *, message: str, title, snippet_ids: list[str], sources: list[str]
    ) -> list[str]:
        """Suggest up to 3 relevant next questions that ADVANCE the conversation.

        Question-aware: suggestions never repeat what was just asked (normalized
        match), so clicking a chip always moves to a genuinely new question.
        Deterministic and purely presentational.
        """
        asked = self._norm(message)
        candidates: list[str] = []
        name = getattr(title, "title_name", None)

        if name:
            # A pool of distinct title drill-downs; we drop whatever matches the
            # question just asked so the chips keep changing as the user clicks.
            candidates = [
                f"How is {name}'s churn mitigation calculated?",
                f"What price would make {name} clear?",
                f"Which guardrail breached hardest for {name}?",
                f"How does {name}'s CPVH compare to its ceiling?",
                f"What is {name}'s LTV-to-Cost multiple?",
                f"What content format and genre does {name} use?",
                f"Is {name} a GREENLIGHT, NEGOTIATE HARD, or PASS - and why?",
            ]
        else:
            neighbours = {
                "concept-cpvh": ["What drives the LTV-to-Cost multiple?", "What is a good CPVH?"],
                "concept-ltv": ["How is CPVH calculated?", "What is churn mitigation?"],
                "concept-churn": ["Why is a churn breach non-correctable?", "How does content format affect churn?"],
                "concept-verdicts": ["What's the difference between NEGOTIATE HARD and PASS?", "What are the four guardrails?"],
                "concept-guardrails": ["What is CPVH?", "What is churn mitigation?"],
                "concept-content-format": ["How does genre affect churn?", "What is churn mitigation?"],
                "how-to-batch-slate": ["What columns does the slate CSV need?", "How do I evaluate a single title?"],
                "how-to-override": ["Who is allowed to override a recommendation?", "How is an override audited?"],
                "how-to-backtest-audit": ["What is MAPE?", "How does model calibration work?"],
            }
            for sid in snippet_ids:
                candidates.extend(neighbours.get(sid, []))
            if "portfolio" in sources or "doc:assistant-intro" in sources:
                candidates.extend([
                    "Why did The Ledger get NEGOTIATE HARD?",
                    "How many titles are GREENLIGHT?",
                    "What is churn mitigation?",
                    "How do I upload a slate?",
                    "What are the four guardrails?",
                ])

        # De-dupe, drop the just-asked question, cap at 3.
        out: list[str] = []
        for q in candidates:
            if self._norm(q) == asked:
                continue
            if q not in out:
                out.append(q)
            if len(out) == 3:
                break
        return out

    @staticmethod
    def _norm(text: str) -> str:
        import re as _re
        return _re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()

    def _is_greeting_or_help(self, message: str) -> bool:
        q = (message or "").strip().lower()
        if q in {"hi", "hello", "hey", "yo", "help", "start", "menu", "?", "hi!", "hello!"}:
            return True
        return any(
            kw in q
            for kw in (
                "how it works", "how does this work", "what can you do",
                "what can i ask", "get started", "getting started", "what do you do",
                "who are you", "what is this",
            )
        )

    # --- resolution -------------------------------------------------------- #

    async def _resolve_title(self, message: str, title_id: str | None):
        if title_id:
            try:
                tid = uuid.UUID(str(title_id))
            except (ValueError, AttributeError, TypeError):
                tid = None
            if tid is not None:
                try:
                    found = await self._titles.get(tid)
                except Exception:
                    found = None
                if found is not None:
                    return found
            # malformed or missing -> fall through to name match / portfolio

        lowered = (message or "").lower()
        try:
            all_titles = await self._titles.list()
        except Exception:
            return None

        # Exact full-name substring first (most precise).
        exact = [t for t in all_titles if t.title_name and t.title_name.lower() in lowered]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            return None

        # Otherwise match on the title's significant words, so "Ledger" resolves
        # "The Ledger" and "Aurora" resolves "Aurora Protocol". A match requires
        # every significant word of a title to appear in the message; the title
        # with the most matched words wins when unambiguous.
        _STOP = {"the", "a", "an", "of", "and", "vol", "vol.", "part", "ii", "iii"}
        best = []
        for t in all_titles:
            if not t.title_name:
                continue
            words = [w for w in t.title_name.lower().replace(".", "").split() if w not in _STOP]
            if not words:
                continue
            hits = sum(1 for w in words if w in lowered)
            if hits > 0:
                best.append((hits, len(words), t))
        if not best:
            return None
        best.sort(key=lambda x: -x[0])
        top = best[0][0]
        leaders = [b for b in best if b[0] == top]
        if len(leaders) == 1:
            return leaders[0][2]
        return None

    def _mentions_portfolio(self, message: str) -> bool:
        q = (message or "").lower()
        return any(
            kw in q
            for kw in ("portfolio", "all titles", "pipeline", "how many", "which titles", "every title", "dashboard")
        )

    def _looks_data_oriented(self, message: str) -> bool:
        q = (message or "").lower()
        return any(
            kw in q
            for kw in ("verdict", "churn", "cpvh", "ltv", "payback", "greenlight", "negotiate", "pass", "recommendation", "risk", "value")
        )

    # --- context builders -------------------------------------------------- #

    async def _title_context(self, title) -> tuple[str, list[str]]:
        projection = await self._projections.get_latest_for_title(title.title_id)
        sources = [f"title:{title.title_id}"]
        lines = [
            f"Title: {title.title_name} (asset type {title.asset_type}).",
        ]
        if not self._can_read_confidential:
            lines.append("(Confidential deal terms are hidden for your role.)")

        if projection is None:
            lines.append("No computed valuation exists for this title yet (valuation pending).")
            return "\n".join(lines), sources

        sources.append("projection:latest")
        lines.append(f"Recommendation: {projection.recommendation_status or 'n/a'}.")
        lines.append(f"CPVH: {_num(projection.calculated_cpvh)}; LTV-to-Cost multiple: {_num(projection.ltv_to_cost_multiple)}.")
        if getattr(projection, "churn_reduction_pct", None) is not None:
            lines.append(f"Churn mitigation: {_num(projection.churn_reduction_pct)}% (1.5% hurdle; a churn breach is non-correctable).")
        if projection.normalized_cost_usd is not None:
            lines.append(f"Normalized cost (USD): {_num(projection.normalized_cost_usd)}.")

        explanation = projection.explanation if isinstance(projection.explanation, dict) else {}
        dominant = explanation.get("dominant_factor")
        if dominant:
            lines.append(f"Dominant factor behind the verdict: {dominant}.")
        checks = explanation.get("checks")
        if isinstance(checks, list) and checks:
            _CHECK_LABELS = {
                "cpvh": "Cost per Viewing Hour",
                "CPVH": "Cost per Viewing Hour",
                "ltv_to_cost": "LTV-to-Cost multiple",
                "LTV_TO_COST": "LTV-to-Cost multiple",
                "churn_mitigation": "Churn mitigation",
                "CHURN_MITIGATION": "Churn mitigation",
                "payback_horizon": "Payback horizon",
                "PAYBACK_HORIZON": "Payback horizon",
            }
            check_bits = []
            for c in checks:
                if isinstance(c, dict) and c.get("name"):
                    label = _CHECK_LABELS.get(c["name"], str(c["name"]))
                    if c.get("breached"):
                        corr = "correctable" if c.get("correctable") else "non-correctable"
                        check_bits.append(f"{label} - breached ({corr})")
                    else:
                        check_bits.append(f"{label} - passed")
            if check_bits:
                lines.append("Guardrail checks: " + "; ".join(check_bits) + ".")
        churn_model = explanation.get("churn_model")
        if isinstance(churn_model, dict) and churn_model.get("breakdown"):
            lines.append("Churn breakdown is available (per-feature contributions).")

        return "\n".join(lines), sources

    async def _portfolio_context(self) -> tuple[str, list[str]]:
        try:
            titles = await self._titles.list()
        except Exception:
            return "", []
        if not titles:
            return "Portfolio: no titles in the pipeline yet.", ["portfolio"]
        counts: dict[str, int] = {}
        valued = 0
        for t in titles:
            proj = await self._projections.get_latest_for_title(t.title_id)
            if proj is not None and proj.recommendation_status:
                valued += 1
                counts[proj.recommendation_status] = counts.get(proj.recommendation_status, 0) + 1
        verdict_bits = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "none valued yet"
        text = (
            f"Portfolio overview: {len(titles)} titles in the pipeline, {valued} valued. "
            f"Verdicts - {verdict_bits}."
        )
        return text, ["portfolio"]