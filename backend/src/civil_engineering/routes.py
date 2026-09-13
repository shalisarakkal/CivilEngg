from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from civil_engineering.database import get_db
from civil_engineering.extraction import ExtractionError, parse_file
from civil_engineering.models import (
    Client,
    ExtractedDocument,
    ProcessingJob,
    Project,
    SourceFile,
    new_id,
)
from civil_engineering.schemas import (
    ClientCreate,
    ClientResponse,
    ClientUpdate,
    ExtractedDocumentResponse,
    ProcessingJobResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    SourceFileResponse,
)
from civil_engineering.storage import FileValidationError, remove_file, save_upload

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
    statement = select(SourceFile).where(SourceFile.project_id == project_id)
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
    if source_file is None or not Path(source_file.stored_path).is_file():
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
    remove_file(source_file.stored_path)
    database.delete(source_file)
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
