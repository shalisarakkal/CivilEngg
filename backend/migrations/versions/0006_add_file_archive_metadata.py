"""Add soft-delete metadata to source files."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_add_file_archive_metadata"
down_revision: Union[str, None] = "0005_add_calculation_results"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("source_files", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("source_files", sa.Column("archived_path", sa.String(length=1000)))
    op.add_column("source_files", sa.Column("status_before_delete", sa.String(length=32)))


def downgrade() -> None:
    op.drop_column("source_files", "status_before_delete")
    op.drop_column("source_files", "archived_path")
    op.drop_column("source_files", "deleted_at")
