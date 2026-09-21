"""Add activity_events: Phase 12's persisted, project-scoped audit trail.

Closes the gap the session-only activity log (frontend-only, cleared on
reload) explicitly left open -- the user asked for a durable record, not
just an in-browser one. Project-scoped, not tenant-scoped directly: it
carries `project_id`, not its own `tenant_id`, matching the convention
already established for every other table nested under `Project`
(source_files, calculation_results, etc. -- migration
0022_extend_rls_nested_tables). Reads and writes go through the existing
`require_project_member` dependency, the same authorization boundary every
other project-scoped resource already uses, rather than inventing a new
visibility rule.

Row-Level Security is enabled here too, for the same reason and in the same
shape as migration 0022's nested tables: `project_id IN (SELECT id FROM
projects)`, which composes correctly with `projects`' own FORCE ROW LEVEL
SECURITY policy. See that migration's docstring for the full reasoning
(verified against a real Postgres instance).

No retention/auto-purge here, deliberately: an "audit trail" implies
durability by default, unlike `purge_history`'s finite retention window
(Phase 13). If a retention policy is wanted later, it's a separate, opt-in
decision, not a default this migration should impose.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_add_activity_events"
down_revision: Union[str, None] = "0022_extend_rls_nested_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "activity_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("success_label", sa.String(64), nullable=False, server_default="Successful"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_activity_events_project_id", "activity_events", ["project_id"])

    op.execute("ALTER TABLE activity_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE activity_events FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON activity_events
        USING (project_id IN (SELECT id FROM projects))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON activity_events")
    op.execute("ALTER TABLE activity_events NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE activity_events DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_activity_events_project_id", table_name="activity_events")
    op.drop_table("activity_events")
