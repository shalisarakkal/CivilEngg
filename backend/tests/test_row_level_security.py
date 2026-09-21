"""Unit coverage for the Postgres Row-Level Security session-variable logic
(migration 0021_add_row_level_security, PLAN.md Phase 16). This tests the
pure decision logic in isolation -- what SQL and values get sent, given a
tenant context -- using a fake connection object rather than a real
database. The rest of this suite (test_auth.py, test_tenant_isolation.py)
already confirms the SQLite no-op path is silently correct: all of it runs
against SQLite and none of it ever attempts to execute this Postgres-only
SQL.

The actual Postgres enforcement (RLS policies, FORCE ROW LEVEL SECURITY,
and this module's set_config() calls) has been verified end-to-end against
a real local Postgres 18 instance (2026-09-20) -- see PLAN.md Phase 16 and
RISK_REGISTER.md. That exercise is exactly why this function calls
set_config() rather than `SET LOCAL app.x = :value`: the latter looked
correct and passed every test here, but Postgres's SET command syntax has
no placeholder for a bound parameter at all, and raises a syntax error the
first time it actually runs -- something no SQLite-backed unit test can
catch, since this whole function is skipped on every non-Postgres dialect.
"""

from typing import Any

from civil_engineering.database import _set_rls_session_variables


class _RecordingConnection:
    """Stands in for a SQLAlchemy Connection, capturing every execute() call
    instead of running it against a real database."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, statement: Any, parameters: dict[str, Any] | None = None) -> None:
        self.calls.append((str(statement), parameters or {}))


def test_sets_the_tenant_id_and_platform_admin_flag_from_session_info() -> None:
    connection = _RecordingConnection()
    _set_rls_session_variables(
        connection, {"rls_tenant_id": "tenant-123", "rls_is_platform_admin": False}
    )
    assert len(connection.calls) == 2
    tenant_sql, tenant_params = connection.calls[0]
    admin_sql, admin_params = connection.calls[1]
    assert "set_config('app.current_tenant_id'" in tenant_sql
    assert tenant_params == {"value": "tenant-123"}
    assert "set_config('app.is_platform_admin'" in admin_sql
    assert admin_params == {"value": "false"}


def test_uses_an_empty_string_sentinel_for_a_tenant_less_user() -> None:
    # None can't be sent as a Postgres session-variable value directly --
    # current_setting() always returns text. Empty string is the sentinel
    # the tenant_isolation policy's "tenant_id IS NULL" branch matches.
    connection = _RecordingConnection()
    _set_rls_session_variables(connection, {"rls_tenant_id": None, "rls_is_platform_admin": True})
    assert connection.calls[0][1] == {"value": ""}
    assert connection.calls[1][1] == {"value": "true"}


def test_platform_admin_flag_defaults_to_false_when_absent() -> None:
    connection = _RecordingConnection()
    _set_rls_session_variables(connection, {"rls_tenant_id": "tenant-123"})
    assert connection.calls[1][1] == {"value": "false"}
