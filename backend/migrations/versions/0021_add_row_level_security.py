"""Enable Postgres Row-Level Security on projects and clients as a
database-enforced backstop for tenant isolation, for the shared-instance
case specifically (PLAN.md Phase 16, DECISIONS.md ADR-010).

Verified end-to-end against a real local Postgres 18 instance (2026-09-20):
migrations 0019-0021 applied to a pre-existing dev database, FORCE ROW LEVEL
SECURITY confirmed via pg_class, the tenant_isolation policy confirmed via
pg_policies, and actual row isolation proven both directly in psql (tenant A
sees only its own row, tenant B only its own, platform_admin sees both, no
session context fails closed, a cross-tenant UPDATE affects 0 rows) and
through the real FastAPI app over HTTP (login by email, POST /tenants,
tenant-scoped admin creation, cross-tenant client-list isolation). That
verification pass found and fixed two real bugs this migration and its
support code had: this migration's original-constraint lookup compared
`array_agg` of `information_schema.sql_identifier` against a `text[]`
literal with no operator between them (needed an explicit `::text`/`::text[]`
cast), and `_set_rls_session_variables` (database.py) originally used
`SET LOCAL app.x = :value` -- which raises a hard syntax error in Postgres,
since the `SET` command's grammar has no placeholder for a bound parameter
at all -- now fixed to use `set_config(name, :value, true)`, an ordinary
function call that both takes bind parameters and is transaction-scoped
exactly like SET LOCAL. Neither bug was catchable by the SQLite-backed test
suite, since this whole code path is skipped on every non-Postgres dialect
-- which is exactly why this real-Postgres pass mattered.

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
down_revision: Union[str, None] = "0020_add_email_tenant_username"
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
