from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from civil_engineering.database import Base


def new_id() -> str:
    return str(uuid4())


class Tenant(Base):
    """The isolation boundary for the hybrid deployment model of DECISIONS.md
    ADR-010 (Phase 16): a dedicated, single-customer install has exactly one
    Tenant row, created automatically at bootstrap and never seen by that
    customer (see create_sysadmin.py); a shared instance serving several
    subscribing customers has one Tenant row per customer. Schema only for
    now -- nothing yet reads or enforces tenant_id on any query, and no route
    exists to create, list, or manage a Tenant. See RISK_REGISTER.md and
    PLAN.md Phase 16 for what's deliberately not built yet.
    """

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # Nullable, not yet enforced -- see Tenant's docstring. ondelete="SET NULL"
    # (matching Project.client_id below) rather than leaving a delete to fail,
    # even though nothing deletes a Tenant today.
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant | None] = relationship()
    projects: Mapped[list["Project"]] = relationship(back_populates="client")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    # Nullable, not yet enforced -- see Tenant's docstring.
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    default_unit_system: Mapped[str] = mapped_column(String(32), nullable=False, default="imperial")
    coordinate_reference_system: Mapped[str | None] = mapped_column(String(100))
    # Nullable at the DB level even though every project should have an owner:
    # existing rows predate the users table, and no user exists yet at
    # migration time to backfill onto. Enforced as required for new projects
    # at the schema/route layer instead (see create_project in routes.py).
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    client: Mapped[Client | None] = relationship(back_populates="projects")
    tenant: Mapped[Tenant | None] = relationship()
    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_id])
    source_files: Mapped[list["SourceFile"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    processing_jobs: Mapped[list["ProcessingJob"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    revisions: Mapped[list["ProjectRevision"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    calculations: Mapped[list["CalculationResult"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    memberships: Mapped[list["ProjectMembership"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class SourceFile(Base):
    __tablename__ = "source_files"
    __table_args__ = (
        UniqueConstraint("project_id", "checksum", name="uq_source_files_project_checksum"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    media_type: Mapped[str] = mapped_column(String(150), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_path: Mapped[str | None] = mapped_column(String(1000))
    status_before_delete: Mapped[str | None] = mapped_column(String(32))
    # Identifies the logical document lineage this file belongs to. A newly
    # uploaded file is the only member of its own group (document_group_id ==
    # id); an explicit "replace" creates a new file that shares the original's
    # group so the two are recognized as versions of the same document.
    document_group_id: Mapped[str] = mapped_column(String(36), nullable=False)
    superseded_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_files.id", ondelete="SET NULL")
    )

    project: Mapped[Project] = relationship(back_populates="source_files")
    processing_jobs: Mapped[list["ProcessingJob"]] = relationship(
        back_populates="source_file", cascade="all, delete-orphan"
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    parser_name: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    warnings: Mapped[list[Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="processing_jobs")
    source_file: Mapped[SourceFile] = relationship(back_populates="processing_jobs")
    extraction: Mapped["ExtractedDocument | None"] = relationship(
        back_populates="processing_job", cascade="all, delete-orphan", uselist=False
    )


class ExtractedDocument(Base):
    __tablename__ = "extracted_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    processing_job_id: Mapped[str] = mapped_column(
        ForeignKey("processing_jobs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(nullable=False)
    parser_name: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list[Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    processing_job: Mapped[ProcessingJob] = relationship(back_populates="extraction")


class ProjectRevision(Base):
    __tablename__ = "project_revisions"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "revision_number", name="uq_project_revisions_project_number"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(200))
    source_job_ids: Mapped[list[Any] | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="revisions")
    entities: Mapped[list["SiteModelEntity"]] = relationship(
        back_populates="revision", cascade="all, delete-orphan"
    )


class SiteModelEntity(Base):
    __tablename__ = "site_model_entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    geometry: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    properties: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    unit: Mapped[str | None] = mapped_column(String(32))
    elevation: Mapped[float | None] = mapped_column()
    source_reference: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    confidence: Mapped[float | None] = mapped_column()
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="valid")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    revision: Mapped[ProjectRevision] = relationship(back_populates="entities")


class CalculationResult(Base):
    __tablename__ = "calculation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_revisions.id", ondelete="SET NULL")
    )
    calculation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    input_entity_ids: Mapped[list[Any] | None] = mapped_column(JSON)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[float] = mapped_column(nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    assumptions: Mapped[list[Any] | None] = mapped_column(JSON)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="calculations")


class ProjectSummary(Base):
    __tablename__ = "project_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # The revisions actually used to answer, resolved at request time: either
    # explicitly chosen, or (when none were given) the project-boundary default
    # of the latest revision per document lineage. Stored as the resolved list
    # rather than a live reference so a past answer's provenance never changes
    # as new revisions are accepted later.
    revision_ids: Mapped[list[Any] | None] = mapped_column(JSON)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionAnswer(Base):
    __tablename__ = "question_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    revision_ids: Mapped[list[Any] | None] = mapped_column(JSON)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String(32), nullable=False)
    answer: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActivityEvent(Base):
    """A persisted record of a notable action taken within a project --
    Phase 12's audit trail. Distinct from the frontend's own session-only
    activity log (kept for instant, no-round-trip feedback): this is the
    durable copy, project-scoped and readable by any member of the project
    after the fact, including across reloads and other sessions.

    No `tenant_id` column, matching the convention already established for
    every other table nested under `Project` (source_files, calculation_results,
    etc. -- PLAN.md Phase 16, migration 0022_extend_rls_nested_tables): the
    tenant boundary is reached via `project_id`, not duplicated here, and the
    same RLS policy shape applies (see migration 0023_add_activity_events).
    """

    __tablename__ = "activity_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Mirrors the frontend's BatchResult[] shape for a multi-item action
    # (e.g. a multi-file upload/archive/accept); null for a single-outcome
    # action, matching setMessage()'s own details=null default.
    details: Mapped[list[Any] | None] = mapped_column(JSON)
    success_label: Mapped[str] = mapped_column(String(64), nullable=False, default="Successful")
    # A Python-side default, not server_default=func.now() like every other
    # created_at column in this file: an audit trail's whole point is
    # correct ordering, and several events routinely land within the same
    # request or the same UI batch -- easily within the same wall-clock
    # second. SQLite's CURRENT_TIMESTAMP (what func.now() compiles to there)
    # only has 1-second resolution, so same-second events would tie and sort
    # in an arbitrary order; datetime.now(timezone.utc) has microsecond
    # resolution on both SQLite and Postgres, which is what list_activity_
    # events' ORDER BY created_at DESC actually relies on.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    project: Mapped[Project] = relationship()
    user: Mapped["User | None"] = relationship()


class PurgeHistoryEntry(Base):
    """A permanent tombstone recording that a project or file was purged.

    Deliberately has no foreign keys to `projects`/`source_files`: by the
    time this matters, those rows are gone. This table survives them, and is
    itself pruned on its own (longer) retention schedule.
    """

    __tablename__ = "purge_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resource_type: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)
    resource_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # The owning project for a purged file; null for a purged project (its
    # own id is already resource_id).
    project_id: Mapped[str | None] = mapped_column(String(36))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_reason: Mapped[str] = mapped_column(String(32), nullable=False)
    purged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # The project's owner_id at the moment this was purged (project or file),
    # captured because that ownership row disappears along with the project
    # itself -- not literally "who clicked purge," since an automatic
    # retention sweep isn't attributable to any specific action. No FK,
    # deliberately, for the same reason this table has none to projects/
    # source_files: it must outlive the user account too if that's deleted.
    purged_by_user_id: Mapped[str | None] = mapped_column(String(36))


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # Unique per tenant, not globally (PLAN.md Phase 16): two different
    # tenants can each have their own "jsmith". Login uses `email` instead
    # (below), which stays globally unique, precisely so a login attempt is
    # never ambiguous about which tenant's same-named user is meant.
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    # Nullable at the DB level even though every new user must have one
    # (enforced in schemas.py's UserCreate, not here): existing rows predate
    # this column and have no email to backfill onto. Globally unique --
    # this is the login identifier, not username (see above).
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # platform_admin | admin | power_user | user -- validated in schemas.py,
    # not a DB enum, matching this codebase's existing string-status-field
    # convention (see SiteModelEntity.validation_status,
    # CalculationResult.calculation_type). platform_admin is a superset of
    # admin (see auth.py's ADMIN_TIER_ROLES); no dedicated install has any
    # reason to create one.
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    # Nullable, not yet enforced -- see Tenant's docstring.
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Presence signals disabled, absence signals active -- same idiom as
    # Project.archived_at/SourceFile.deleted_at rather than a new bool flag.
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant | None] = relationship()


class Session(Base):
    """A server-side session; its id is also the value stored in the cookie."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class ProjectMembership(Base):
    """Associates a user with a project beyond the project's own owner.

    Ownership itself lives on Project.owner_id (a single source of truth);
    this table is purely for additional collaborators, Power User or User.
    """

    __tablename__ = "project_memberships"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_memberships_project_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship()
