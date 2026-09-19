"""Add purge_history.purged_by_user_id.

Phase 15's purge-history visibility rule for a power_user (see routes.py's
list_purge_history) needs to know who owned the purged resource, not just
which project it belonged to: once a *project itself* is purged, the
ownership row that would otherwise answer "was this mine" is gone along
with it. Recording the project's owner_id at purge time (not literally who
clicked purge -- an automatic retention sweep isn't a click) answers that
without depending on state that no longer exists. No FK, matching this
table's existing "no FK to anything it must outlive" convention (see its
docstring in models.py).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_add_purge_history_purged_by"
down_revision: Union[str, None] = "0017_add_users_roles_ownership"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("purge_history", sa.Column("purged_by_user_id", sa.String(36), nullable=True))


def downgrade() -> None:
    op.drop_column("purge_history", "purged_by_user_id")
