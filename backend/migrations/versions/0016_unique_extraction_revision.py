"""Enforce source-file/revision-number uniqueness on extracted_documents.

revision_number on extracted_documents was previously never incremented (it
always defaulted to 1), making "latest extraction for this file" non-
deterministic once a file was reprocessed: two rows would tie on
revision_number, and which one a query returned depended on unspecified
database order rather than recency. This closes the same class of race
condition already fixed for project_revisions in 0010_unique_project_revision,
renumbering existing rows sequentially per source_file_id (by creation order)
before adding the constraint that keeps new ones correct.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_unique_extraction_revision"
down_revision: Union[str, None] = "0015_add_purge_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, source_file_id FROM extracted_documents "
            "ORDER BY source_file_id, created_at, id"
        )
    ).fetchall()
    next_number: dict[str, int] = {}
    for row in rows:
        number = next_number.get(row.source_file_id, 0) + 1
        next_number[row.source_file_id] = number
        bind.execute(
            sa.text("UPDATE extracted_documents SET revision_number = :number WHERE id = :id"),
            {"number": number, "id": row.id},
        )
    op.create_unique_constraint(
        "uq_extracted_documents_file_number",
        "extracted_documents",
        ["source_file_id", "revision_number"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_extracted_documents_file_number", "extracted_documents", type_="unique")
