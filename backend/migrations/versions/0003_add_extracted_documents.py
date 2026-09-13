"""Add versioned normalized extraction output."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_add_extracted_documents"
down_revision: Union[str, None] = "0002_add_project_entities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "extracted_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("processing_job_id", sa.String(length=36), nullable=False),
        sa.Column("source_file_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("parser_name", sa.String(length=100), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["processing_job_id"], ["processing_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("processing_job_id"),
    )


def downgrade() -> None:
    op.drop_table("extracted_documents")
