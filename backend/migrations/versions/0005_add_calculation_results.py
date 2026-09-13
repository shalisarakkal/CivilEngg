"""Add deterministic calculation results."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_add_calculation_results"
down_revision: Union[str, None] = "0004_add_site_model_entities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calculation_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=True),
        sa.Column("calculation_type", sa.String(length=32), nullable=False),
        sa.Column("input_entity_ids", sa.JSON(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.Column("result", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["project_revisions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("calculation_results")
