from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from civil_engineering.ai_service import MockAIProvider, route_question
from civil_engineering.calculations import (
    CalculationError,
    calculate_area,
    calculate_distance,
    calculate_elevation_statistics,
    calculate_perimeter,
    calculate_slope,
)
from civil_engineering.database import get_db
from civil_engineering.extraction import ExtractionError, parse_file
from civil_engineering.models import (
    CalculationResult,
    Client,
    ExtractedDocument,
    ProcessingJob,
    Project,
    ProjectRevision,
    ProjectSummary,
    QuestionAnswer,
    SiteModelEntity,
    SourceFile,
    new_id,
)
from civil_engineering.schemas import (
    CalculationRequest,
    CalculationResponse,
    ClientCreate,
    ClientResponse,
    ClientUpdate,
    ExtractedDocumentResponse,
    ProcessingJobResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    QuestionRequest,
    QuestionResponse,
    SiteModelEntityResponse,
    SiteModelRevisionResponse,
    SourceFileResponse,
    SummaryResponse,
)
from civil_engineering.site_model import SiteModelError, normalize_geometry
from civil_engineering.storage import (
    FileValidationError,
    archive_file,
    remove_file,
    restore_file,
    save_upload,
)

router = APIRouter()


def get_client_or_404(client_id: str, database: Session) -> Client:
    client = database.get(Client, client_id)
    if client is None or client.archived_at is not None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def get_project_or_404(project_id: str, database: Session) -> Project:
    project = database.get(Project, project_id)
    if project is None or project.archived_at is not None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/clients", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
def create_client(payload: ClientCreate, database: Session = Depends(get_db)) -> Client:
    client = Client(name=payload.name)
    database.add(client)
    database.commit()
    database.refresh(client)
    return client


@router.get("/clients", response_model=list[ClientResponse])
def list_clients(database: Session = Depends(get_db)) -> list[Client]:
    statement = select(Client).where(Client.archived_at.is_(None)).order_by(Client.name)
    return list(database.scalars(statement))


@router.get("/clients/{client_id}", response_model=ClientResponse)
def read_client(client_id: str, database: Session = Depends(get_db)) -> Client:
    return get_client_or_404(client_id, database)


@router.patch("/clients/{client_id}", response_model=ClientResponse)
def update_client(
    client_id: str, payload: ClientUpdate, database: Session = Depends(get_db)
) -> Client:
    client = get_client_or_404(client_id, database)
    if payload.name is not None:
        client.name = payload.name
    database.commit()
    database.refresh(client)
    return client


@router.post("/clients/{client_id}/archive", response_model=ClientResponse)
def archive_client(client_id: str, database: Session = Depends(get_db)) -> Client:
    client = get_client_or_404(client_id, database)
    client.archived_at = datetime.now(timezone.utc)
    database.commit()
    database.refresh(client)
    return client


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, database: Session = Depends(get_db)) -> Project:
    if payload.client_id is not None:
        get_client_or_404(payload.client_id, database)
    project = Project(**payload.model_dump())
    database.add(project)
    database.commit()
    database.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(database: Session = Depends(get_db)) -> list[Project]:
    statement = select(Project).where(Project.archived_at.is_(None)).order_by(Project.name)
    return list(database.scalars(statement))


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def read_project(project_id: str, database: Session = Depends(get_db)) -> Project:
    return get_project_or_404(project_id, database)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str, payload: ProjectUpdate, database: Session = Depends(get_db)
) -> Project:
    project = get_project_or_404(project_id, database)
    values = payload.model_dump(exclude_unset=True)
    if "client_id" in values and values["client_id"] is not None:
        get_client_or_404(values["client_id"], database)
    for key, value in values.items():
        setattr(project, key, value)
    database.commit()
    database.refresh(project)
    return project


@router.post("/projects/{project_id}/archive", response_model=ProjectResponse)
def archive_project(project_id: str, database: Session = Depends(get_db)) -> Project:
    project = get_project_or_404(project_id, database)
    project.archived_at = datetime.now(timezone.utc)
    database.commit()
    database.refresh(project)
    return project


@router.post(
    "/projects/{project_id}/files",
    response_model=SourceFileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    project_id: str,
    file: UploadFile = File(...),
    database: Session = Depends(get_db),
) -> SourceFile:
    project = get_project_or_404(project_id, database)
    source_file = SourceFile(
        id=new_id(),
        project_id=project.id,
        original_name=Path(file.filename or "").name,
        stored_path="",
        media_type=file.content_type or "application/octet-stream",
        size_bytes=0,
        checksum="pending",
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
            status_code=409, detail="A file with the same content already exists in this project"
        )
    source_file.stored_path = str(path)
    source_file.size_bytes = size
    source_file.checksum = checksum
    database.add(source_file)
    database.commit()
    database.refresh(source_file)
    return source_file


@router.get("/projects/{project_id}/files", response_model=list[SourceFileResponse])
def list_files(project_id: str, database: Session = Depends(get_db)) -> list[SourceFile]:
    get_project_or_404(project_id, database)
    statement = select(SourceFile).where(
        SourceFile.project_id == project_id, SourceFile.deleted_at.is_(None)
    )
    return list(database.scalars(statement))


@router.get("/projects/{project_id}/files/{file_id}/download")
def download_file(
    project_id: str, file_id: str, database: Session = Depends(get_db)
) -> FileResponse:
    get_project_or_404(project_id, database)
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
def delete_file(project_id: str, file_id: str, database: Session = Depends(get_db)) -> None:
    get_project_or_404(project_id, database)
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
    project_id: str, file_id: str, database: Session = Depends(get_db)
) -> ProcessingJob:
    get_project_or_404(project_id, database)
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
        extraction = ExtractedDocument(
            processing_job_id=job.id,
            source_file_id=file_id,
            parser_name=normalized.parser_name,
            content=normalized.as_dict(),
            warnings=normalized.warnings,
        )
        database.add(extraction)
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.warnings = normalized.warnings
        source_file.status = "completed"
        source_file.processed_at = job.completed_at
    except (ExtractionError, OSError) as error:
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
    project_id: str, database: Session = Depends(get_db)
) -> list[ProcessingJob]:
    get_project_or_404(project_id, database)
    statement = select(ProcessingJob).where(ProcessingJob.project_id == project_id)
    return list(database.scalars(statement))


@router.get("/admin/files/archived", response_model=list[SourceFileResponse])
def list_archived_files(database: Session = Depends(get_db)) -> list[SourceFile]:
    return list(
        database.scalars(
            select(SourceFile)
            .where(SourceFile.deleted_at.is_not(None))
            .order_by(SourceFile.deleted_at.desc())
        )
    )


@router.post("/admin/files/{file_id}/restore", response_model=SourceFileResponse)
def restore_archived_file(file_id: str, database: Session = Depends(get_db)) -> SourceFile:
    source_file = database.get(SourceFile, file_id)
    if source_file is None or source_file.deleted_at is None:
        raise HTTPException(status_code=404, detail="Archived file not found")
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
def purge_archived_file(file_id: str, database: Session = Depends(get_db)) -> None:
    source_file = database.get(SourceFile, file_id)
    if source_file is None or source_file.deleted_at is None:
        raise HTTPException(status_code=404, detail="Archived file not found")
    remove_file(source_file.archived_path or source_file.stored_path)
    database.delete(source_file)
    database.commit()


@router.get("/projects/{project_id}/processing/{job_id}", response_model=ProcessingJobResponse)
def read_processing_job(
    project_id: str, job_id: str, database: Session = Depends(get_db)
) -> ProcessingJob:
    get_project_or_404(project_id, database)
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
    project_id: str, file_id: str, database: Session = Depends(get_db)
) -> ExtractedDocument:
    get_project_or_404(project_id, database)
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
) -> ProjectRevision:
    project = get_project_or_404(project_id, database)
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
    database.flush()
    table_rows: list[dict[str, Any]] = []
    text_lines: list[str] = []
    text_source: dict[str, Any] | None = None
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
            value = {"point": point}
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
            properties=value if isinstance(value, dict) else {"value": value},
            source_reference=item.get("source"),
            validation_status=validation_status,
        )
        database.add(entity)
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
    return [x, y] if x is not None and y is not None else None


@router.get(
    "/projects/{project_id}/site-model/revisions",
    response_model=list[SiteModelRevisionResponse],
)
def list_site_model_revisions(
    project_id: str, database: Session = Depends(get_db)
) -> list[ProjectRevision]:
    get_project_or_404(project_id, database)
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
) -> list[SiteModelEntity]:
    get_project_or_404(project_id, database)
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


@router.get("/projects/{project_id}/site-model/revisions/{revision_id}/compare/{other_revision_id}")
def compare_site_model_revisions(
    project_id: str,
    revision_id: str,
    other_revision_id: str,
    database: Session = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    get_project_or_404(project_id, database)
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


@router.post(
    "/projects/{project_id}/calculations",
    response_model=CalculationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_calculation(
    project_id: str,
    payload: CalculationRequest,
    database: Session = Depends(get_db),
) -> CalculationResult:
    project = get_project_or_404(project_id, database)
    if payload.revision_id is not None:
        revision = database.scalar(
            select(ProjectRevision).where(
                ProjectRevision.id == payload.revision_id,
                ProjectRevision.project_id == project_id,
            )
        )
        if revision is None:
            raise HTTPException(status_code=404, detail="Site-model revision not found")
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
    project_id: str, database: Session = Depends(get_db)
) -> list[CalculationResult]:
    get_project_or_404(project_id, database)
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
    project_id: str, calculation_id: str, database: Session = Depends(get_db)
) -> CalculationResult:
    get_project_or_404(project_id, database)
    calculation = database.scalar(
        select(CalculationResult).where(
            CalculationResult.id == calculation_id,
            CalculationResult.project_id == project_id,
        )
    )
    if calculation is None:
        raise HTTPException(status_code=404, detail="Calculation not found")
    return calculation


@router.post("/projects/{project_id}/summaries", response_model=SummaryResponse)
def create_summary(
    project_id: str, revision_id: str | None = None, database: Session = Depends(get_db)
) -> ProjectSummary:
    get_project_or_404(project_id, database)
    entities = []
    warnings = []
    if revision_id:
        entities = list(
            database.scalars(
                select(SiteModelEntity).where(SiteModelEntity.revision_id == revision_id)
            )
        )
        warnings = [
            entity.validation_status for entity in entities if entity.validation_status != "valid"
        ]
    content = MockAIProvider().summarize({"entities": entities, "warnings": warnings})
    summary = ProjectSummary(project_id=project_id, revision_id=revision_id, content=content)
    database.add(summary)
    database.commit()
    database.refresh(summary)
    return summary


@router.post("/projects/{project_id}/questions", response_model=QuestionResponse)
def ask_question(
    project_id: str, payload: QuestionRequest, database: Session = Depends(get_db)
) -> QuestionAnswer:
    get_project_or_404(project_id, database)
    intent = route_question(payload.question)
    answer = MockAIProvider().answer(payload.question, {"source_references": []})
    question = QuestionAnswer(
        project_id=project_id,
        revision_id=payload.revision_id,
        question=payload.question,
        intent=intent,
        answer=answer,
    )
    database.add(question)
    database.commit()
    database.refresh(question)
    return question
