"""Fix site_model_entities.created_at: it was added in 0012 without an
actual database-level DEFAULT, only the ORM model's server_default
metadata. Since the ORM omits the column from INSERT statements expecting
the database to fill it in, every new entity created since 0012 landed
would fail with a NOT NULL violation. Found by testing a plain insert
directly, before this was ever hit by a real user action.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_entity_created_at_default"
down_revision: Union[str, None] = "0013_entity_revision_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "site_model_entities",
        "created_at",
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.alter_column("site_model_entities", "created_at", server_default=None)
