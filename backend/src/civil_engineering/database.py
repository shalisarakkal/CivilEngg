from collections.abc import Generator
from typing import Any, Protocol

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Session, SessionTransaction, sessionmaker

from civil_engineering.config import get_settings


class _ExecutesSql(Protocol):
    """Structural type for _set_rls_session_variables's `connection` param --
    a real Connection satisfies this naturally; test doubles need only this
    one method, not the rest of Connection's much larger surface."""

    def execute(self, statement: Any, parameters: dict[str, Any] | None = None) -> Any: ...


class Base(DeclarativeBase):
    pass


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
    # SQLite doesn't enforce foreign keys (including ON DELETE CASCADE) unless
    # told to per-connection. The application always runs on PostgreSQL, which
    # enforces them natively, but the automated test suite runs on SQLite, so
    # without this a cascading delete silently leaves orphaned rows in tests.
    if type(dbapi_connection).__module__ == "sqlite3":
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@event.listens_for(Session, "after_begin")
def _apply_tenant_rls_context(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    """Re-applies the Postgres Row-Level Security session variables that
    migration 0021_add_row_level_security's policies read, every time a new
    transaction begins on this session -- not just once. `SET LOCAL` only
    lasts for a single transaction, and many routes in this app call
    `database.commit()` more than once per request, each of which silently
    starts a fresh one.

    No-op for SQLite (the automated test suite; these session variables are
    Postgres-specific) and for any session auth.get_current_user hasn't
    (yet) attached a tenant context to via `session.info` -- nothing
    tenant-scoped has any business running before authentication resolves
    who's asking, and get_current_user itself applies the context directly
    (see there) rather than relying on this listener for the very first
    transaction of a request.

    UNVERIFIED against a real Postgres instance -- see migration
    0021_add_row_level_security's docstring.
    """
    if connection.dialect.name != "postgresql":
        return
    if "rls_tenant_id" not in session.info:
        return
    _set_rls_session_variables(connection, session.info)


def _set_rls_session_variables(connection: _ExecutesSql, info: dict[Any, Any]) -> None:
    # set_config(..., true), not `SET LOCAL app.x = :value` -- Postgres's SET
    # command syntax has no placeholder for a bound parameter at all (proven
    # against a real instance: it raises "syntax error at or near $1",
    # something no SQLite-backed test can ever exercise, since this whole
    # function is skipped on every non-Postgres dialect). set_config() is a
    # normal function call, so ordinary bind parameters work, and its third
    # argument (is_local=true) is transaction-scoped exactly like SET LOCAL.
    connection.execute(
        text("SELECT set_config('app.current_tenant_id', :value, true)"),
        {"value": info.get("rls_tenant_id") or ""},
    )
    connection.execute(
        text("SELECT set_config('app.is_platform_admin', :value, true)"),
        {"value": "true" if info.get("rls_is_platform_admin") else "false"},
    )


def _engine_url() -> str:
    return get_settings().database_url


engine = create_engine(_engine_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()
