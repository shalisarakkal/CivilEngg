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
    # Only meaningful when the caller is an admin (must name a power_user);
    # a power_user caller always becomes owner of their own new project and
    # this field is ignored for them. See create_project in routes.py.
    owner_id: str | None = None


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
    owner_id: str | None
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
    deleted_at: datetime | None
    document_group_id: str
    superseded_by_id: str | None


class ArchivedProjectResponse(ProjectResponse):
    # When this project will be automatically, permanently purged if nobody
    # restores or manually purges it first.
    purge_scheduled_at: datetime
    # True once purge_scheduled_at is within the configured warning window.
    purge_warning: bool


class ArchivedSourceFileResponse(SourceFileResponse):
    purge_scheduled_at: datetime
    purge_warning: bool


class PurgeHistoryEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    resource_type: str
    resource_id: str
    resource_name: str
    project_id: str | None
    archived_at: datetime | None
    purge_reason: str
    purged_at: datetime
    purged_by_user_id: str | None


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


class SiteModelEntityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    revision_id: str
    entity_type: str
    geometry: dict[str, object] | None
    properties: dict[str, object] | None
    unit: str | None
    elevation: float | None
    source_reference: dict[str, object] | None
    confidence: float | None
    validation_status: str
    created_at: datetime


class SiteModelRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    revision_number: int
    created_at: datetime
    created_by: str | None
    source_job_ids: list[object] | None
    notes: str | None


class CalculationRequest(BaseModel):
    calculation_type: str = Field(pattern="^(distance|area|perimeter|slope|elevation)$")
    inputs: dict[str, object]
    coordinate_unit: str = Field(default="m", max_length=32)
    unit: str = Field(default="m", max_length=32)
    revision_id: str | None = None
    source_entity_ids: list[str] = Field(default_factory=list)


class CalculationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    revision_id: str | None
    calculation_type: str
    input_entity_ids: list[object] | None
    inputs: dict[str, object]
    formula: str
    result: float
    unit: str
    assumptions: list[object] | None
    details: dict[str, object] | None
    created_at: datetime


class SummaryResponse(BaseModel):
    id: str
    project_id: str
    revision_ids: list[str] | None
    content: dict[str, object]
    created_at: datetime


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    revision_ids: list[str] | None = None


class QuestionResponse(BaseModel):
    id: str
    project_id: str
    revision_ids: list[str] | None
    question: str
    intent: str
    answer: dict[str, object]
    created_at: datetime


ROLE_PATTERN = "^(platform_admin|admin|power_user|user)$"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8)
    role: str = Field(default="user", pattern=ROLE_PATTERN)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class UserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern=ROLE_PATTERN)
    password: str | None = Field(default=None, min_length=8)
    disabled: bool | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    role: str
    created_at: datetime
    updated_at: datetime
    disabled_at: datetime | None


class ProjectMembershipCreate(BaseModel):
    user_id: str


class ProjectMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    user_id: str
    username: str
    role: str
    created_at: datetime


class ProjectOwnerUpdate(BaseModel):
    owner_id: str
