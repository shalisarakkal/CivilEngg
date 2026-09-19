"""Add users, sessions, project_memberships, and projects.owner_id.

The application had no user/auth concept at all until now (ADR-005 deferred
it for the MVP). This adds the schema for Phase 15's role model (admin /
power_user / user), server-side sessions, project ownership, and
project-level collaborator membership.

projects.owner_id is added nullable, not backfilled here: no user exists yet
at migration time to backfill onto. backend/scripts/create_sysadmin.py
creates the first admin account and backfills any pre-existing project with
no owner onto it, as a one-time, documented step run after this migration.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_add_users_roles_ownership"
down_revision: Union[str, None] = "0016_unique_extraction_revision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "project_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_unique_constraint(
        "uq_project_memberships_project_user", "project_memberships", ["project_id", "user_id"]
    )

    op.add_column("projects", sa.Column("owner_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_projects_owner_id_users", "projects", "users", ["owner_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_projects_owner_id_users", "projects", type_="foreignkey")
    op.drop_column("projects", "owner_id")
    op.drop_constraint("uq_project_memberships_project_user", "project_memberships", type_="unique")
    op.drop_table("project_memberships")
    op.drop_table("sessions")
    op.drop_table("users")
