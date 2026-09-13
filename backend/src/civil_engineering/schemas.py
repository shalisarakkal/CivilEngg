from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)


class ClientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    client_id: str | None = None
    description: str | None = None
    default_unit_system: str = Field(default="imperial", max_length=32)
    coordinate_reference_system: str | None = Field(default=None, max_length=100)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    client_id: str | None = None
    description: str | None = None
    default_unit_system: str | None = Field(default=None, max_length=32)
    coordinate_reference_system: str | None = Field(default=None, max_length=100)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str | None
    name: str
    description: str | None
    default_unit_system: str
    coordinate_reference_system: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class SourceFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    original_name: str
    media_type: str
    size_bytes: int
    checksum: str
    status: str
    uploaded_at: datetime
    processed_at: datetime | None
    error_message: str | None


class ProcessingJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    source_file_id: str
    status: str
    parser_name: str | None
    started_at: datetime | None
    completed_at: datetime | None
    warnings: list[object] | None
    error_message: str | None


class ExtractedDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    processing_job_id: str
    source_file_id: str
    revision_number: int
    parser_name: str
    content: dict[str, object]
    warnings: list[object] | None
    created_at: datetime
