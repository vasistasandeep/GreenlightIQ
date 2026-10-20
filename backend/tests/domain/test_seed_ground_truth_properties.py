"""Property-based test for the demo ground-truth seed rows.

Feature: dashboard-accuracy-and-payback-audit, Property 9: seed idempotence and
determinism. The generator must emit byte-identical ``historical_ground_truth``
INSERT statements on every render, use deterministic ``det_uuid`` primary keys,
and carry ``ON CONFLICT (ground_truth_id) DO NOTHING`` so re-applying the seed
inserts no duplicate and raises no error. The four seeded metrics must come only
from the audit metric vocabulary.

The generator lives under ``database/seed`` (outside the backend package root),
so it is loaded by file path with ``importlib`` exactly as the other seed
regression tests do. Importing does not regenerate the SQL file (the render-time
write only runs under ``__main__``).

Validates: Requirements 12.2, 12.3; Property 9
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GEN_PATH = _REPO_ROOT / "database" / "seed" / "generate_seed_sql.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_seed_sql", _GEN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = _load_generator()

# Metric names the audit scores (mirrors PREDICTED_METRIC_FIELDS).
_AUDIT_METRICS = {"cpvh", "ltv_to_cost", "churn_reduction", "payback_horizon"}


def _ground_truth_section(sql: str) -> str:
    """Return the historical_ground_truth INSERT ... up to its terminating ';'."""
    start = sql.index("INSERT INTO historical_ground_truth")
    end = sql.index(";", start) + 1
    return sql[start:end]


# Feature: dashboard-accuracy-and-payback-audit, Property 9: regenerating the seed produces byte-identical historical_ground_truth INSERTs
# Validates: Requirements 12.2, 12.3
@settings(max_examples=100)
@given(runs=st.integers(min_value=2, max_value=6))
def test_property_9_ground_truth_render_is_byte_identical(runs):
    outputs = [_ground_truth_section(seed.render()) for _ in range(runs)]
    # Every render of the ground-truth section is byte-identical (deterministic).
    assert all(o == outputs[0] for o in outputs)


def test_ground_truth_rows_are_deterministic_and_idempotent():
    section = _ground_truth_section(seed.render())

    # Idempotent: ON CONFLICT on the deterministic primary key.
    assert "ON CONFLICT (ground_truth_id) DO NOTHING" in section

    # Deterministic PKs: the four ids match det_uuid("title-echoes-gt-<metric>").
    for metric in _AUDIT_METRICS:
        expected_id = str(seed.det_uuid(f"title-echoes-gt-{metric}"))
        assert expected_id in section, f"missing deterministic id for {metric}"

    # Only audit-vocabulary metric names appear, and all four are present.
    found = set(re.findall(r"'(cpvh|ltv_to_cost|churn_reduction|payback_horizon)'", section))
    assert found == _AUDIT_METRICS

    # The FK target is the seeded historical title's deterministic id.
    assert str(seed.det_uuid("title-echoes")) in section