import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from shapely.geometry import Point, shape
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from civil_engineering.ai_service import MockAIProvider, route_question
from civil_engineering.auth import (
    ADMIN_TIER_ROLES,
    ROLE_ADMIN,
    ROLE_PLATFORM_ADMIN,
    ROLE_POWER_USER,
    ROLE_USER,
    clear_session_cookie,
    create_session,
    get_current_user,
    hash_password,
    is_project_member,
    is_project_owner,
    logout_current_session,
    require_admin,
    require_client_access,
    require_client_manager,
    require_client_manager_access,
    require_project_archive_rights,
    require_project_member,
    require_project_owner,
    set_session_cookie,
    user_owned_project_ids,
    verify_password,
)
from civil_engineering.calculations import (
    CalculationError,
    calculate_area,
    calculate_distance,
    calculate_elevation_statistics,
    calculate_perimeter,
    calculate_slope,
)
from civil_engineering.config import get_settings
from civil_engineering.database import get_db
from civil_engineering.extraction import ExtractionError, parse_file
from civil_engineering.models import (
    CalculationResult,
    Client,
    ExtractedDocument,
    ProcessingJob,
    Project,
    ProjectMembership,
    ProjectRevision,
    ProjectSummary,
    PurgeHistoryEntry,
    QuestionAnswer,
    SiteModelEntity,
    SourceFile,
    Tenant,
    User,
    new_id,
)
from civil_engineering.plan_snippets import PlanSnippetError, render_dxf_snippet
from civil_engineering.schemas import (
    ArchivedProjectResponse,
    ArchivedSourceFileResponse,
    CalculationRequest,
    CalculationResponse,
    ClientCreate,
    ClientResponse,
    ClientUpdate,
    ExtractedDocumentResponse,
    LoginRequest,
    PasswordChangeRequest,
    ProcessingJobResponse,
    ProjectCreate,
    ProjectMembershipCreate,
    ProjectMembershipResponse,
    ProjectOwnerUpdate,
    ProjectResponse,
    ProjectUpdate,
    PurgeHistoryEntryResponse,
    QuestionRequest,
    QuestionResponse,
    SiteModelEntityResponse,
    SiteModelRevisionResponse,
    SourceFileResponse,
    SummaryResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from civil_engineering.site_model import (
    SiteModelError,
    crs_linear_unit_meters,
    ensure_projected_crs,
    is_geographic_crs,
    normalize_geometry,
)
from civil_engineering.storage import (
    FileValidationError,
    archive_file,
    remove_file,
    remove_project_storage,
    restore_file,
    save_upload,
)

router = APIRouter()


def get_client_or_404(client_id: str, database: Session) -> Client:
    client = database.get(Client, client_id)
    if client is None or client.archived_at is not None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _as_utc(value: datetime) -> datetime:
    # SQLite (used by the test suite) can hand back a naive datetime for a
    # DateTime(timezone=True) column even though it was written as UTC-aware;
    # Postgres never does. Normalizing here keeps the arithmetic below correct
    # under either backend instead of raising on a naive/aware comparison.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _log_purge(
    database: Session,
    *,
    resource_type: str,
    resource_id: str,
    resource_name: str,
    project_id: str | None,
    archived_at: datetime | None,
    reason: str,
    purged_by_user_id: str | None,
) -> None:
    database.add(
        PurgeHistoryEntry(
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            project_id=project_id,
            archived_at=archived_at,
            purge_reason=reason,
            purged_by_user_id=purged_by_user_id,
        )
    )


def _purge_project(database: Session, project: Project, *, reason: str) -> None:
    _log_purge(
        database,
        resource_type="project",
        resource_id=project.id,
        resource_name=project.name,
        project_id=None,
        archived_at=project.archived_at,
        reason=reason,
        # The project's own owner_id row disappears along with it, so this is
        # captured here -- not just for a manual purge, but for an automatic
        # retention sweep too, so an owner can still find their own history.
        purged_by_user_id=project.owner_id,
    )
    remove_project_storage(project.id)
    # See the comment on the original bulk-delete below for why this bypasses
    # the ORM object graph.
    database.execute(delete(Project).where(Project.id == project.id))


def _purge_file(database: Session, source_file: SourceFile, *, reason: str) -> None:
    project = database.get(Project, source_file.project_id)
    _log_purge(
        database,
        resource_type="file",
        resource_id=source_file.id,
        resource_name=source_file.original_name,
        project_id=source_file.project_id,
        archived_at=source_file.deleted_at,
        reason=reason,
        purged_by_user_id=project.owner_id if project is not None else None,
    )
    remove_file(source_file.archived_path or source_file.stored_path)
    database.delete(source_file)


def _sweep_expired_archives(database: Session) -> None:
    """Auto-purges anything left archived past the configured retention
    window, and prunes purge-history entries past their own (separate,
    longer) retention window. Called lazily from the archived-list endpoints
    rather than on a schedule, since nothing else in this app runs on one."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    retention_cutoff = now - timedelta(days=settings.archive_retention_days)
    history_cutoff = now - timedelta(days=settings.purge_history_retention_days)

    expired_projects = list(
        database.scalars(
            select(Project).where(
                Project.archived_at.is_not(None), Project.archived_at < retention_cutoff
            )
        )
    )
    for project in expired_projects:
        _purge_project(database, project, reason="retention_expired")

    expired_files = list(
        database.scalars(
            select(SourceFile).where(
                SourceFile.deleted_at.is_not(None), SourceFile.deleted_at < retention_cutoff
            )
        )
    )
    for source_file in expired_files:
        _purge_file(database, source_file, reason="retention_expired")

    database.execute(delete(PurgeHistoryEntry).where(PurgeHistoryEntry.purged_at < history_cutoff))
    database.commit()


@router.post("/auth/login", response_model=UserResponse)
def login(payload: LoginRequest, response: Response, database: Session = Depends(get_db)) -> User:
    user = database.scalar(select(User).where(User.username == payload.username))
    if (
        user is None
        or user.disabled_at is not None
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    session = create_session(database, user)
    set_session_cookie(response, session)
    return user


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, database: Session = Depends(get_db)) -> None:
    logout_current_session(request, database)
    clear_session_cookie(response)


@router.get("/auth/me", response_model=UserResponse)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.patch("/auth/password", status_code=status.HTTP_204_NO_CONTENT)
def change_own_password(
    payload: PasswordChangeRequest,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect"
        )
    current_user.password_hash = hash_password(payload.new_password)
    database.commit()


def _require_not_last_active_admin(database: Session, target: User) -> None:
    # ADMIN_TIER_ROLES, not just ROLE_ADMIN: a platform_admin can already do
    # everything an admin can (see auth.py), so it counts toward "an
    # admin-tier account still exists" the same way a plain admin does.
    if target.role not in ADMIN_TIER_ROLES or target.disabled_at is not None:
        return
    # A platform_admin anywhere in the install counts (it can already manage
    # any tenant), or another admin within target's OWN tenant -- admin no
    # longer means "the whole install" (PLAN.md Phase 16), so an admin in a
    # different tenant doesn't help target's tenant keep an admin.
    other_admins = database.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.disabled_at.is_(None),
            User.id != target.id,
            (User.role == ROLE_PLATFORM_ADMIN)
            | ((User.role == ROLE_ADMIN) & (User.tenant_id == target.tenant_id)),
        )
    )
    if not other_admins:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot disable or delete the last active admin",
        )


def _require_no_owned_projects(database: Session, target: User) -> None:
    owned = list(
        database.scalars(
            select(Project).where(Project.owner_id == target.id, Project.archived_at.is_(None))
        )
    )
    if owned:
        names = ", ".join(project.name for project in owned)
        raise HTTPException(
            status_code=422,
            detail=(
                "Reassign ownership of these projects to another power_user before "
                f"disabling or deleting this user: {names}"
            ),
        )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    database: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    # Still a global uniqueness check, not yet per-tenant -- a separate,
    # not-yet-done PLAN.md Phase 16 follow-on item (RISK_REGISTER.md).
    existing = database.scalar(select(User).where(User.username == payload.username))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already exists")
    if admin.role == ROLE_PLATFORM_ADMIN:
        tenant_id = payload.tenant_id
        if tenant_id is not None and database.get(Tenant, tenant_id) is None:
            raise HTTPException(status_code=422, detail="tenant_id does not exist")
    else:
        tenant_id = admin.tenant_id
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        tenant_id=tenant_id,
    )
    database.add(user)
    database.commit()
    database.refresh(user)
    return user


@router.get("/users", response_model=list[UserResponse])
def list_users(
    database: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> list[User]:
    statement = select(User).order_by(User.username)
    if admin.role != ROLE_PLATFORM_ADMIN:
        statement = statement.where(User.tenant_id == admin.tenant_id)
    return list(database.scalars(statement))


@router.get("/users/lookup", response_model=UserResponse)
def lookup_user_by_username(
    username: str,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Exact-match username -> user, for any authenticated caller (not just
    admins). Needed so a Power User project owner can add a collaborator by
    username without the full-directory access GET /users requires -- this
    only confirms one exact username, it doesn't enumerate the directory.
    Scoped to the caller's own tenant (platform_admin excepted): finding a
    cross-tenant username would be an information leak, and the collaborator
    would be rejected anyway when actually added (see add_project_member)."""
    statement = select(User).where(User.username == username)
    if current_user.role != ROLE_PLATFORM_ADMIN:
        statement = statement.where(User.tenant_id == current_user.tenant_id)
    user = database.scalar(statement)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def get_user_or_404(user_id: str, database: Session) -> User:
    user = database.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _require_manageable_user(user_id: str, database: Session, admin: User) -> User:
    """Like get_user_or_404, but 404s a user outside the calling admin's own
    tenant instead of returning it -- an admin manages its own tenant's
    users, not the whole install (PLAN.md Phase 16). platform_admin is
    exempt, same as everywhere else."""
    user = get_user_or_404(user_id, database)
    if admin.role != ROLE_PLATFORM_ADMIN and user.tenant_id != admin.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    payload: UserUpdate,
    database: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    user = _require_manageable_user(user_id, database, admin)
    if payload.disabled is True:
        _require_not_last_active_admin(database, user)
        _require_no_owned_projects(database, user)
        user.disabled_at = datetime.now(timezone.utc)
    elif payload.disabled is False:
        user.disabled_at = None
    if payload.role is not None:
        # Guard only a move OUT of the admin tier entirely -- an admin <->
        # platform_admin lateral move doesn't reduce how many admin-tier
        # accounts exist, so it needs no check.
        if user.role in ADMIN_TIER_ROLES and payload.role not in ADMIN_TIER_ROLES:
            _require_not_last_active_admin(database, user)
        if payload.role == ROLE_USER:
            # ADR-009: "a project's owner must be a power_user." Demoting a
            # user to plain `user` while they still own an active project
            # would leave that invariant broken -- `require_project_owner`
            # only checks `project.owner_id == user.id`, not the owner's
            # current role, so they'd keep archive/purge/reassign rights on
            # it despite `user` never being allowed those "anywhere".
            _require_no_owned_projects(database, user)
        user.role = payload.role
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    database.commit()
    database.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    database: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> None:
    user = _require_manageable_user(user_id, database, admin)
    _require_not_last_active_admin(database, user)
    _require_no_owned_projects(database, user)
    database.delete(user)
    database.commit()


def _membership_response(membership: ProjectMembership) -> ProjectMembershipResponse:
    # username/role live on the related User, not the membership row itself,
    # so from_attributes=True alone can't fill them -- build explicitly.
    return ProjectMembershipResponse(
        id=membership.id,
        project_id=membership.project_id,
        user_id=membership.user_id,
        username=membership.user.username,
        role=membership.user.role,
        created_at=membership.created_at,
    )


@router.get("/projects/{project_id}/members", response_model=list[ProjectMembershipResponse])
def list_project_members(
    project: Project = Depends(require_project_member),
    database: Session = Depends(get_db),
) -> list[ProjectMembershipResponse]:
    statement = select(ProjectMembership).where(ProjectMembership.project_id == project.id)
    return [_membership_response(m) for m in database.scalars(statement)]


@router.post(
    "/projects/{project_id}/members",
    response_model=ProjectMembershipResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_project_member(
    payload: ProjectMembershipCreate,
    project: Project = Depends(require_project_owner),
    database: Session = Depends(get_db),
) -> ProjectMembershipResponse:
    member = get_user_or_404(payload.user_id, database)
    if member.tenant_id != project.tenant_id:
        raise HTTPException(
            status_code=422, detail="A collaborator must belong to the project's own tenant"
        )
    if member.id == project.owner_id:
        raise HTTPException(
            status_code=422, detail="The owner is already associated with this project"
        )
    existing = database.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id, ProjectMembership.user_id == member.id
        )
    )
    if existing is not None:
        return _membership_response(existing)
    membership = ProjectMembership(project_id=project.id, user_id=member.id)
    database.add(membership)
    database.commit()
    database.refresh(membership)
    return _membership_response(membership)


@router.delete("/projects/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project_member(
    user_id: str,
    project: Project = Depends(require_project_owner),
    database: Session = Depends(get_db),
) -> None:
    membership = database.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id, ProjectMembership.user_id == user_id
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    database.delete(membership)
    database.commit()


@router.patch("/projects/{project_id}/owner", response_model=ProjectResponse)
def reassign_project_owner(
    payload: ProjectOwnerUpdate,
    project: Project = Depends(require_project_owner),
    database: Session = Depends(get_db),
) -> Project:
    new_owner = get_user_or_404(payload.owner_id, database)
    if new_owner.role != ROLE_POWER_USER:
        raise HTTPException(status_code=422, detail="A project owner must be a power_user")
    if new_owner.disabled_at is not None:
        raise HTTPException(status_code=422, detail="Cannot assign a disabled user as owner")
    if new_owner.tenant_id != project.tenant_id:
        raise HTTPException(
            status_code=422, detail="A project owner must belong to the project's own tenant"
        )
    previous_owner_id = project.owner_id
    project.owner_id = new_owner.id
    # The new owner's access no longer depends on a membership row.
    stale_membership = database.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id, ProjectMembership.user_id == new_owner.id
        )
    )
    if stale_membership is not None:
        database.delete(stale_membership)
    # The old owner keeps their access as a collaborator unless explicitly
    # removed, same as any collaborator -- an owner never has a membership row
    # of their own (add_project_member forbids adding the current owner as a
    # member), so without adding one here they'd end up with neither owner_id
    # nor a membership row and be locked out of the project entirely, the
    # opposite of what this is meant to do. Skipped for an admin-tier account
    # (already has universal access) or a no-op reassignment to the same user.
    if previous_owner_id is not None and previous_owner_id != new_owner.id:
        previous_owner = database.get(User, previous_owner_id)
        if previous_owner is not None and previous_owner.role not in ADMIN_TIER_ROLES:
            existing_membership = database.scalar(
                select(ProjectMembership).where(
                    ProjectMembership.project_id == project.id,
                    ProjectMembership.user_id == previous_owner_id,
                )
            )
            if existing_membership is None:
                database.add(ProjectMembership(project_id=project.id, user_id=previous_owner_id))
    database.commit()
    database.refresh(project)
    return project


@router.post("/clients", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
def create_client(
    payload: ClientCreate,
    database: Session = Depends(get_db),
    user: User = Depends(require_client_manager),
) -> Client:
    if user.role == ROLE_PLATFORM_ADMIN:
        tenant_id = payload.tenant_id
        if tenant_id is not None and database.get(Tenant, tenant_id) is None:
            raise HTTPException(status_code=422, detail="tenant_id does not exist")
    else:
        tenant_id = user.tenant_id
    client = Client(name=payload.name, tenant_id=tenant_id)
    database.add(client)
    database.commit()
    database.refresh(client)
    return client


@router.get("/clients", response_model=list[ClientResponse])
def list_clients(
    database: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[Client]:
    statement = select(Client).where(Client.archived_at.is_(None)).order_by(Client.name)
    if current_user.role != ROLE_PLATFORM_ADMIN:
        statement = statement.where(Client.tenant_id == current_user.tenant_id)
    return list(database.scalars(statement))


@router.get("/clients/{client_id}", response_model=ClientResponse)
def read_client(client: Client = Depends(require_client_access)) -> Client:
    return client


@router.patch("/clients/{client_id}", response_model=ClientResponse)
def update_client(
    payload: ClientUpdate,
    client: Client = Depends(require_client_manager_access),
    database: Session = Depends(get_db),
) -> Client:
    if payload.name is not None:
        client.name = payload.name
    database.commit()
    database.refresh(client)
    return client


@router.post("/clients/{client_id}/archive", response_model=ClientResponse)
def archive_client(
    client: Client = Depends(require_client_manager_access), database: Session = Depends(get_db)
) -> Client:
    client.archived_at = datetime.now(timezone.utc)
    database.commit()
    database.refresh(client)
    return client


def _require_projected_crs(crs: str | None) -> None:
    """Reject a geographic CRS before it can be stored on a project.

    Distances, areas, and perimeters are all planar (see calculations.py), so a
    lat/lon CRS would silently produce degree-based numbers labelled as feet or
    metres. Blocking it here keeps that state from ever being created; the
    calculation and question endpoints repeat the check for projects stored
    before this validation existed.
    """
    try:
        ensure_projected_crs(crs)
    except SiteModelError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Project:
    if current_user.role == ROLE_USER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins and power users can create projects",
        )
    _require_projected_crs(payload.coordinate_reference_system)
    data = payload.model_dump()
    if current_user.role == ROLE_POWER_USER:
        data["owner_id"] = current_user.id
        data["tenant_id"] = current_user.tenant_id
    else:  # admin or platform_admin
        owner_id = data.get("owner_id")
        if not owner_id:
            raise HTTPException(
                status_code=422, detail="owner_id is required and must belong to a power_user"
            )
        owner = get_user_or_404(owner_id, database)
        if owner.role != ROLE_POWER_USER:
            raise HTTPException(status_code=422, detail="A project owner must be a power_user")
        if current_user.role == ROLE_PLATFORM_ADMIN:
            tenant_id = data.get("tenant_id")
            if not tenant_id:
                raise HTTPException(
                    status_code=422, detail="tenant_id is required for a platform_admin caller"
                )
            if database.get(Tenant, tenant_id) is None:
                raise HTTPException(status_code=422, detail="tenant_id does not exist")
        else:
            tenant_id = current_user.tenant_id
        data["tenant_id"] = tenant_id
        if owner.tenant_id != tenant_id:
            raise HTTPException(
                status_code=422, detail="A project owner must belong to the project's own tenant"
            )
    if payload.client_id is not None:
        client = get_client_or_404(payload.client_id, database)
        if client.tenant_id != data["tenant_id"]:
            raise HTTPException(
                status_code=422, detail="A project's client must belong to the project's own tenant"
            )
    project = Project(**data)
    database.add(project)
    database.commit()
    database.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(
    database: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[Project]:
    statement = select(Project).where(Project.archived_at.is_(None)).order_by(Project.name)
    if current_user.role != ROLE_PLATFORM_ADMIN:
        statement = statement.where(Project.tenant_id == current_user.tenant_id)
        if current_user.role != ROLE_ADMIN:
            statement = statement.where(
                Project.id.in_(user_owned_project_ids(database, current_user))
            )
    return list(database.scalars(statement))


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def read_project(project: Project = Depends(require_project_member)) -> Project:
    return project


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
def update_project(
    payload: ProjectUpdate,
    project: Project = Depends(require_project_member),
    database: Session = Depends(get_db),
) -> Project:
    values = payload.model_dump(exclude_unset=True)
    if "client_id" in values and values["client_id"] is not None:
        client = get_client_or_404(values["client_id"], database)
        if client.tenant_id != project.tenant_id:
            raise HTTPException(
                status_code=422, detail="A project's client must belong to the project's own tenant"
            )
    if "coordinate_reference_system" in values:
        _require_projected_crs(values["coordinate_reference_system"])
    for key, value in values.items():
        setattr(project, key, value)
    database.commit()
    database.refresh(project)
    return project


@router.post("/projects/{project_id}/archive", response_model=ProjectResponse)
def archive_project(
    project: Project = Depends(require_project_owner), database: Session = Depends(get_db)
) -> Project:
    project.archived_at = datetime.now(timezone.utc)
    database.commit()
    database.refresh(project)
    return project


@router.get("/admin/projects/archived", response_model=list[ArchivedProjectResponse])
def list_archived_projects(
    database: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[ArchivedProjectResponse]:
    if current_user.role == ROLE_USER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Archive/purge rights required"
        )
    _sweep_expired_archives(database)
    settings = get_settings()
    retention = timedelta(days=settings.archive_retention_days)
    warning_window = timedelta(days=settings.archive_purge_warning_days)
    now = datetime.now(timezone.utc)
    statement = (
        select(Project).where(Project.archived_at.is_not(None)).order_by(Project.archived_at.desc())
    )
    if current_user.role != ROLE_PLATFORM_ADMIN:
        statement = statement.where(Project.tenant_id == current_user.tenant_id)
        if current_user.role != ROLE_ADMIN:
            statement = statement.where(
                Project.id.in_(user_owned_project_ids(database, current_user))
            )
    projects = database.scalars(statement)
    responses = []
    for project in projects:
        archived_at = _as_utc(cast(datetime, project.archived_at))
        scheduled = archived_at + retention
        responses.append(
            ArchivedProjectResponse(
                **ProjectResponse.model_validate(project).model_dump(),
                purge_scheduled_at=scheduled,
                purge_warning=now >= scheduled - warning_window,
            )
        )
    return responses


def _require_archived_project_owner(
    database: Session, project_id: str, current_user: User
) -> Project:
    """Like require_project_owner, but for a project that IS archived (that
    dependency 404s on archived projects, since it's meant for the common
    active-project case)."""
    project = database.get(Project, project_id)
    if project is None or project.archived_at is None:
        raise HTTPException(status_code=404, detail="Archived project not found")
    if not is_project_owner(project, current_user):
        if not is_project_member(database, project, current_user):
            raise HTTPException(status_code=404, detail="Archived project not found")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project owner required")
    return project


@router.post("/admin/projects/{project_id}/restore", response_model=ProjectResponse)
def restore_archived_project(
    project_id: str,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Project:
    project = _require_archived_project_owner(database, project_id, current_user)
    project.archived_at = None
    database.commit()
    database.refresh(project)
    return project


@router.delete("/admin/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge_archived_project(
    project_id: str,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    project = _require_archived_project_owner(database, project_id, current_user)
    # _purge_project relies on the schema's ON DELETE CASCADE foreign keys to
    # remove every dependent row server-side via a single bulk DELETE.
    # Loading the object graph through the ORM instead (database.delete)
    # issues one DELETE per row, which is impractically slow once a
    # project's site model has hundreds of thousands of entities.
    _purge_project(database, project, reason="manual")
    database.commit()


async def _upload_source_file(
    project: Project,
    file: UploadFile,
    database: Session,
    document_group_id: str | None,
) -> SourceFile:
    file_id = new_id()
    source_file = SourceFile(
        id=file_id,
        project_id=project.id,
        original_name=Path(file.filename or "").name,
        stored_path="",
        media_type=file.content_type or "application/octet-stream",
        size_bytes=0,
        checksum="pending",
        document_group_id=document_group_id or file_id,
    )
    try:
        path, size, checksum = await save_upload(file, project.id, source_file.id)
    except FileValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    duplicate = database.scalar(
        select(SourceFile).where(
            SourceFile.project_id == project.id, SourceFile.checksum == checksum
        )
    )
    if duplicate is not None:
        remove_file(str(path))
        raise HTTPException(
            status_code=409,
            detail=(
                f"File '{source_file.original_name}' upload failed. "
                f"'{duplicate.original_name}' with the same content already exists in this project."
            ),
        )
    source_file.stored_path = str(path)
    source_file.size_bytes = size
    source_file.checksum = checksum
    database.add(source_file)
    try:
        database.commit()
    except IntegrityError as error:
        database.rollback()
        remove_file(str(path))
        existing = database.scalar(
            select(SourceFile).where(
                SourceFile.project_id == project.id, SourceFile.checksum == checksum
            )
        )
        existing_name = existing.original_name if existing is not None else "another file"
        raise HTTPException(
            status_code=409,
            detail=(
                f"File '{source_file.original_name}' upload failed. "
                f"'{existing_name}' with the same content already exists in this project."
            ),
        ) from error
    database.refresh(source_file)
    return source_file


@router.post(
    "/projects/{project_id}/files",
    response_model=SourceFileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    project_id: str,
    file: UploadFile = File(...),
    database: Session = Depends(get_db),
    project: Project = Depends(require_project_member),
) -> SourceFile:
    return await _upload_source_file(project, file, database, document_group_id=None)


@router.post(
    "/projects/{project_id}/files/{file_id}/replace",
    response_model=SourceFileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def replace_file(
    project_id: str,
    file_id: str,
    file: UploadFile = File(...),
    database: Session = Depends(get_db),
    project: Project = Depends(require_project_member),
) -> SourceFile:
    statement = select(SourceFile).where(
        SourceFile.id == file_id, SourceFile.project_id == project_id
    )
    previous = database.scalar(statement)
    if previous is None:
        raise HTTPException(status_code=404, detail="File not found")
    if previous.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Archived files cannot be replaced")
    if previous.superseded_by_id is not None:
        raise HTTPException(
            status_code=409,
            detail="This file has already been replaced by a newer version; "
            "replace that version instead",
        )
    new_file = await _upload_source_file(
        project, file, database, document_group_id=previous.document_group_id
    )
    previous.superseded_by_id = new_file.id
    database.commit()
    database.refresh(new_file)
    return new_file


@router.get("/projects/{project_id}/files", response_model=list[SourceFileResponse])
def list_files(
    project_id: str,
    database: Session = Depends(get_db),
    _project: Project = Depends(require_project_member),
) -> list[SourceFile]:
    statement = (
        select(SourceFile)
        .where(SourceFile.project_id == project_id, SourceFile.deleted_at.is_(None))
        .order_by(SourceFile.uploaded_at.desc())
    )
    return list(database.scalars(statement))


@router.get("/projects/{project_id}/files/{file_id}/download")
def download_file(
    project_id: str,
    file_id: str,
    database: Session = Depends(get_db),
    _project: Project = Depends(require_project_member),
) -> FileResponse:
    statement = select(SourceFile).where(
        SourceFile.id == file_id, SourceFile.project_id == project_id
    )
    source_file = database.scalar(statement)
    if source_file is None or source_file.deleted_at is not None:
        raise HTTPException(status_code=404, detail="File not found")
    if not Path(source_file.stored_path).is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        source_file.stored_path,
        media_type=source_file.media_type,
        filename=source_file.original_name,
    )


@router.delete("/projects/{project_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(
    project_id: str,
    file_id: str,
    database: Session = Depends(get_db),
    _project: Project = Depends(require_project_archive_rights),
) -> None:
    statement = select(SourceFile).where(
        SourceFile.id == file_id, SourceFile.project_id == project_id
    )
    source_file = database.scalar(statement)
    if source_file is None:
        raise HTTPException(status_code=404, detail="File not found")
    if source_file.deleted_at is not None:
        raise HTTPException(status_code=409, detail="File is already archived")
    source_file.status_before_delete = source_file.status
    source_file.archived_path = str(archive_file(source_file.stored_path, project_id, file_id))
    source_file.deleted_at = datetime.now(timezone.utc)
    source_file.status = "deleted"
    database.commit()


@router.post(
    "/projects/{project_id}/files/{file_id}/process",
    response_model=ProcessingJobResponse,
    status_code=status.HTTP_201_CREATED,
)
def process_file(
    project_id: str,
    file_id: str,
    database: Session = Depends(get_db),
    _project: Project = Depends(require_project_member),
) -> ProcessingJob:
    statement = select(SourceFile).where(
        SourceFile.id == file_id, SourceFile.project_id == project_id
    )
    source_file = database.scalar(statement)
    if source_file is None:
        raise HTTPException(status_code=404, detail="File not found")
    if source_file.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Archived files cannot be processed")
    if Path(source_file.stored_path).suffix.lower() not in {
        ".pdf",
        ".dxf",
        ".csv",
        ".txt",
        ".tif",
        ".tiff",
        ".xml",
    }:
        source_file.status = "unsupported"
        database.commit()
        raise HTTPException(status_code=400, detail="Unsupported processing file type")
    job = ProcessingJob(
        project_id=project_id,
        source_file_id=file_id,
        status="processing",
        parser_name=Path(source_file.stored_path).suffix.lower().lstrip("."),
        started_at=datetime.now(timezone.utc),
    )
    database.add(job)
    source_file.status = "processing"
    database.commit()
    try:
        normalized = parse_file(Path(source_file.stored_path), source_file.original_name)
        max_attempts = 5
        for attempt in range(max_attempts):
            current_revision = database.scalar(
                select(func.max(ExtractedDocument.revision_number)).where(
                    ExtractedDocument.source_file_id == file_id
                )
            )
            extraction = ExtractedDocument(
                processing_job_id=job.id,
                source_file_id=file_id,
                revision_number=(current_revision or 0) + 1,
                parser_name=normalized.parser_name,
                content=normalized.as_dict(),
                warnings=normalized.warnings,
            )
            database.add(extraction)
            try:
                database.flush()
                break
            except IntegrityError:
                database.rollback()
                if attempt == max_attempts - 1:
                    raise
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.warnings = normalized.warnings
        source_file.status = "completed"
        source_file.processed_at = job.completed_at
    except (ExtractionError, OSError, IntegrityError) as error:
        job.status = "failed"
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = str(error)
        source_file.status = "failed"
        source_file.error_message = str(error)
    database.commit()
    database.refresh(job)
    return job


@router.get("/projects/{project_id}/processing", response_model=list[ProcessingJobResponse])
def list_processing_jobs(
    project_id: str,
    database: Session = Depends(get_db),
    _project: Project = Depends(require_project_member),
) -> list[ProcessingJob]:
    statement = (
        select(ProcessingJob)
        .where(ProcessingJob.project_id == project_id)
        .order_by(ProcessingJob.started_at.desc())
    )
    return list(database.scalars(statement))


@router.get("/admin/files/archived", response_model=list[ArchivedSourceFileResponse])
def list_archived_files(
    database: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[ArchivedSourceFileResponse]:
    if current_user.role == ROLE_USER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Archive/purge rights required"
        )
    _sweep_expired_archives(database)
    settings = get_settings()
    retention = timedelta(days=settings.archive_retention_days)
    warning_window = timedelta(days=settings.archive_purge_warning_days)
    now = datetime.now(timezone.utc)
    statement = (
        select(SourceFile)
        .where(SourceFile.deleted_at.is_not(None))
        .order_by(SourceFile.deleted_at.desc())
    )
    if current_user.role != ROLE_PLATFORM_ADMIN:
        if current_user.role == ROLE_ADMIN:
            tenant_project_ids = select(Project.id).where(
                Project.tenant_id == current_user.tenant_id
            )
            statement = statement.where(SourceFile.project_id.in_(tenant_project_ids))
        else:
            statement = statement.where(
                SourceFile.project_id.in_(user_owned_project_ids(database, current_user))
            )
    files = database.scalars(statement)
    responses = []
    for source_file in files:
        deleted_at = _as_utc(cast(datetime, source_file.deleted_at))
        scheduled = deleted_at + retention
        responses.append(
            ArchivedSourceFileResponse(
                **SourceFileResponse.model_validate(source_file).model_dump(),
                purge_scheduled_at=scheduled,
                purge_warning=now >= scheduled - warning_window,
            )
        )
    return responses


def _require_archived_file_access(
    database: Session, file_id: str, current_user: User
) -> SourceFile:
    source_file = database.get(SourceFile, file_id)
    if source_file is None or source_file.deleted_at is None:
        raise HTTPException(status_code=404, detail="Archived file not found")
    project = database.get(Project, source_file.project_id)
    if project is None or not is_project_member(database, project, current_user):
        raise HTTPException(status_code=404, detail="Archived file not found")
    if current_user.role == ROLE_USER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Archive/purge rights required"
        )
    return source_file


@router.post("/admin/files/{file_id}/restore", response_model=SourceFileResponse)
def restore_archived_file(
    file_id: str,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SourceFile:
    source_file = _require_archived_file_access(database, file_id, current_user)
    extension = Path(source_file.original_name).suffix.lower()
    try:
        restored_path = restore_file(
            source_file.archived_path or "", source_file.project_id, source_file.id, extension
        )
    except FileValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    source_file.stored_path = str(restored_path)
    source_file.archived_path = None
    source_file.deleted_at = None
    source_file.status = source_file.status_before_delete or "queued"
    source_file.status_before_delete = None
    database.commit()
    database.refresh(source_file)
    return source_file


@router.delete("/admin/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge_archived_file(
    file_id: str,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    source_file = _require_archived_file_access(database, file_id, current_user)
    _purge_file(database, source_file, reason="manual")
    database.commit()


@router.get("/admin/purge-history", response_model=list[PurgeHistoryEntryResponse])
def list_purge_history(
    database: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[PurgeHistoryEntry]:
    if current_user.role == ROLE_USER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Archive/purge rights required"
        )
    statement = select(PurgeHistoryEntry).order_by(PurgeHistoryEntry.purged_at.desc())
    if current_user.role == ROLE_ADMIN:
        # project_id/resource_id cover a still-existing project's file purges
        # (its tenant is still readable); purged_by_user_id covers a purged
        # *project* itself, where the ownership row that would otherwise
        # answer "was this in my tenant" is gone -- fall back to the tenant
        # of whoever it was purged from instead.
        tenant_project_ids = set(
            database.scalars(select(Project.id).where(Project.tenant_id == current_user.tenant_id))
        )
        tenant_user_ids = set(
            database.scalars(select(User.id).where(User.tenant_id == current_user.tenant_id))
        )
        statement = statement.where(
            PurgeHistoryEntry.project_id.in_(tenant_project_ids)
            | PurgeHistoryEntry.resource_id.in_(tenant_project_ids)
            | PurgeHistoryEntry.purged_by_user_id.in_(tenant_user_ids)
        )
    elif current_user.role != ROLE_PLATFORM_ADMIN:
        accessible = set(user_owned_project_ids(database, current_user))
        statement = statement.where(
            PurgeHistoryEntry.project_id.in_(accessible)
            | PurgeHistoryEntry.resource_id.in_(accessible)
            | (PurgeHistoryEntry.purged_by_user_id == current_user.id)
        )
    return list(database.scalars(statement))


@router.get("/projects/{project_id}/processing/{job_id}", response_model=ProcessingJobResponse)
def read_processing_job(
    project_id: str,
    job_id: str,
    database: Session = Depends(get_db),
    _project: Project = Depends(require_project_member),
) -> ProcessingJob:
    statement = select(ProcessingJob).where(
        ProcessingJob.id == job_id, ProcessingJob.project_id == project_id
    )
    job = database.scalar(statement)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return job


@router.get(
    "/projects/{project_id}/files/{file_id}/extraction",
    response_model=ExtractedDocumentResponse,
)
def read_extraction(
    project_id: str,
    file_id: str,
    database: Session = Depends(get_db),
    _project: Project = Depends(require_project_member),
) -> ExtractedDocument:
    source_file = database.scalar(
        select(SourceFile).where(SourceFile.id == file_id, SourceFile.project_id == project_id)
    )
    if source_file is None:
        raise HTTPException(status_code=404, detail="File not found")
    extraction = database.scalar(
        select(ExtractedDocument)
        .where(ExtractedDocument.source_file_id == file_id)
        .order_by(ExtractedDocument.revision_number.desc())
    )
    if extraction is None:
        raise HTTPException(status_code=404, detail="Extraction not found")
    return extraction


@router.post(
    "/projects/{project_id}/site-model/revisions/from-extraction/{file_id}",
    response_model=SiteModelRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_site_model_revision(
    project_id: str,
    file_id: str,
    source_crs: str | None = None,
    database: Session = Depends(get_db),
    project: Project = Depends(require_project_member),
) -> ProjectRevision:
    extraction = database.scalar(
        select(ExtractedDocument)
        .join(SourceFile, SourceFile.id == ExtractedDocument.source_file_id)
        .where(SourceFile.project_id == project_id, ExtractedDocument.source_file_id == file_id)
        .order_by(ExtractedDocument.created_at.desc(), ExtractedDocument.id.desc())
    )
    if extraction is None:
        raise HTTPException(status_code=404, detail="Extraction not found")
    existing_revisions = database.scalars(
        select(ProjectRevision).where(ProjectRevision.project_id == project_id)
    )
    for existing in existing_revisions:
        if existing.source_job_ids == [extraction.processing_job_id]:
            return existing
    max_attempts = 5
    for attempt in range(max_attempts):
        current_revision = database.scalar(
            select(func.max(ProjectRevision.revision_number)).where(
                ProjectRevision.project_id == project_id
            )
        )
        revision = ProjectRevision(
            project_id=project.id,
            revision_number=(current_revision or 0) + 1,
            source_job_ids=[extraction.processing_job_id],
            notes="Accepted from normalized extraction",
        )
        database.add(revision)
        try:
            database.flush()
            break
        except IntegrityError:
            database.rollback()
            if attempt == max_attempts - 1:
                raise HTTPException(
                    status_code=409,
                    detail="Could not accept this revision due to a concurrent accept in the "
                    "same project; please retry.",
                ) from None
    table_rows: list[dict[str, Any]] = []
    text_lines: list[str] = []
    text_source: dict[str, Any] | None = None
    created_entities: list[SiteModelEntity] = []
    for item in extraction.content.get("items", []):
        value = item.get("value", {})
        item_type = str(item.get("item_type", "unknown"))
        if item_type == "text_line":
            text_lines.append(str(value))
            text_source = text_source or item.get("source")
            continue
        if item_type == "table_row" and isinstance(value, dict):
            point = _table_row_point(value)
            if point is None:
                table_rows.append(value)
                continue
            value = {**value, "point": point}
            item_type = "point"
        geometry = None
        validation_status = "unmapped"
        if isinstance(value, dict) and any(
            key in value for key in ("start", "end", "point", "points")
        ):
            try:
                geometry = normalize_geometry(
                    value, source_crs, project.coordinate_reference_system
                )
                validation_status = "valid"
            except SiteModelError:
                validation_status = "invalid"
        entity = SiteModelEntity(
            revision_id=revision.id,
            entity_type=item_type,
            geometry=geometry,
            properties=_classify_entity(value, item.get("source")),
            source_reference=item.get("source"),
            validation_status=validation_status,
        )
        database.add(entity)
        created_entities.append(entity)
    database.flush()
    _link_labels_to_nearby_geometry(created_entities, project)
    if text_lines:
        database.add(
            SiteModelEntity(
                revision_id=revision.id,
                entity_type="text",
                properties={
                    "line_count": len(text_lines),
                    "sample_lines": text_lines[:20],
                },
                source_reference=text_source,
                validation_status="unmapped",
            )
        )
    if table_rows:
        first_row = next(
            item
            for item in extraction.content.get("items", [])
            if item.get("item_type") == "table_row"
        )
        database.add(
            SiteModelEntity(
                revision_id=revision.id,
                entity_type="table",
                properties={
                    "row_count": len(table_rows),
                    "columns": list(table_rows[0].keys()),
                    "sample_rows": table_rows[:5],
                },
                source_reference=first_row.get("source"),
                validation_status="unmapped",
            )
        )
    database.commit()
    database.refresh(revision)
    return revision


# Keyword vocabulary for semantic entity classification, matched against a DXF layer
# name or an explicit CSV type/classification column (see RISK_REGISTER.md: inference
# only from these signals, never guessed from geometry shape alone).
PARCEL_TYPE_KEYWORDS = ("parcel", "property", "boundary", "lot")
BUILDING_TYPE_KEYWORDS = ("building", "footprint", "structure")
DRIVEWAY_TYPE_KEYWORDS = ("driveway", "drive", "road", "street", "access")
CURB_CUT_TYPE_KEYWORDS = ("curb cut", "curbcut")
# PLAN.md Phase 14: keyword vocabulary for the site-feature roles TestQuestions asks
# about that had no semantic_type at all before this. Same deterministic,
# layer/type-column-only matching as the roles above (see RISK_REGISTER.md: never
# guessed from geometry shape alone).
UTILITY_EASEMENT_TYPE_KEYWORDS = ("easement",)
PARKING_TYPE_KEYWORDS = ("parking",)
TREE_TYPE_KEYWORDS = ("tree",)
SIDEWALK_TYPE_KEYWORDS = ("sidewalk", "walkway")
DETENTION_BASIN_TYPE_KEYWORDS = ("detention", "retention", "basin")


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    # Word-boundary match, not a bare substring: a short bare keyword like "tree"
    # is a literal substring of an unrelated word like "street" -- the same
    # hazard already fixed for DIRECTION_AXES in ai_service.py's
    # _parse_directional_question. An optional trailing "s" still matches an
    # ordinary plural layer name ("TREES", "SIDEWALKS") without a boundary
    # between the keyword and the "s" defeating the match entirely.
    return any(re.search(rf"\b{re.escape(keyword)}s?\b", text) for keyword in keywords)


def _semantic_type_from_text(text: str) -> str | None:
    lowered = text.lower()
    if _contains_keyword(lowered, CURB_CUT_TYPE_KEYWORDS):
        return "curb_cut"
    if _contains_keyword(lowered, UTILITY_EASEMENT_TYPE_KEYWORDS):
        return "utility_easement"
    if _contains_keyword(lowered, DETENTION_BASIN_TYPE_KEYWORDS):
        return "detention_basin"
    if _contains_keyword(lowered, PARKING_TYPE_KEYWORDS):
        return "parking"
    if _contains_keyword(lowered, TREE_TYPE_KEYWORDS):
        return "tree"
    if _contains_keyword(lowered, SIDEWALK_TYPE_KEYWORDS):
        return "sidewalk"
    if _contains_keyword(lowered, PARCEL_TYPE_KEYWORDS):
        return "parcel_boundary"
    if _contains_keyword(lowered, BUILDING_TYPE_KEYWORDS):
        return "building_footprint"
    if _contains_keyword(lowered, DRIVEWAY_TYPE_KEYWORDS):
        return "driveway_road"
    return None


def _classify_entity(value: Any, source: dict[str, Any] | None) -> dict[str, Any]:
    properties = dict(value) if isinstance(value, dict) else {"value": value}
    candidates: list[str] = []
    if source and source.get("layer"):
        candidates.append(str(source["layer"]))
    if isinstance(value, dict):
        for key in ("type", "classification", "category"):
            if value.get(key):
                candidates.append(str(value[key]))
    for candidate in candidates:
        semantic_type = _semantic_type_from_text(candidate)
        if semantic_type is not None:
            properties["semantic_type"] = semantic_type
            break
    if isinstance(value, dict):
        for key in ("zoning", "zone"):
            if value.get(key):
                properties["zoning"] = value[key]
                break
    return properties


# How far a plan label may sit from the feature it annotates, as a real-world
# distance rather than a bare coordinate count: ten feet, the working figure this
# linking has always used, expressed in metres so it can be converted into whatever
# unit a given project's coordinates are in.
LABEL_LINK_MAX_DISTANCE_METERS = 10 * 0.3048

# Fallback size of one coordinate unit when the project declares no usable CRS to
# read it from. Mirrors the unit systems accepted by ProjectCreate.
METERS_PER_UNIT_SYSTEM = {"imperial": 0.3048, "metric": 1.0}
DEFAULT_METERS_PER_UNIT = METERS_PER_UNIT_SYSTEM["imperial"]


def _label_link_max_distance(project: Project) -> float:
    """The label-linking cutoff in the project's own coordinate units.

    Taken from the project's CRS when it has one, since that states exactly how
    long a coordinate unit is; otherwise from its declared unit system. A
    foot-based project keeps the ten-unit cutoff it had before this was made
    unit-aware, while a metre-based project gets 3.048 units instead of ten.
    """
    meters_per_unit = crs_linear_unit_meters(project.coordinate_reference_system)
    if meters_per_unit is None:
        meters_per_unit = METERS_PER_UNIT_SYSTEM.get(
            (project.default_unit_system or "").lower(), DEFAULT_METERS_PER_UNIT
        )
    return LABEL_LINK_MAX_DISTANCE_METERS / meters_per_unit


def _link_labels_to_nearby_geometry(entities: list[SiteModelEntity], project: Project) -> None:
    geometries = [
        (entity, shape(entity.geometry))
        for entity in entities
        if entity.validation_status == "valid" and entity.geometry
    ]
    if not geometries:
        return
    max_distance = _label_link_max_distance(project)
    for entity in entities:
        if entity.entity_type != "text":
            continue
        location = (entity.properties or {}).get("location")
        if not isinstance(location, list) or len(location) < 2:
            continue
        label_point = Point(location[0], location[1])
        nearest_entity, nearest_distance = min(
            ((candidate, label_point.distance(geometry)) for candidate, geometry in geometries),
            key=lambda pair: pair[1],
        )
        if nearest_distance > max_distance:
            continue
        entity.properties = {
            **(entity.properties or {}),
            "linked_geometry": {
                "entity_id": nearest_entity.id,
                "entity_type": nearest_entity.entity_type,
                "distance": round(nearest_distance, 4),
                "source_reference": nearest_entity.source_reference,
            },
        }


def _table_row_point(row: dict[str, Any]) -> list[float] | None:
    def find_value(names: tuple[str, ...]) -> float | None:
        for key, value in row.items():
            if key.strip().lower() in names:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
        return None

    x = find_value(("x", "easting", "longitude", "lon"))
    y = find_value(("y", "northing", "latitude", "lat"))
    if x is None or y is None:
        return None
    z = find_value(("elevation", "z"))
    return [x, y, z] if z is not None else [x, y]


@router.get(
    "/projects/{project_id}/site-model/revisions",
    response_model=list[SiteModelRevisionResponse],
)
def list_site_model_revisions(
    project_id: str,
    database: Session = Depends(get_db),
    _project: Project = Depends(require_project_member),
) -> list[ProjectRevision]:
    revisions = list(
        database.scalars(
            select(ProjectRevision)
            .where(ProjectRevision.project_id == project_id)
            .order_by(ProjectRevision.revision_number.desc())
        )
    )
    active_jobs = set(
        database.scalars(
            select(ProcessingJob.id)
            .join(SourceFile, SourceFile.id == ProcessingJob.source_file_id)
            .where(SourceFile.project_id == project_id, SourceFile.deleted_at.is_(None))
        )
    )
    return [
        revision
        for revision in revisions
        if any(job_id in active_jobs for job_id in (revision.source_job_ids or []))
    ]


@router.get(
    "/projects/{project_id}/site-model/revisions/{revision_id}/entities",
    response_model=list[SiteModelEntityResponse],
)
def list_site_model_entities(
    project_id: str,
    revision_id: str,
    limit: int = 500,
    offset: int = 0,
    database: Session = Depends(get_db),
    _project: Project = Depends(require_project_member),
) -> list[SiteModelEntity]:
    limit = max(1, min(limit, 2000))
    offset = max(0, offset)
    revision = database.scalar(
        select(ProjectRevision).where(
            ProjectRevision.id == revision_id, ProjectRevision.project_id == project_id
        )
    )
    if revision is None:
        raise HTTPException(status_code=404, detail="Site-model revision not found")
    active_job = database.scalar(
        select(ProcessingJob.id)
        .join(SourceFile, SourceFile.id == ProcessingJob.source_file_id)
        .where(
            ProcessingJob.id.in_(revision.source_job_ids or []),
            SourceFile.project_id == project_id,
            SourceFile.deleted_at.is_(None),
        )
    )
    if active_job is None:
        raise HTTPException(status_code=404, detail="Site-model revision is archived")
    statement = (
        select(SiteModelEntity)
        .where(SiteModelEntity.revision_id == revision_id)
        .order_by(SiteModelEntity.id)
        .limit(limit)
        .offset(offset)
    )
    return list(database.scalars(statement))


@router.get("/projects/{project_id}/site-model/entities/{entity_id}/snippet")
def get_entity_plan_snippet(
    project_id: str,
    entity_id: str,
    database: Session = Depends(get_db),
    _project: Project = Depends(require_project_member),
) -> Response:
    entity = database.scalar(
        select(SiteModelEntity)
        .join(ProjectRevision, ProjectRevision.id == SiteModelEntity.revision_id)
        .where(SiteModelEntity.id == entity_id, ProjectRevision.project_id == project_id)
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Site-model entity not found")
    source = entity.source_reference or {}
    file_name = source.get("file_name")
    source_entity_id = source.get("entity_id")
    if not file_name or not str(file_name).lower().endswith(".dxf") or source_entity_id is None:
        raise HTTPException(
            status_code=400,
            detail="Plan-sheet snippets are only available for DXF-sourced entities",
        )
    source_file = database.scalar(
        select(SourceFile).where(
            SourceFile.project_id == project_id,
            SourceFile.original_name == file_name,
            SourceFile.deleted_at.is_(None),
        )
    )
    if source_file is None:
        raise HTTPException(status_code=404, detail="Source DXF file not found")
    try:
        svg = render_dxf_snippet(Path(source_file.stored_path), str(source_entity_id))
    except PlanSnippetError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/projects/{project_id}/site-model/revisions/{revision_id}/compare/{other_revision_id}")
def compare_site_model_revisions(
    project_id: str,
    revision_id: str,
    other_revision_id: str,
    database: Session = Depends(get_db),
    _project: Project = Depends(require_project_member),
) -> dict[str, list[dict[str, Any]]]:
    revisions = database.scalars(
        select(ProjectRevision).where(
            ProjectRevision.project_id == project_id,
            ProjectRevision.id.in_([revision_id, other_revision_id]),
        )
    ).all()
    if len(revisions) != 2:
        raise HTTPException(status_code=404, detail="Both site-model revisions are required")
    entities = database.scalars(
        select(SiteModelEntity).where(
            SiteModelEntity.revision_id.in_([revision_id, other_revision_id])
        )
    ).all()
    first = {entity.id: entity for entity in entities if entity.revision_id == revision_id}
    second = {entity.id: entity for entity in entities if entity.revision_id == other_revision_id}
    added = [second[key].__dict__ for key in second.keys() - first.keys()]
    removed = [first[key].__dict__ for key in first.keys() - second.keys()]
    changed = [
        {"before": first[key].__dict__, "after": second[key].__dict__}
        for key in first.keys() & second.keys()
        if first[key].geometry != second[key].geometry
        or first[key].properties != second[key].properties
    ]
    for item in added + removed + changed:
        item.pop("_sa_instance_state", None)
    return {"added": added, "removed": removed, "changed": changed}


# Calculation types whose formulas are Euclidean and therefore need projected
# coordinates. Slope and elevation statistics work on supplied numbers rather than
# on coordinate positions, so they are unaffected by a geographic CRS.
PLANAR_CALCULATION_TYPES = frozenset({"distance", "area", "perimeter"})


@router.post(
    "/projects/{project_id}/calculations",
    response_model=CalculationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_calculation(
    project_id: str,
    payload: CalculationRequest,
    database: Session = Depends(get_db),
    project: Project = Depends(require_project_member),
) -> CalculationResult:
    if payload.revision_id is not None:
        revision = database.scalar(
            select(ProjectRevision).where(
                ProjectRevision.id == payload.revision_id,
                ProjectRevision.project_id == project_id,
            )
        )
        if revision is None:
            raise HTTPException(status_code=404, detail="Site-model revision not found")
    if payload.calculation_type in PLANAR_CALCULATION_TYPES and is_geographic_crs(
        project.coordinate_reference_system
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"This project's coordinate reference system "
                f"({project.coordinate_reference_system}) is geographic (lat/lon degrees); "
                f"{payload.calculation_type} is measured on a plane and would be meaningless. "
                "Set a projected CRS for the project first."
            ),
        )
    try:
        if payload.calculation_type == "distance":
            result = calculate_distance(
                cast(dict[str, Any], payload.inputs["first_geometry"]),
                cast(dict[str, Any], payload.inputs["second_geometry"]),
                payload.coordinate_unit,
                payload.unit,
            )
        elif payload.calculation_type == "area":
            result = calculate_area(
                cast(dict[str, Any], payload.inputs["geometry"]),
                payload.coordinate_unit,
                payload.unit,
            )
        elif payload.calculation_type == "perimeter":
            result = calculate_perimeter(
                cast(dict[str, Any], payload.inputs["geometry"]),
                payload.coordinate_unit,
                payload.unit,
            )
        else:
            if payload.calculation_type == "elevation":
                result = calculate_elevation_statistics(
                    [float(value) for value in cast(list[Any], payload.inputs["elevations"])],
                    payload.unit,
                )
            else:
                result = calculate_slope(
                    float(cast(Any, payload.inputs["start_elevation"])),
                    float(cast(Any, payload.inputs["end_elevation"])),
                    float(cast(Any, payload.inputs["horizontal_distance"])),
                    payload.unit,
                )
    except (CalculationError, KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    calculation = CalculationResult(
        project_id=project.id,
        revision_id=payload.revision_id,
        calculation_type=payload.calculation_type,
        input_entity_ids=payload.source_entity_ids,
        inputs=result["inputs"],
        formula=result["formula"],
        result=result["result"],
        unit=result["unit"],
        assumptions=result["assumptions"],
        details=result.get("statistics"),
    )
    database.add(calculation)
    database.commit()
    database.refresh(calculation)
    return calculation


@router.get("/projects/{project_id}/calculations", response_model=list[CalculationResponse])
def list_calculations(
    project_id: str,
    database: Session = Depends(get_db),
    _project: Project = Depends(require_project_member),
) -> list[CalculationResult]:
    return list(
        database.scalars(
            select(CalculationResult)
            .where(CalculationResult.project_id == project_id)
            .order_by(CalculationResult.created_at.desc())
        )
    )


@router.get(
    "/projects/{project_id}/calculations/{calculation_id}", response_model=CalculationResponse
)
def read_calculation(
    project_id: str,
    calculation_id: str,
    database: Session = Depends(get_db),
    _project: Project = Depends(require_project_member),
) -> CalculationResult:
    calculation = database.scalar(
        select(CalculationResult).where(
            CalculationResult.id == calculation_id,
            CalculationResult.project_id == project_id,
        )
    )
    if calculation is None:
        raise HTTPException(status_code=404, detail="Calculation not found")
    return calculation


def _entity_payload(entity: SiteModelEntity) -> dict[str, Any]:
    return {
        "entity_type": entity.entity_type,
        "geometry": entity.geometry,
        "properties": entity.properties,
        "validation_status": entity.validation_status,
        "source_reference": entity.source_reference,
    }


def _resolve_revision_ids(
    project_id: str, requested: list[str] | None, database: Session
) -> list[str]:
    """Resolve which revisions to draw on: the explicitly requested ones, or
    (by default) the project boundary — the single latest revision for each
    distinct document lineage (document_group_id), so an older, superseded
    version of a re-uploaded file never contributes alongside its replacement.
    """
    if requested:
        # Scoped to this project, not returned as-is: `require_project_member`
        # only checks membership on `project_id`, so an id belonging to a
        # different project the caller has no relationship to would otherwise
        # pull that project's site-model entities into this project's
        # summary/question answer -- and persist them there. An id that
        # doesn't belong here is silently dropped rather than erroring, the
        # same as a stale/nonexistent id already would be.
        return list(
            database.scalars(
                select(ProjectRevision.id).where(
                    ProjectRevision.id.in_(requested), ProjectRevision.project_id == project_id
                )
            )
        )
    revisions = list(
        database.scalars(select(ProjectRevision).where(ProjectRevision.project_id == project_id))
    )
    job_ids = [revision.source_job_ids[0] for revision in revisions if revision.source_job_ids]
    jobs = (
        {
            job.id: job
            for job in database.scalars(select(ProcessingJob).where(ProcessingJob.id.in_(job_ids)))
        }
        if job_ids
        else {}
    )
    file_ids = {job.source_file_id for job in jobs.values()}
    files = (
        {
            file.id: file
            for file in database.scalars(
                select(SourceFile).where(
                    SourceFile.id.in_(file_ids), SourceFile.deleted_at.is_(None)
                )
            )
        }
        if file_ids
        else {}
    )
    latest_by_group: dict[str, ProjectRevision] = {}
    for revision in revisions:
        if not revision.source_job_ids:
            continue
        job = jobs.get(revision.source_job_ids[0])
        source_file = files.get(job.source_file_id) if job else None
        if source_file is None:
            continue
        group_id = source_file.document_group_id
        current = latest_by_group.get(group_id)
        # revision_number is unique and strictly increasing per project (see the
        # 0010 migration), so it's a reliable tiebreaker where created_at alone
        # can tie at second-level timestamp resolution.
        if current is None or revision.revision_number > current.revision_number:
            latest_by_group[group_id] = revision
    return [revision.id for revision in latest_by_group.values()]


@router.post("/projects/{project_id}/summaries", response_model=SummaryResponse)
def create_summary(
    project_id: str,
    revision_ids: list[str] | None = None,
    database: Session = Depends(get_db),
    project: Project = Depends(require_project_member),
) -> ProjectSummary:
    resolved_ids = _resolve_revision_ids(project_id, revision_ids, database)
    entities = []
    warnings: list[str] = []
    if resolved_ids:
        entities = list(
            database.scalars(
                select(SiteModelEntity).where(SiteModelEntity.revision_id.in_(resolved_ids))
            )
        )
        warnings = [
            entity.validation_status for entity in entities if entity.validation_status != "valid"
        ]
    entities_payload = [_entity_payload(entity) for entity in entities]
    content = MockAIProvider().summarize(
        {
            "entities": entities_payload,
            "warnings": warnings,
            "coordinate_reference_system": project.coordinate_reference_system,
        }
    )
    summary = ProjectSummary(
        project_id=project_id, revision_ids=resolved_ids or None, content=content
    )
    database.add(summary)
    database.commit()
    database.refresh(summary)
    return summary


@router.get("/projects/{project_id}/summaries", response_model=list[SummaryResponse])
def list_summaries(
    project_id: str,
    database: Session = Depends(get_db),
    _project: Project = Depends(require_project_member),
) -> list[ProjectSummary]:
    return list(
        database.scalars(
            select(ProjectSummary)
            .where(ProjectSummary.project_id == project_id)
            .order_by(ProjectSummary.created_at.desc())
        )
    )


@router.post("/projects/{project_id}/questions", response_model=QuestionResponse)
def ask_question(
    project_id: str,
    payload: QuestionRequest,
    database: Session = Depends(get_db),
    project: Project = Depends(require_project_member),
) -> QuestionAnswer:
    intent = route_question(payload.question)
    resolved_ids = _resolve_revision_ids(project_id, payload.revision_ids, database)
    entities_payload: list[dict[str, Any]] = []
    if resolved_ids:
        entities = list(
            database.scalars(
                select(SiteModelEntity).where(SiteModelEntity.revision_id.in_(resolved_ids))
            )
        )
        entities_payload = [_entity_payload(entity) for entity in entities]
    answer = MockAIProvider().answer(
        payload.question,
        {
            "entities": entities_payload,
            "intent": intent,
            "coordinate_reference_system": project.coordinate_reference_system,
        },
    )
    question = QuestionAnswer(
        project_id=project_id,
        revision_ids=resolved_ids or None,
        question=payload.question,
        intent=intent,
        answer=answer,
    )
    database.add(question)
    database.commit()
    database.refresh(question)
    return question
