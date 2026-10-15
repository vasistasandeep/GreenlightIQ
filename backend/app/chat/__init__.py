"""Data_Chat_Assistant: a read-only, grounded conversational layer.

The assistant answers plain-language questions about platform data (verdicts,
guardrail checks, churn, the portfolio) and how-to/concept questions, by
retrieving real records and curated knowledge snippets and having a pluggable
Chat_Provider phrase the answer. It computes nothing and changes nothing - the
deterministic engines remain the sole source of every number.
"""