"""titles.deal_stage: human acquisition pipeline stage (deal-stage lifecycle).

Adds a ``deal_stage`` column to ``titles`` recording where a title sits in the
buyer-managed acquisition pipeline, orthogonal to the AI ``recommendation_status``.
The column is NOT NULL with a server default of ``SCREENING`` so existing rows
backfill to the initial stage, and a CHECK constraint pins it to the enumerated
set the domain state machine (``app.domain.deal_stage.DealStage``) recognizes.

Revision ID: 0004_deal_stage
Revises: 0003_subscriber_clusters
Create Date: 2024-01-01 00:00:03.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_deal_stage"
down_revision: Union[str, None] = "0003_subscriber_clusters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEAL_STAGES = (
    "SCREENING",
    "EVALUATED",
    "IN_NEGOTIATION",
    "APPROVED",
    "CLOSED_WON",
    "CLOSED_LOST",
    "PASSED",
)


def upgrade() -> None:
    op.add_column(
        "titles",
        sa.Column(
            "deal_stage",
            sa.Text(),
            nullable=False,
            server_default="SCREENING",
        ),
    )
    allowed = ", ".join(f"'{stage}'" for stage in _DEAL_STAGES)
    op.create_check_constraint(
        "ck_titles_deal_stage",
        "titles",
        f"deal_stage IN ({allowed})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_titles_deal_stage", "titles", type_="check")
    op.drop_column("titles", "deal_stage")