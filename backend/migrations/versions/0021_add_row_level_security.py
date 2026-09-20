"""Enable Postgres Row-Level Security on projects and clients as a
database-enforced backstop for tenant isolation, for the shared-instance
case specifically (PLAN.md Phase 16, DECISIONS.md ADR-010).

UNVERIFIED against a real Postgres instance -- this environment has no live
Postgres to test the migration chain against (confirmed: even migration
0001's `CREATE EXTENSION postgis` can't run outside Postgres, so this whole
chain has never been runnable here). Written by careful reasoning about
Postgres's RLS semantics, not confirmed by actually running it. Verify
before relying on it in a real shared-instance deployment.

Scope: `projects` and `clients` only -- the two tables that actually carry
`tenant_id`. Deliberately NOT `users`: the very first thing
auth.get_current_user does is look up which user a session belongs to,
before the tenant context is known at all (the user IS how the tenant
context gets determined) -- RLS on `users` would face a bootstrapping
problem the existing app-layer scoping (Phase 16's query-scoping slice)
doesn't have. Also deliberately NOT every table nested under Project
(source_files, processing_jobs, project_revisions, site_model_entities,
calculation_results, project_summaries, question_answers,
project_memberships) -- true defense-in-depth would extend RLS to each of
those too, via a policy checking `project_id IN (SELECT id FROM projects
WHERE ...)`, but that's a larger follow-up not attempted here. A missed
application-layer check on one of those tables is not yet caught by this
backstop.

FORCE ROW LEVEL SECURITY (not just ENABLE) is required: Postgres exempts a
table's own owner from RLS policies by default, and this app's database
role is normally that owner (it's the role that ran every migration).
Without FORCE, this whole migration would silently do nothing for the
app's own connections.

The app must SET the `app.current_tenant_id`/`app.is_platform_admin`
session variables these policies read -- see auth.py's get_current_user
and database.py's Session "after_begin" listener. Without the app setting
them, `current_setting(..., true)` returns NULL and every row is hidden
from everyone (fails closed, not open).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0021_add_row_level_security"
down_revision: Union[str, None] = "0020_add_user_email_tenant_scoped_username"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("projects", "clients")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                current_setting('app.is_platform_admin', true) = 'true'
                OR (
                    tenant_id IS NULL
                    AND current_setting('app.current_tenant_id', true) = ''
                )
                OR tenant_id = current_setting('app.current_tenant_id', true)
            )
            """
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
