"""Expanded tables for the expanded requirements.

Adds users, sessions, model_versions, title_versions, exchange_rates, jobs,
license_terms, approval_workflows, approval_actions, and audit_log, then wires
the foreign keys that were deferred in migration 0001 (titles.created_by ->
users, titles.active_version_id -> title_versions, metadata_vectors
title_version_id/model_version_id, financial_projections title_version_id/
exchange_rate_id/model_version_id). Enforces:

- model_versions partial unique index (exactly one active) + weights-sum CHECK
  (R12.2, R26.1).
- title_versions (title_id, version_number) UNIQUE + one-active-per-title
  partial unique index (R24.2, R24.4).
- jobs.idempotency_key UNIQUE (R27.1).
- exchange_rates (from_currency, to_currency, rate_date) UNIQUE (R21.4).
- financial_projections.model_version_id NOT NULL (R25.3, R26.2).
- audit_log append-only: REVOKE UPDATE/DELETE + a mutation-blocking trigger
  (R25.2).

Note: row_version optimistic-lock columns on titles and financial_projections
were already created in migration 0001; this migration only verifies/relies on
them (R27.2).

Revision ID: 0002_expanded_tables
Revises: 0001_core_tables
Create Date: 2024-01-01 00:00:01.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_expanded_tables"
down_revision: Union[str, None] = "0001_core_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users (R20.1, R19) ---
    op.create_table(
        "users",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("external_subject", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("user_role", sa.Text(), nullable=False),
        sa.Column(
            "authorized_territories",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("external_subject", name="uq_users_external_subject"),
        sa.CheckConstraint(
            "user_role IN ('DATA_ANALYST', 'CONTENT_BUYER', "
            "'CHIEF_CONTENT_OFFICER', 'CFO')",
            name="ck_users_user_role",
        ),
    )

    # --- sessions (R19.2, R19.4) ---
    op.create_table(
        "sessions",
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.PrimaryKeyConstraint("session_id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.user_id"], ondelete="CASCADE"
        ),
    )

    # --- model_versions (R26, R12.2) ---
    op.create_table(
        "model_versions",
        sa.Column(
            "model_version_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("talent_pedigree_weight", sa.Numeric(4, 2), nullable=False),
        sa.Column("narrative_trope_weight", sa.Numeric(4, 2), nullable=False),
        sa.Column("guardrail_params", postgresql.JSONB(), nullable=False),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("model_version_id"),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["model_versions.model_version_id"]
        ),
        sa.CheckConstraint(
            "talent_pedigree_weight BETWEEN 0.00 AND 1.00",
            name="ck_model_versions_talent_pedigree_weight_range",
        ),
        sa.CheckConstraint(
            "narrative_trope_weight BETWEEN 0.00 AND 1.00",
            name="ck_model_versions_narrative_trope_weight_range",
        ),
        sa.CheckConstraint(
            "talent_pedigree_weight + narrative_trope_weight = 1.00",
            name="ck_model_versions_weights_sum",
        ),
    )
    # Exactly one active model version (R26.1).
    op.create_index(
        "uq_model_versions_one_active",
        "model_versions",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    # --- title_versions (R24) ---
    op.create_table(
        "title_versions",
        sa.Column(
            "title_version_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("title_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        # Encrypted at rest (R28.1): stored as ciphertext TEXT, not JSONB,
        # because Fernet ciphertext is opaque to the database.
        sa.Column("source_snapshot", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("title_version_id"),
        sa.ForeignKeyConstraint(
            ["title_id"], ["titles.title_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "title_id", "version_number", name="uq_title_versions_title_version"
        ),
    )
    # Exactly one active version per title (R24.4).
    op.create_index(
        "uq_title_versions_one_active_per_title",
        "title_versions",
        ["title_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    # --- exchange_rates (R21.4) ---
    op.create_table(
        "exchange_rates",
        sa.Column(
            "exchange_rate_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("from_currency", sa.String(length=3), nullable=False),
        sa.Column("to_currency", sa.String(length=3), nullable=False),
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("exchange_rate_id"),
        sa.UniqueConstraint(
            "from_currency",
            "to_currency",
            "rate_date",
            name="uq_exchange_rates_from_to_date",
        ),
    )

    # --- jobs (R23.2-R23.5, R27.1, R29.3) ---
    op.create_table(
        "jobs",
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "dead_lettered",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("job_id"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.user_id"]),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="ck_jobs_status",
        ),
    )

    # --- license_terms (R22) ---
    op.create_table(
        "license_terms",
        sa.Column(
            "license_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("title_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("license_duration_months", sa.Integer(), nullable=False),
        sa.Column("is_exclusive", sa.Boolean(), nullable=False),
        # Confidential deal terms encrypted at rest (R28.1): ciphertext TEXT,
        # not JSONB (ciphertext is opaque to the database).
        sa.Column("windowing_rules", sa.Text(), nullable=False),
        sa.Column("holdbacks", sa.Text(), nullable=True),
        sa.Column("milestone_schedule", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("license_id"),
        sa.ForeignKeyConstraint(
            ["title_id"], ["titles.title_id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "license_duration_months > 0",
            name="ck_license_terms_duration_positive",
        ),
    )

    # --- approval_workflows (R20.3, R20.5) ---
    op.create_table(
        "approval_workflows",
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("required_roles", postgresql.JSONB(), nullable=False),
        sa.Column(
            "finalized",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("workflow_id"),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["financial_projections.projection_id"],
            ondelete="CASCADE",
        ),
    )

    # --- approval_actions (R20.4) ---
    op.create_table(
        "approval_actions",
        sa.Column(
            "action_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column(
            "acted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("action_id"),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["approval_workflows.workflow_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.user_id"]),
        sa.CheckConstraint(
            "action IN ('APPROVE', 'REJECT', 'OVERRIDE')",
            name="ck_approval_actions_action",
        ),
    )

    # --- audit_log (R25.1, R25.2) ---
    op.create_table(
        "audit_log",
        sa.Column(
            "audit_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("before_value", postgresql.JSONB(), nullable=True),
        sa.Column("after_value", postgresql.JSONB(), nullable=True),
        sa.Column("model_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("audit_id"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(
            ["model_version_id"], ["model_versions.model_version_id"]
        ),
    )

    # --- Wire deferred FKs from the core tables (migration 0001 left these
    #     columns FK-less until the target tables existed). ---
    op.create_foreign_key(
        "fk_titles_created_by", "titles", "users", ["created_by"], ["user_id"]
    )
    op.create_foreign_key(
        "fk_titles_active_version_id",
        "titles",
        "title_versions",
        ["active_version_id"],
        ["title_version_id"],
    )
    op.create_foreign_key(
        "fk_metadata_vectors_title_version_id",
        "metadata_vectors",
        "title_versions",
        ["title_version_id"],
        ["title_version_id"],
    )
    op.create_foreign_key(
        "fk_metadata_vectors_model_version_id",
        "metadata_vectors",
        "model_versions",
        ["model_version_id"],
        ["model_version_id"],
    )
    op.create_foreign_key(
        "fk_financial_projections_title_version_id",
        "financial_projections",
        "title_versions",
        ["title_version_id"],
        ["title_version_id"],
    )
    op.create_foreign_key(
        "fk_financial_projections_exchange_rate_id",
        "financial_projections",
        "exchange_rates",
        ["exchange_rate_id"],
        ["exchange_rate_id"],
    )
    # model_version_id must be NOT NULL per design (R25.3, R26.2) before its FK.
    op.alter_column(
        "financial_projections",
        "model_version_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_financial_projections_model_version_id",
        "financial_projections",
        "model_versions",
        ["model_version_id"],
        ["model_version_id"],
    )

    # --- audit_log append-only enforcement (R25.2) ---
    # Block row mutation at the engine level with a trigger, and revoke the
    # UPDATE/DELETE privileges so no role can mutate historical entries.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION cineroi_block_audit_log_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % is not permitted',
                TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_log_append_only
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION cineroi_block_audit_log_mutation();
        """
    )
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC")


def downgrade() -> None:
    # Remove append-only enforcement first.
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_append_only ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS cineroi_block_audit_log_mutation()")

    # Drop the deferred FKs wired onto the core tables.
    op.drop_constraint(
        "fk_financial_projections_model_version_id",
        "financial_projections",
        type_="foreignkey",
    )
    op.alter_column(
        "financial_projections",
        "model_version_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.drop_constraint(
        "fk_financial_projections_exchange_rate_id",
        "financial_projections",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_financial_projections_title_version_id",
        "financial_projections",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_metadata_vectors_model_version_id",
        "metadata_vectors",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_metadata_vectors_title_version_id",
        "metadata_vectors",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_titles_active_version_id", "titles", type_="foreignkey"
    )
    op.drop_constraint("fk_titles_created_by", "titles", type_="foreignkey")

    # Drop expanded tables in reverse dependency order.
    op.drop_table("audit_log")
    op.drop_table("approval_actions")
    op.drop_table("approval_workflows")
    op.drop_table("license_terms")
    op.drop_table("jobs")
    op.drop_table("exchange_rates")
    op.drop_index(
        "uq_title_versions_one_active_per_title", table_name="title_versions"
    )
    op.drop_table("title_versions")
    op.drop_index("uq_model_versions_one_active", table_name="model_versions")
    op.drop_table("model_versions")
    op.drop_table("sessions")
    op.drop_table("users")
