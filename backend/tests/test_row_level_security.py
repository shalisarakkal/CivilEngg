"""Unit coverage for the Postgres Row-Level Security session-variable logic
(migration 0021_add_row_level_security, PLAN.md Phase 16). This tests the
pure decision logic in isolation -- what SQL and values get sent, given a
tenant context -- using a fake connection object rather than a real
database. It does NOT verify that Postgres actually accepts and enforces
the resulting policies; that needs a real Postgres instance, which this
environment doesn't have (see the migration's own docstring). The rest of
this suite (test_auth.py, test_tenant_isolation.py) already confirms the
SQLite no-op path is silently correct: all of it runs against SQLite and
none of it ever attempts to execute this Postgres-only SQL.
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
    assert "SET LOCAL app.current_tenant_id" in tenant_sql
    assert tenant_params == {"value": "tenant-123"}
    assert "SET LOCAL app.is_platform_admin" in admin_sql
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
