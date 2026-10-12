"""Integration tests for CineROI AI.

These tests exercise the system against real external infrastructure
(PostgreSQL 16 + pgvector). They are marked ``@pytest.mark.integration`` and
skip cleanly when neither Docker (via testcontainers) nor an externally
provided database is reachable.
"""
