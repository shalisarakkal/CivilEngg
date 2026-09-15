"""Enforce project/checksum uniqueness at the database level to close a race condition."""

from typing import Sequence, Union

from alembic import op

revision: str = "0009_unique_source_file_checksum"
down_revision: Union[str, None] = "0008_add_ai_outputs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_source_files_checksum", table_name="source_files")
    op.create_unique_constraint(
        "uq_source_files_project_checksum", "source_files", ["project_id", "checksum"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_source_files_project_checksum", "source_files", type_="unique")
    op.create_index("ix_source_files_checksum", "source_files", ["checksum"])
