"""Add created_at to site_model_entities, the one table that lacked any timestamp.

Backfilled from the parent revision's created_at, since every entity in a
revision is created together at accept time.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_entity_created_at"
down_revision: Union[str, None] = "0011_file_versioning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("site_model_entities", sa.Column("created_at", sa.DateTime(timezone=True)))
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE site_model_entities SET created_at = project_revisions.created_at "
            "FROM project_revisions "
            "WHERE project_revisions.id = site_model_entities.revision_id"
        )
    )
    op.alter_column("site_model_entities", "created_at", nullable=False)


def downgrade() -> None:
    op.drop_column("site_model_entities", "created_at")
