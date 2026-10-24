"""Advanced_Content_Eval_Drivers: neutral driver-fact columns on ``titles``.

Adds the nine ``titles`` columns the four advanced content-evaluation drivers
read (Comps lineage parents, franchise lineage, production-stage momentum, and
the macro market modifiers), each with an EXPLICIT NEUTRAL server-side default so
every existing row backfills to an inert value. With the four ``enable_*`` kill
switches off and these columns at their neutral defaults the engine produces
byte-identical valuations and explanations, so the migration is fully backward
compatible (R8.1-R8.4).

Columns added (all on ``titles``):

- ``is_franchise`` (bool, default ``false``) -- lineage franchise flag (Driver B).
- ``franchise_order`` (int, default ``1``) -- franchise entry ordinal (Driver B).
- ``parent_title_viewing_hours`` (Numeric(16,2), NULL) -- parent-title hours (B).
- ``parent_completion_rate`` (Numeric(3,2), NULL) -- parent completion rate (B).
- ``production_stage`` (text, default ``CONCEPT_SCRIPT``) -- production-readiness
  lifecycle for momentum gating (Driver C), a SEPARATE enum from ``deal_stage``;
  pinned by a CHECK over the four production stages the domain state machine
  (``app.domain.momentum.Production_Stage``) recognizes.
- ``source_ip_provenance`` (text, default ``ORIGINAL_SCREENPLAY``) -- neutral IP
  provenance descriptor (Driver D, multiplier 1.00).
- ``release_window`` (text, default ``DIRECT_TO_STREAMING``) -- neutral release
  window descriptor (Driver D, halo 1.00).
- ``release_month`` (int, explicit ``NULL`` neutral sentinel -> calendar 1.00) (D).
- ``vernacular_track_count`` (int, default ``1``) -- neutral vernacular reach (D).

``downgrade`` drops the production-stage CHECK first, then the nine columns in
reverse order of addition.

Revision ID: 0005_advanced_content_eval_drivers
Revises: 0004_deal_stage
Create Date: 2024-01-01 00:00:04.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_advanced_content_eval_drivers"
down_revision: str | None = "0004_deal_stage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Production-readiness lifecycle stages (Driver C), distinct from ``deal_stage``.
#: Mirrors ``app.domain.momentum.Production_Stage``.
_PRODUCTION_STAGES = (
    "CONCEPT_SCRIPT",
    "IN_PRODUCTION",
    "FESTIVAL_PREVIEW",
    "ACQUISITION_READY",
)


def upgrade() -> None:
    # --- Driver B: lineage / franchise facts ---
    op.add_column(
        "titles",
        sa.Column(
            "is_franchise",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "titles",
        sa.Column(
            "franchise_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "titles",
        sa.Column(
            "parent_title_viewing_hours",
            sa.Numeric(16, 2),
            nullable=True,
            server_default=sa.text("NULL"),
        ),
    )
    op.add_column(
        "titles",
        sa.Column(
            "parent_completion_rate",
            sa.Numeric(3, 2),
            nullable=True,
            server_default=sa.text("NULL"),
        ),
    )

    # --- Driver C: production-stage momentum gating ---
    op.add_column(
        "titles",
        sa.Column(
            "production_stage",
            sa.Text(),
            nullable=False,
            server_default="CONCEPT_SCRIPT",
        ),
    )
    allowed = ", ".join(f"'{stage}'" for stage in _PRODUCTION_STAGES)
    op.create_check_constraint(
        "ck_titles_production_stage",
        "titles",
        f"production_stage IN ({allowed})",
    )

    # --- Driver D: macro market modifiers ---
    op.add_column(
        "titles",
        sa.Column(
            "source_ip_provenance",
            sa.Text(),
            nullable=False,
            server_default="ORIGINAL_SCREENPLAY",
        ),
    )
    op.add_column(
        "titles",
        sa.Column(
            "release_window",
            sa.Text(),
            nullable=False,
            server_default="DIRECT_TO_STREAMING",
        ),
    )
    op.add_column(
        "titles",
        sa.Column(
            "release_month",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("NULL"),
        ),
    )
    op.add_column(
        "titles",
        sa.Column(
            "vernacular_track_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )


def downgrade() -> None:
    op.drop_constraint("ck_titles_production_stage", "titles", type_="check")
    op.drop_column("titles", "vernacular_track_count")
    op.drop_column("titles", "release_month")
    op.drop_column("titles", "release_window")
    op.drop_column("titles", "source_ip_provenance")
    op.drop_column("titles", "production_stage")
    op.drop_column("titles", "parent_completion_rate")
    op.drop_column("titles", "parent_title_viewing_hours")
    op.drop_column("titles", "franchise_order")
    op.drop_column("titles", "is_franchise")
