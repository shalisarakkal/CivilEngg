"""Add users.email (globally unique login identifier) and move
users.username uniqueness from global to per-tenant.

PLAN.md Phase 16 / DECISIONS.md ADR-010: username alone can no longer be
globally unique once a shared instance has more than one tenant -- two
different customers could each reasonably want a user named "jsmith". But
login (POST /auth/login) has no other way to know which tenant's "jsmith"
is meant, so it switches to email instead, which stays globally unique and
is never ambiguous.

email is added nullable: existing rows predate this column and have no
email to backfill onto (the same nullable-then-app-enforced pattern already
used for projects.owner_id and every tenant_id column). New users are
required to supply one at the schema layer (UserCreate.email), not here.

The original single-column uniqueness on username was created inline
(`unique=True`) in migration 0017, so Postgres auto-named its constraint
rather than this codebase choosing a name -- looked up here via
information_schema instead of hardcoding a guess at that generated name.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_add_user_email_tenant_scoped_username"
down_revision: Union[str, None] = "0019_add_tenants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ORIGINAL_USERNAME_CONSTRAINT_LOOKUP = """
    SELECT tc.constraint_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON tc.constraint_name = kcu.constraint_name
     AND tc.table_schema = kcu.table_schema
    WHERE tc.table_name = 'users'
      AND tc.constraint_type = 'UNIQUE'
      AND tc.table_schema = 'public'
    GROUP BY tc.constraint_name
    HAVING array_agg(kcu.column_name) = ARRAY['username']
"""


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(255), nullable=True))
    op.create_unique_constraint("uq_users_email", "users", ["email"])

    bind = op.get_bind()
    original_constraint = bind.execute(sa.text(_ORIGINAL_USERNAME_CONSTRAINT_LOOKUP)).scalar()
    if original_constraint:
        op.drop_constraint(original_constraint, "users", type_="unique")

    op.create_unique_constraint("uq_users_tenant_username", "users", ["tenant_id", "username"])


def downgrade() -> None:
    op.drop_constraint("uq_users_tenant_username", "users", type_="unique")
    op.create_unique_constraint("users_username_key", "users", ["username"])
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_column("users", "email")
