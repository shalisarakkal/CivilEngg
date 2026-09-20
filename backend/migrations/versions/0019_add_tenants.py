"""Add tenants and a nullable tenant_id on users/clients/projects.

Schema-only foundation for DECISIONS.md ADR-010's hybrid deployment model: a
dedicated single-customer install gets exactly one Tenant row; a shared
instance serving several subscribing customers gets one Tenant row per
customer. Nothing yet reads or enforces this column on any query -- see
RISK_REGISTER.md and PLAN.md Phase 16 for what's deliberately not done yet
(query scoping, per-tenant username uniqueness, a platform-admin role,
database-enforced Row-Level Security).

tenant_id is added nullable, not backfilled here, following the same pattern
already used for projects.owner_id in migration 0017: no tenant exists yet
at migration time to backfill onto. backend/scripts/create_sysadmin.py
creates the default tenant and backfills every pre-existing row onto it, as
a one-time, documented step run after this migration.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_add_tenants"
down_revision: Union[str, None] = "0018_add_purge_history_purged_by"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TENANT_SCOPED_TABLES = ("users", "clients", "projects")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    for table in _TENANT_SCOPED_TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.String(36), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_tenant_id_tenants",
            table,
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table in _TENANT_SCOPED_TABLES:
        op.drop_constraint(f"fk_{table}_tenant_id_tenants", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")
    op.drop_table("tenants")
