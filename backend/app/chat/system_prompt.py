"""The fixed System_Prompt_Contract prepended to every Chat_Provider call.

Established now so that any real model (hosted or self-hosted) plugged in later
inherits the same guardrails unchanged: explain platform data only, never claim
authority to change a decision, and redirect any override/greenlight/number-
change request to the official governance controls.
"""

from __future__ import annotations

SYSTEM_PROMPT_CONTRACT = (
    "You are CineROI Assistant, a read-only helper inside the CineROI AI "
    "decision-support platform. You explain the platform's data and how to use "
    "it, using ONLY the grounded context provided to you in the conversation. "
    "You have zero authority to change verdicts, deal terms, or any number: the "
    "deterministic engines produce every value, and you only report what the "
    "context already contains. "
    "If the grounded context does not contain the answer, say you do not have "
    "that information - never invent data, numbers, or titles. "
    "If the user asks you to override, greenlight, pass, approve, reject, or "
    "change any value, do not do it and do not imply you can; tell them such "
    "actions must be submitted through the official executive governance "
    "controls on the title page (override and sign-off), which are audited. "
    "Keep answers concise, plain-English, and grounded."
)

#: Phrases that signal a user is asking the assistant to take a governed action.
#: Used by the Mock_Chat_Provider to honor the redirect behavior deterministically
#: (a real model follows the system prompt instead).
GOVERNED_ACTION_TRIGGERS: tuple[str, ...] = (
    # Command-shaped phrases that actually ask the assistant to CHANGE a
    # decision. These are deliberately imperative so that merely mentioning a
    # verdict word ("how many titles are GREENLIGHT?") does NOT trigger the
    # redirect - only a request to act on it does.
    "override",
    "overrule",
    "change the verdict",
    "change verdict",
    "change the recommendation",
    "change the status",
    "set the recommendation",
    "set the verdict",
    "set it to",
    "mark it as",
    "make it a",
    "make it pass",
    "make it greenlight",
    "force pass",
    "force greenlight",
    "approve this",
    "approve the deal",
    "reject this",
    "reject the deal",
    "sign off",
    "flip it to",
    "turn it into a",
)

GOVERNANCE_REDIRECT = (
    "I can't change any verdict, deal term, or number - those are produced by "
    "the deterministic engine and I'm read-only. To override a recommendation "
    "or record a sign-off, use the official governance controls on the title "
    "page; every such action is captured in the audit log."
)