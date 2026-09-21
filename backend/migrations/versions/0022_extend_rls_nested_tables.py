"""Extend Postgres Row-Level Security to every table nested under Project,
closing the scope gap migration 0021 explicitly deferred (PLAN.md Phase 16,
DECISIONS.md ADR-010, RISK_REGISTER.md).

None of these tables carry their own `tenant_id` column -- they reach a
tenant only by following a foreign key up to `projects` (directly, or via
one more hop). Rather than duplicating projects' three-branch
platform_admin/tenant-match/tenant-IS-NULL policy on every one of them, each
policy here is just:

    <fk column> IN (SELECT id FROM <parent table>)

This is not an unfiltered subquery. `projects` (and, transitively,
`processing_jobs`/`project_revisions` for the two-hop tables below) already
has `FORCE ROW LEVEL SECURITY` plus its own `tenant_isolation` policy from
migration 0021/this migration. FORCE ROW LEVEL SECURITY means that policy
still applies to this app's own database role even when it's the table
owner -- including when that role's query is a subquery nested inside
another table's policy evaluation, not just a top-level SELECT. So each
`SELECT id FROM <parent table>` here is already scoped to exactly the
projects (or processing_jobs/project_revisions) the current session's
tenant context can see, and this composes correctly through two levels of
nesting. Verified directly (2026-09-20, real Postgres 18, ad hoc before
writing this migration): a `source_files` row under tenant A's project was
visible only to a session with tenant A's context set, tenant B's session
saw only its own, with no explicit tenant/platform_admin logic duplicated
on `source_files` itself.

Unlike `projects.tenant_id`/`clients.tenant_id`, every foreign key used
below (`project_id`, `processing_job_id`, `revision_id`) is `NOT NULL` on
these tables -- there is no pre-migration "tenant-less row" case to handle
here the way migration 0021 had to for `projects`/`clients` themselves.

Tables covered, and how each reaches `projects`:
  - `source_files`, `processing_jobs`, `project_revisions`,
    `calculation_results`, `project_summaries`, `question_answers`,
    `project_memberships`: directly, via their own `project_id`.
  - `extracted_documents`: via `processing_job_id` -> `processing_jobs`
    (itself covered above).
  - `site_model_entities`: via `revision_id` -> `project_revisions`
    (itself covered above).

Deliberately still NOT covered, same reasoning as migration 0021:
  - `users`, `sessions`: no `Project` relationship at all; `users` also has
    the bootstrapping paradox described in migration 0021's docstring.
  - `purge_history`: designed with no foreign key to `projects`/
    `source_files` at all (see `PurgeHistoryEntry`'s own docstring in
    models.py) -- it must outlive the rows it records the purge of, so
    there is nothing to join through, tenant-scoped or otherwise. It also
    carries no `tenant_id` of its own to filter on directly.

With this migration, RLS now covers every table that carries or reaches a
tenant boundary. The application's own query-scoping (PLAN.md Phase 16's
earlier slice) remains the primary enforcement; this is strictly a second,
database-level backstop behind it, per the original multi-tenant study's
recommendation.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0022_extend_rls_nested_tables"
down_revision: Union[str, None] = "0021_add_row_level_security"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, its foreign key column, the parent table that column points to)
_POLICIES = (
    ("source_files", "project_id", "projects"),
    ("processing_jobs", "project_id", "projects"),
    ("project_revisions", "project_id", "projects"),
    ("calculation_results", "project_id", "projects"),
    ("project_summaries", "project_id", "projects"),
    ("question_answers", "project_id", "projects"),
    ("project_memberships", "project_id", "projects"),
    ("extracted_documents", "processing_job_id", "processing_jobs"),
    ("site_model_entities", "revision_id", "project_revisions"),
)


def upgrade() -> None:
    for table, fk_column, parent_table in _POLICIES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING ({fk_column} IN (SELECT id FROM {parent_table}))
            """
        )


def downgrade() -> None:
    for table, _fk_column, _parent_table in reversed(_POLICIES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
