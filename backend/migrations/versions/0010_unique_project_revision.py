"""Enforce project/revision-number uniqueness at the database level to close a race condition.

Concurrent "accept revision" requests for different files in the same project could
both read the same current max(revision_number) before either committed, producing
two revisions with the same number. This migration renumbers any existing duplicates
(sequentially by creation order, per project) before adding the constraint that
prevents new ones.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_unique_project_revision"
down_revision: Union[str, None] = "0009_unique_source_file_checksum"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, project_id FROM project_revisions ORDER BY project_id, created_at, id"
        )
    ).fetchall()
    next_number: dict[str, int] = {}
    for row in rows:
        number = next_number.get(row.project_id, 0) + 1
        next_number[row.project_id] = number
        bind.execute(
            sa.text("UPDATE project_revisions SET revision_number = :number WHERE id = :id"),
            {"number": number, "id": row.id},
        )
    op.create_unique_constraint(
        "uq_project_revisions_project_number",
        "project_revisions",
        ["project_id", "revision_number"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_project_revisions_project_number", "project_revisions", type_="unique")
