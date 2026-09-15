"""Add source-grounded summaries and questions."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_add_ai_outputs"
down_revision: Union[str, None] = "0007_add_calculation_details"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table, columns in {
        "project_summaries": [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("revision_id", sa.String(36)),
            sa.Column("content", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["revision_id"], ["project_revisions.id"], ondelete="SET NULL"),
        ],
        "question_answers": [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("revision_id", sa.String(36)),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("intent", sa.String(32), nullable=False),
            sa.Column("answer", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["revision_id"], ["project_revisions.id"], ondelete="SET NULL"),
        ],
    }.items():
        op.create_table(table, *columns)


def downgrade() -> None:
    op.drop_table("question_answers")
    op.drop_table("project_summaries")
