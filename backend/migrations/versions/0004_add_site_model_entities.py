"""Add site-model entities to project revisions."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_site_model_entities"
down_revision: Union[str, None] = "0003_add_extracted_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "site_model_entities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("geometry", sa.JSON(), nullable=True),
        sa.Column("properties", sa.JSON(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("elevation", sa.Float(), nullable=True),
        sa.Column("source_reference", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["revision_id"], ["project_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("site_model_entities")
