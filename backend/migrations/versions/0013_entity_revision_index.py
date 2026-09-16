"""Index site_model_entities.revision_id.

Found while investigating a slow project purge: this foreign key column had
no index at all, so every lookup by revision_id (including the cascade
delete when a revision or project is removed) required a full table scan
of site_model_entities, the largest table in the schema.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0013_entity_revision_index"
down_revision: Union[str, None] = "0012_entity_created_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_site_model_entities_revision_id",
        "site_model_entities",
        ["revision_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_site_model_entities_revision_id", table_name="site_model_entities")
