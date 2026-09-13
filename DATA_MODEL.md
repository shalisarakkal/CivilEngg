# Data Model

## Modeling Rules

- Store all source references with extracted and calculated data.
- Store units and coordinate reference information explicitly.
- Treat processed output as versioned project data.
- Do not overwrite source files when reprocessing them.
- Keep calculated results reproducible from recorded inputs.

## Initial Entities

### Client

- `id`
- `name`
- `created_at`
- `updated_at`
- `archived_at`

### Project

- `id`
- `client_id`
- `name`
- `description`
- `default_unit_system`
- `coordinate_reference_system`
- `created_at`
- `updated_at`
- `archived_at`

### SourceFile

- `id`
- `project_id`
- `original_name`
- `stored_path`
- `media_type`
- `size_bytes`
- `checksum`
- `status`
- `uploaded_at`
- `processed_at`
- `error_message`

### ProcessingJob

- `id`
- `project_id`
- `source_file_id`
- `status`
- `parser_name`
- `started_at`
- `completed_at`
- `warnings`
- `error_message`

### ProjectRevision

- `id`
- `project_id`
- `revision_number`
- `created_at`
- `created_by`
- `source_job_ids`
- `notes`

### SiteModelEntity

- `id`
- `revision_id`
- `entity_type`
- `geometry`
- `properties`
- `unit`
- `elevation`
- `source_reference`
- `confidence`
- `validation_status`

Initial entity types include parcel, structure, road, driveway, utility, contour, point, elevation, annotation, and drainage path.

### CalculationResult

- `id`
- `project_id`
- `revision_id`
- `calculation_type`
- `input_entity_ids`
- `inputs`
- `formula`
- `result`
- `unit`
- `assumptions`
- `created_at`

### QuestionAnswer

- `id`
- `project_id`
- `revision_id`
- `question`
- `intent`
- `answer`
- `calculation_result_id`
- `source_references`
- `limitations`
- `provider`
- `created_at`

## Relationships

```text
Client 1 -- many Project
Project 1 -- many SourceFile
SourceFile 1 -- many ProcessingJob
Project 1 -- many ProjectRevision
ProjectRevision 1 -- many SiteModelEntity
ProjectRevision 1 -- many CalculationResult
ProjectRevision 1 -- many QuestionAnswer
```

## Open Modeling Questions

- Final geometry column types and spatial indexes
- Whether raw normalized extraction is stored in PostgreSQL or file storage
- Exact confidence and validation-status values
- Revision merge behavior when several files contribute to one site model
- Retention and deletion rules for source files
