"""Add purge_history: a permanent tombstone table recording every project or
file that gets purged, manually or via the new auto-purge retention sweep.
Deliberately has no foreign keys to projects/source_files, since by the time
a row here matters, those original rows are already gone.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_add_purge_history"
down_revision: Union[str, None] = "0014_entity_created_at_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "purge_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("resource_type", sa.String(16), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("resource_name", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(36)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("purge_reason", sa.String(32), nullable=False),
        sa.Column(
            "purged_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_purge_history_purged_at", "purge_history", ["purged_at"])


def downgrade() -> None:
    op.drop_index("ix_purge_history_purged_at", table_name="purge_history")
    op.drop_table("purge_history")
