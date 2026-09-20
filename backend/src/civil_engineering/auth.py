"""Password hashing, session management, and permission dependencies.

Roles are plain strings (platform_admin | admin | power_user | user), validated
at the Pydantic schema layer -- matching this codebase's existing convention of
never using a DB-level enum (see models.py's SiteModelEntity.validation_status
and CalculationResult.calculation_type for the precedent).

platform_admin (PLAN.md Phase 16, DECISIONS.md ADR-010) is a superset of admin:
everywhere admin bypasses a per-project/per-client/per-install restriction,
platform_admin does too, plus it crosses tenant boundaries where admin does
not -- admin sees/manages everything within its OWN tenant, not the whole
install. A dedicated install has no reason to ever create a platform_admin --
there's nothing "above" its single tenant to administer -- so nothing here
changes behavior for an install that doesn't have one.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from civil_engineering.config import get_settings
from civil_engineering.database import _set_rls_session_variables, get_db
from civil_engineering.models import Client, Project, ProjectMembership, User
from civil_engineering.models import Session as SessionModel

SESSION_COOKIE_NAME = "session_id"

ROLE_PLATFORM_ADMIN = "platform_admin"
ROLE_ADMIN = "admin"
ROLE_POWER_USER = "power_user"
ROLE_USER = "user"
ROLES = (ROLE_PLATFORM_ADMIN, ROLE_ADMIN, ROLE_POWER_USER, ROLE_USER)
# Roles that satisfy every check written as "admin required" -- platform_admin
# is deliberately never excluded from one of these, since it's a superset.
ADMIN_TIER_ROLES = (ROLE_ADMIN, ROLE_PLATFORM_ADMIN)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    # A naive value is treated as already-UTC (this codebase's storage
    # convention). An aware one is *converted*, not just relabeled: Postgres
    # hands timestamptz columns back in the connection's session timezone,
    # which is equal in instant but not necessarily tzinfo == timezone.utc --
    # and set_cookie's usegmt=True requires the latter exactly, not just an
    # equivalent offset.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def create_session(database: Session, user: User) -> SessionModel:
    ttl_days = get_settings().session_ttl_days
    session = SessionModel(user_id=user.id, expires_at=_now() + timedelta(days=ttl_days))
    database.add(session)
    database.commit()
    database.refresh(session)
    return session


def revoke_session(database: Session, session: SessionModel) -> None:
    session.revoked_at = _now()
    database.commit()


def set_session_cookie(response: Response, session: SessionModel) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session.id,
        httponly=True,
        samesite="lax",
        expires=_as_utc(session.expires_at),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


def _get_active_session(database: Session, session_id: str) -> SessionModel | None:
    session = database.get(SessionModel, session_id)
    if session is None:
        return None
    if session.revoked_at is not None:
        return None
    if _as_utc(session.expires_at) < _now():
        return None
    return session


def get_current_user(request: Request, database: Session = Depends(get_db)) -> User:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    session = _get_active_session(database, session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid"
        )
    user = database.get(User, session.user_id)
    if user is None or user.disabled_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account disabled")
    _apply_tenant_rls_context(database, user)
    return user


def _apply_tenant_rls_context(database: Session, user: User) -> None:
    """Attaches this request's tenant context to the session for Postgres
    Row-Level Security (migration 0021_add_row_level_security) and applies
    it to the transaction already open from this function's own session/user
    lookups above -- database.py's Session "after_begin" listener only
    covers transactions that begin *after* this point (e.g. following a
    mid-request commit), since it fires before a tenant is known for the
    very first one. UNVERIFIED against a real Postgres instance -- see that
    migration's docstring.
    """
    database.info["rls_tenant_id"] = user.tenant_id
    database.info["rls_is_platform_admin"] = user.role == ROLE_PLATFORM_ADMIN
    bind = database.get_bind()
    if bind.dialect.name != "postgresql":
        return
    _set_rls_session_variables(database.connection(), database.info)


def logout_current_session(request: Request, database: Session) -> None:
    """Revokes the session named by the request's cookie, if any. Silently
    no-ops if there isn't one -- logging out twice isn't an error."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return
    session = database.get(SessionModel, session_id)
    if session is not None and session.revoked_at is None:
        revoke_session(database, session)


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in ADMIN_TIER_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    """Not yet used by any route -- plumbing for PLAN.md Phase 16's next slice
    (tenant provisioning), where an action must be platform-wide only and a
    regular tenant admin satisfying require_admin isn't enough."""
    if user.role != ROLE_PLATFORM_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Platform admin role required"
        )
    return user


def require_client_manager(user: User = Depends(get_current_user)) -> User:
    """For creating a new client, where there's no existing client_id to check
    tenant access against yet -- see require_client_manager_access for an
    existing one. admin/power_user can manage clients, plain user gets
    read-only (same archive-rights boundary as everything else)."""
    if user.role == ROLE_USER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    return user


def _get_client_or_404(database: Session, client_id: str) -> Client:
    client = database.get(Client, client_id)
    if client is None or client.archived_at is not None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def require_client_access(
    client_id: str,
    user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> Client:
    """Read access to an existing client -- 404, not 403, for a client
    outside the caller's tenant, matching require_project_member's
    don't-reveal-existence pattern. platform_admin crosses tenant boundaries;
    everyone else, including admin, does not (admin manages its own tenant's
    clients, not the whole install -- PLAN.md Phase 16)."""
    client = _get_client_or_404(database, client_id)
    if user.role != ROLE_PLATFORM_ADMIN and client.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def require_client_manager_access(
    client: Client = Depends(require_client_access), user: User = Depends(get_current_user)
) -> Client:
    """Write access to an existing client: tenant access (above) plus the
    same role floor as require_client_manager."""
    if user.role == ROLE_USER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    return client


def is_project_member(database: Session, project: Project, user: User) -> bool:
    """True if the user is admin, owner, or an associated collaborator -- the
    baseline required to see/act on this project at all. Works regardless of
    whether the project is currently archived (unlike require_project_member,
    which is for the common active-project case).

    platform_admin crosses tenant boundaries; admin's bypass does not -- it
    sees/manages every project within its OWN tenant, not the whole install
    (PLAN.md Phase 16's query-scoping slice). A project outside the caller's
    tenant is invisible to everyone except platform_admin, regardless of role
    or an owner_id/membership row that would otherwise grant access -- that
    can only happen for data that predates tenant assignment or was
    mismigrated, and treating it as inaccessible is the safe default.
    """
    if user.role == ROLE_PLATFORM_ADMIN:
        return True
    if project.tenant_id != user.tenant_id:
        return False
    if user.role == ROLE_ADMIN:
        return True
    if project.owner_id == user.id:
        return True
    membership = database.execute(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id, ProjectMembership.user_id == user.id
        )
    ).scalar_one_or_none()
    return membership is not None


def is_project_owner(project: Project, user: User) -> bool:
    if user.role == ROLE_PLATFORM_ADMIN:
        return True
    if project.tenant_id != user.tenant_id:
        return False
    return user.role == ROLE_ADMIN or project.owner_id == user.id


def _get_project_or_404(database: Session, project_id: str) -> Project:
    project = database.get(Project, project_id)
    if project is None or project.archived_at is not None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def require_project_member(
    project_id: str,
    user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> Project:
    project = _get_project_or_404(database, project_id)
    if not is_project_member(database, project, user):
        # 404, not 403: an unauthorized caller shouldn't learn the project exists.
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def require_project_archive_rights(
    project_id: str,
    user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> Project:
    project = _get_project_or_404(database, project_id)
    if not is_project_member(database, project, user):
        raise HTTPException(status_code=404, detail="Project not found")
    if user.role == ROLE_USER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Archive/purge rights required"
        )
    return project


def require_project_owner(
    project_id: str,
    user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> Project:
    project = _get_project_or_404(database, project_id)
    if not is_project_owner(project, user):
        if not is_project_member(database, project, user):
            raise HTTPException(status_code=404, detail="Project not found")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project owner required")
    return project


def user_owned_project_ids(database: Session, user: User) -> list[str]:
    """Project ids where the user is owner or an associated member."""
    owned = database.execute(select(Project.id).where(Project.owner_id == user.id)).scalars().all()
    member_statement = select(ProjectMembership.project_id).where(
        ProjectMembership.user_id == user.id
    )
    member = database.execute(member_statement).scalars().all()
    return list({*owned, *member})
