"""Knowledge_Base: curated how-to and concept snippets for the assistant.

Static, versioned reference content sourced from the in-portal How It Works
guide (Features & How-To recipes + glossary) and the knowledge docs. It lets the
assistant answer How_To_Query questions ("how do I upload a slate?", "what is
CPVH?") from documentation rather than inventing guidance. This is not user data
and nothing here is confidential; it is shipped with the backend.

Retrieval is a deterministic case-insensitive keyword/substring match - no NLP,
no network, no database.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class KnowledgeSnippet:
    """One how-to or concept entry. ``id`` is stable and surfaced as ``doc:<id>``."""

    id: str
    title: str
    keywords: tuple[str, ...]
    body: str


# --------------------------------------------------------------------------- #
# How-to recipes (mirror frontend/app/guide/page.tsx Features & How-To tab).
# --------------------------------------------------------------------------- #
_HOW_TO: tuple[KnowledgeSnippet, ...] = (
    KnowledgeSnippet(
        id="how-to-evaluate-single",
        title="Evaluate a single title",
        keywords=("evaluate", "single", "asset studio", "valuation", "run", "scorecard", "one title"),
        body=(
            "Open Asset Studio (/studio); the Single Asset tab is selected by default. "
            "Fill in Title, Asset Type, Cost & Currency, and a Synopsis (the rest is "
            "optional), then press RUN ROI VALUATION. The scorecard appears on the "
            "right; click View Full Deep-Dive Analysis to open the title page. Not sure "
            "what to type? Click a Quick Preset to fill and run a sample instantly."
        ),
    ),
    KnowledgeSnippet(
        id="how-to-batch-slate",
        title="Ingest a whole slate (CSV / JSON) and the CSV template",
        keywords=("batch", "slate", "upload", "csv", "json", "catalog", "bulk", "ingest", "template", "download template"),
        body=(
            "In Asset Studio switch to the Batch Slate tab. New to the format? Click "
            "Download CSV template to get a ready-made file with the header row, every "
            "allowed value as a comment hint, and three example titles; fill in your rows "
            "and remove the examples. Then choose the format (CSV or JSON), upload a file "
            "or paste the contents (each row needs at least a title name and a cost), and "
            "press Ingest slate. A live indicator tracks the background job; when it "
            "finishes you see how many rows were accepted vs rejected, with a reason per "
            "rejected row. Rejected rows never block the batch."
        ),
    ),
    KnowledgeSnippet(
        id="how-to-pitch-pdf",
        title="Auto-fill the form from a pitch / script PDF",
        keywords=("pitch", "pdf", "auto-fill", "autofill", "drop", "script", "deck", "parse"),
        body=(
            "At the top of the Single Asset form, click the 'Drop a script / pitch PDF' "
            "box and choose a PDF. It reads the document and pre-fills recognized fields "
            "(title, synopsis, genre, budget) for you to review - nothing is submitted "
            "automatically. It is best-effort: a messy deck may fill only some fields."
        ),
    ),
    KnowledgeSnippet(
        id="how-to-shorthand-cost",
        title="Enter the budget in shorthand (Cr / Lakh / M / k)",
        keywords=("shorthand", "cost", "budget", "crore", "lakh", "million", "amount", "currency"),
        body=(
            "In the Cost field, type amounts like 12 Cr, 1.5M, 500k, or 3 Lakh; a live "
            "preview shows the full number so you can confirm it. Pick the matching "
            "currency (USD / INR / EUR / GBP); everything is normalized to USD before any "
            "check. Plain numbers with commas work too."
        ),
    ),
    KnowledgeSnippet(
        id="how-to-what-if",
        title="Stress-test with What-If sliders",
        keywords=("what-if", "what if", "sensitivity", "slider", "scenario", "stress"),
        body=(
            "On a title page, find the What-if sensitivity panel and drag the Cost, "
            "Viewership (bear/base/bull), or Churn sliders. The recommendation and the "
            "four metrics recompute live after you stop dragging. Nothing is saved - it "
            "is a scenario preview; set every slider to 100% to reproduce the saved "
            "scorecard."
        ),
    ),
    KnowledgeSnippet(
        id="how-to-override",
        title="Override a recommendation (with a reason)",
        keywords=("override", "change recommendation", "manual", "verdict change", "governance"),
        body=(
            "On the title page click Override recommendation, pick the new status, and "
            "type a mandatory business justification, then press Record override. The "
            "verdict updates and the change is written to the audit log. Only decision-"
            "making roles may override; others get a 'not permitted' message. (The chat "
            "assistant cannot do this for you - overrides go through these audited "
            "controls.)"
        ),
    ),
    KnowledgeSnippet(
        id="how-to-export-memo",
        title="Export a Greenlight Memo (PDF)",
        keywords=("export", "memo", "pdf", "greenlight memo", "print", "committee"),
        body=(
            "On the title page click Export Greenlight Memo (PDF). Your browser's print "
            "dialog opens with a paper-friendly brief (financial summary, guardrail "
            "checks, negotiation playbook, sign-off block). Choose 'Save as PDF' or "
            "print; only the memo prints, not the app chrome."
        ),
    ),
    KnowledgeSnippet(
        id="how-to-backtest-audit",
        title="Audit a prediction against reality (Backtest Studio)",
        keywords=("backtest", "audit", "ground truth", "actual", "accuracy", "mape", "predicted"),
        body=(
            "Open Backtest Studio (/backtest), pick a title with a stored prediction, and "
            "enter the actual CPVH and LTV-to-Cost (the predicted values show read-only "
            "beside them). Press Run audit to see Predicted vs Actual and the overall "
            "Prediction Error (MAPE - lower is better)."
        ),
    ),
    KnowledgeSnippet(
        id="how-to-signoff",
        title="Clear a high-budget executive sign-off",
        keywords=("sign-off", "signoff", "approval", "cco", "cfo", "high budget", "25m", "finalize"),
        body=(
            "A GREENLIGHT whose normalized cost exceeds $25M needs both the Chief Content "
            "Officer and the CFO to approve before it is final. In the Backtest Studio "
            "Executive Sign-Off panel, each outstanding role shows an 'Approve as...' "
            "button; once both CCO and CFO are in, the gate flips to Ready to finalize. "
            "Non-high-budget decisions show 'No sign-off required'."
        ),
    ),
    KnowledgeSnippet(
        id="how-to-chat-assistant",
        title="Use the chat assistant",
        keywords=("chat", "assistant", "ask", "chatbot", "help", "how to use chat"),
        body=(
            "Open the chat button in the corner of the portal and ask a plain-language "
            "question. It answers two kinds: questions about your data (a title's verdict, "
            "guardrail checks, churn, the portfolio) and how-to/concept questions (how to "
            "upload a slate, what CPVH means). It is read-only and grounded - it only "
            "reports values the engine already produced and help content it can see, and "
            "says so when it doesn't know. It never changes a decision."
        ),
    ),
)

# --------------------------------------------------------------------------- #
# Concept / glossary snippets (mirror the guide glossary + Calculations ref).
# --------------------------------------------------------------------------- #
_CONCEPTS: tuple[KnowledgeSnippet, ...] = (
    KnowledgeSnippet(
        id="concept-cpvh",
        title="CPVH (Cost per Viewing Hour)",
        keywords=("cpvh", "cost per viewing hour", "per hour", "viewing hour"),
        body=(
            "CPVH is normalized cost (USD) divided by projected viewing hours - what a "
            "deal costs per hour watched. Lower is better. The ceiling is $0.18/hour for "
            "premium originals and $0.05/hour for licensed library. Crossing the ceiling "
            "is a correctable (price) breach."
        ),
    ),
    KnowledgeSnippet(
        id="concept-ltv",
        title="LTV-to-Cost multiple",
        keywords=("ltv", "ltv-to-cost", "lifetime value", "multiple", "svod", "avod"),
        body=(
            "The LTV-to-Cost multiple is total modeled lifetime value divided by "
            "normalized cost. The value splits into SVOD subscription value (retention) "
            "and AVOD ad-yield value (advertising). A multiple below the floor is a "
            "correctable (price) breach."
        ),
    ),
    KnowledgeSnippet(
        id="concept-churn",
        title="Churn mitigation",
        keywords=("churn", "churn mitigation", "retention", "cancel", "1.5", "non-correctable"),
        body=(
            "Churn mitigation is the modeled monthly churn-reduction percentage a title "
            "delivers; it must clear a 1.5% hurdle. It is built additively from the asset "
            "type, talent pedigree, production scale, exclusivity, market telemetry, the "
            "genre affinity, and the content format - each contribution is shown. A churn "
            "breach is non-correctable: no discount fixes it, so it forces PASS."
        ),
    ),
    KnowledgeSnippet(
        id="concept-payback",
        title="Payback horizon",
        keywords=("payback", "break-even", "break even", "horizon", "months", "cumulative margin"),
        body=(
            "The payback horizon is the month cumulative contribution margin turns "
            "positive (break-even). A horizon beyond the target window is a correctable "
            "breach."
        ),
    ),
    KnowledgeSnippet(
        id="concept-verdicts",
        title="The three verdicts",
        keywords=("verdict", "greenlight", "negotiate", "negotiate hard", "pass", "recommendation"),
        body=(
            "Every title gets one of three answers. GREENLIGHT: all four checks pass, buy "
            "it as proposed. NEGOTIATE HARD: the only problems are price problems - there "
            "is a lower price at which it clears, so haggle. PASS: a problem no price can "
            "fix (almost always a churn breach), so walk away."
        ),
    ),
    KnowledgeSnippet(
        id="concept-guardrails",
        title="The four guardrails",
        keywords=("guardrail", "four checks", "breach", "threshold", "ceiling", "correctable"),
        body=(
            "A title must pass four quantitative checks: CPVH (cost per viewing hour), "
            "LTV-to-Cost multiple, churn mitigation, and payback horizon. A breach is a "
            "check crossing its threshold the wrong way. Price-correctable breaches lead "
            "to NEGOTIATE HARD; a non-correctable breach (churn) forces PASS."
        ),
    ),
    KnowledgeSnippet(
        id="concept-content-format",
        title="Content format driver",
        keywords=("content format", "live sports", "live event", "reality", "format", "appointment"),
        body=(
            "Content Format (live sports, live event, reality/competition, scripted "
            "series, film, library) adds an extra churn lift for live/appointment formats "
            "that the asset type cannot express - a live match is far stickier than a "
            "one-and-done film. Formats the asset type already covers add zero lift."
        ),
    ),
    KnowledgeSnippet(
        id="concept-genre",
        title="Genre affinity driver",
        keywords=("genre", "genre affinity", "crime", "drama", "weight"),
        body=(
            "Genre drives a per-genre churn-affinity weight: serialized/returning formats "
            "(crime, drama, thriller, reality) retain subscribers more than one-and-done "
            "formats. An unlisted genre uses a neutral weight."
        ),
    ),
    KnowledgeSnippet(
        id="concept-rbac-roles",
        title="User roles (RBAC)",
        keywords=("role", "rbac", "data analyst", "content buyer", "cco", "cfo", "permission", "confidential"),
        body=(
            "Each user holds exactly one role: DATA_ANALYST, CONTENT_BUYER, CHIEF_CONTENT_"
            "OFFICER (CCO), or CFO. Overrides are reserved for decision-making roles. "
            "Confidential fields (scripts, deal terms, PII) are hidden from roles not "
            "cleared to see them; the chat assistant inherits the same scoping."
        ),
    ),
)

ALL_SNIPPETS: tuple[KnowledgeSnippet, ...] = _HOW_TO + _CONCEPTS


@dataclass(frozen=True)
class KnowledgeBase:
    """A searchable, static set of how-to/concept snippets."""

    snippets: tuple[KnowledgeSnippet, ...] = field(default=ALL_SNIPPETS)

    def search(self, query: str, limit: int = 3) -> list[KnowledgeSnippet]:
        """Return up to ``limit`` snippets matching ``query`` by keyword/title.

        Deterministic: snippets are scored by how many of their keywords (and
        their title words) appear as substrings of the lowercased query; ties
        break by declaration order. Returns an empty list when nothing matches.
        """
        q = (query or "").lower()
        if not q.strip():
            return []
        scored: list[tuple[int, int, KnowledgeSnippet]] = []
        for order, snip in enumerate(self.snippets):
            score = sum(1 for kw in snip.keywords if kw in q)
            # Title words give a light boost so direct term questions match.
            score += sum(1 for word in snip.title.lower().split() if len(word) > 3 and word in q)
            if score > 0:
                scored.append((score, order, snip))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [snip for _, _, snip in scored[:limit]]


#: Shared default instance.
DEFAULT_KNOWLEDGE_BASE = KnowledgeBase()