from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from civil_engineering.database import Base


def new_id() -> str:
    return str(uuid4())


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    projects: Mapped[list["Project"]] = relationship(back_populates="client")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    default_unit_system: Mapped[str] = mapped_column(String(32), nullable=False, default="imperial")
    coordinate_reference_system: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    client: Mapped[Client | None] = relationship(back_populates="projects")
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


class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    media_type: Mapped[str] = mapped_column(String(150), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

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
    revision_number: Mapped[int] = mapped_column(nullable=False, default=1)
    parser_name: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list[Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    processing_job: Mapped[ProcessingJob] = relationship(back_populates="extraction")


class ProjectRevision(Base):
    __tablename__ = "project_revisions"

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
        ForeignKey("project_revisions.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    geometry: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    properties: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    unit: Mapped[str | None] = mapped_column(String(32))
    elevation: Mapped[float | None] = mapped_column()
    source_reference: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    confidence: Mapped[float | None] = mapped_column()
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="valid")

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="calculations")
