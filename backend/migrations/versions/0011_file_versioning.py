"""Add explicit file versioning and multi-revision Q&A/summary scope.

Introduces document_group_id/superseded_by_id on source_files so an explicit
"replace file" upload can be recognized as a new version of an existing file
rather than an unrelated one. Also widens project_summaries/question_answers
from a single revision_id to a revision_ids list, so a question or summary can
draw on more than one revision (e.g. one per document) instead of exactly one.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_file_versioning"
down_revision: Union[str, None] = "0010_unique_project_revision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("source_files", sa.Column("document_group_id", sa.String(36)))
    op.add_column("source_files", sa.Column("superseded_by_id", sa.String(36)))
    op.create_foreign_key(
        "fk_source_files_superseded_by_id",
        "source_files",
        "source_files",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE source_files SET document_group_id = id WHERE document_group_id IS NULL"))
    op.alter_column("source_files", "document_group_id", nullable=False)

    for table in ("project_summaries", "question_answers"):
        op.add_column(table, sa.Column("revision_ids", sa.JSON()))
        bind.execute(
            sa.text(
                f"UPDATE {table} SET revision_ids = json_build_array(revision_id) "
                "WHERE revision_id IS NOT NULL"
            )
        )
        op.drop_constraint(f"{table}_revision_id_fkey", table, type_="foreignkey")
        op.drop_column(table, "revision_id")


def downgrade() -> None:
    for table in ("project_summaries", "question_answers"):
        op.add_column(table, sa.Column("revision_id", sa.String(36)))
        op.create_foreign_key(
            f"{table}_revision_id_fkey",
            table,
            "project_revisions",
            ["revision_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.drop_column(table, "revision_ids")

    op.drop_constraint("fk_source_files_superseded_by_id", "source_files", type_="foreignkey")
    op.drop_column("source_files", "superseded_by_id")
    op.drop_column("source_files", "document_group_id")
