# Data Model

## Modeling Rules

- Store all source references with extracted and calculated data.
- Store units and coordinate reference information explicitly.
- Treat processed output as versioned project data.
- Do not overwrite source files when reprocessing them.
- Keep calculated results reproducible from recorded inputs.

## Initial Entities

### Tenant

Added in Phase 16 (schema/bootstrap only — see DECISIONS.md ADR-010,
RISK_REGISTER.md). The isolation boundary for a hybrid deployment model: a
dedicated single-customer install (whether the customer's own infrastructure
or vendor-operated) has exactly one row, created automatically at bootstrap;
a vendor-operated instance shared across several subscribing customers has
one row per customer. `User`, `Client`, and `Project` each carry a nullable
`tenant_id`. Nothing yet reads or enforces it on any query.

- `id`
- `name`
- `created_at`
- `updated_at`

### Client

- `id`
- `tenant_id` (nullable; see Tenant above)
- `name`
- `created_at`
- `updated_at`
- `archived_at`

### Project

- `id`
- `client_id`
- `tenant_id` (nullable; see Tenant above)
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
- `deleted_at`
- `archived_path`
- `status_before_delete`
- `document_group_id`
- `superseded_by_id`

`document_group_id` identifies the logical document lineage a file belongs to — a newly uploaded file is the only member of its own group (`document_group_id == id`). `POST .../files/{file_id}/replace` uploads a new file sharing the original's `document_group_id` and sets the original's `superseded_by_id` to the new file's id, recording it as an explicit new version of the same document rather than an unrelated file that happens to share a name. A file with `superseded_by_id` set cannot be replaced again until its replacement is.

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

### ExtractedDocument

- `id`
- `processing_job_id`
- `source_file_id`
- `revision_number`
- `parser_name`
- `content`
- `warnings`
- `created_at`

`content` is the full normalized document (text, items, warnings, metadata) that a parser produced, stored as JSON. This is what `POST .../site-model/revisions/from-extraction/{file_id}` reads to build `SiteModelEntity` rows for a revision.

`(source_file_id, revision_number)` is unique at the database level, the same guarantee `ProjectRevision` has below — reprocessing a file (e.g. via "Retry") assigns the next `revision_number` for that file rather than leaving it at a fixed value, so which extraction is "latest" is never ambiguous.

### ProjectRevision

- `id`
- `project_id`
- `revision_number`
- `created_at`
- `created_by`
- `source_job_ids`
- `notes`

`(project_id, revision_number)` is unique at the database level, so two revisions accepted concurrently in the same project can't be assigned the same number; the accept endpoint retries with a fresh number on conflict.

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
- `created_at`

`entity_type` is the geometric/structural kind an extraction produced: `point`, `line`, `text`, `table`, `key_phrase`, `cogo_line`, or a lowercased raw DXF entity type (e.g. `lwpolyline`, `dimension`). It is not a civil-engineering role.

That role lives in `properties.semantic_type` instead, added in Phase 9: `parcel_boundary`, `building_footprint`, `driveway_road`, or `curb_cut`, inferred from a DXF layer name or an explicit CSV type/classification column (see RISK_REGISTER.md). `properties` also carries item-specific data depending on `entity_type` — a CSV/LandXML/DXF geometry's raw coordinates; `phrase`/`context` for a `key_phrase`; `bearing`/`distance` for a `cogo_line`; an optional `zoning` tag passed through from a CSV column; and, for a DXF label with a location, an optional `linked_geometry` object (target entity id, type, distance, and that target's own `source_reference`) recording a Phase 9 proximity link to nearby geometry.

`confidence` exists on the column but is not currently set by any parser or acceptance path; it is always `null` today.

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
- `details`
- `created_at`

### ProjectSummary

- `id`
- `project_id`
- `revision_ids`
- `content`
- `created_at`

`content` is the structured summary returned by the AI provider (`summary`, `grading`, `drainage`, `utilities`, `attention_flags`, `limitations`), stored as JSON.

`revision_ids` is a JSON list, not a single foreign key. If the request doesn't name specific revisions, it's resolved at request time to the project-boundary default — the single latest revision for each distinct document lineage (`SourceFile.document_group_id`), so a superseded (replaced) file's older revision is excluded automatically. The resolved list is stored, not a live reference, so a past summary's provenance doesn't change as new revisions are accepted later.

### QuestionAnswer

- `id`
- `project_id`
- `revision_ids`
- `question`
- `intent`
- `answer`
- `created_at`

`revision_ids` follows the same project-boundary resolution and storage rule as `ProjectSummary.revision_ids` above.

`answer` is the full response returned by the AI provider, stored as JSON — it includes the answer text, method, result/unit where applicable, `source_references`, `limitations`, and `confidence`. These are not separate columns.

## Relationships

```text
Client 1 -- many Project
Project 1 -- many SourceFile
SourceFile 1 -- many ProcessingJob
ProcessingJob 1 -- 1 ExtractedDocument
Project 1 -- many ProjectRevision
ProjectRevision 1 -- many SiteModelEntity
ProjectRevision 1 -- many CalculationResult
ProjectRevision many -- many ProjectSummary   (via ProjectSummary.revision_ids, a JSON list)
ProjectRevision many -- many QuestionAnswer   (via QuestionAnswer.revision_ids, a JSON list)
SourceFile 1 -- 1 SourceFile                  (superseded_by_id, optional: the file that replaced it)
```

## Resolved Modeling Questions

- **Geometry column type:** plain `JSON` (GeoJSON-like dicts), not a native PostGIS geometry/geography type; there are no spatial indexes. Spatial operations run in application code via Shapely, not in the database.
- **Normalized extraction storage:** stored in the database, as `ExtractedDocument.content` (JSON), not in file storage.
- **Confidence and validation-status values:** `validation_status` is one of `valid`, `invalid`, or `unmapped`. `confidence` is not currently populated by any parser or acceptance path (always `null`).
- **Retention and deletion rules for source files:** archive (soft-delete, preserves checksum/metadata), restore, and permanent purge are implemented (Phase 6); see API.md's Files and Processing section.
- **Revision merge behavior when several files contribute to one site model:** each `ProjectRevision` still comes from exactly one extraction/file — revisions themselves are never merged. Instead, `ProjectSummary`/`QuestionAnswer` read across multiple revisions at query time via `revision_ids` (see those entities above), defaulting to one revision per document lineage across the whole project.

## Open Modeling Questions

- Which projected coordinate reference systems to support explicitly. Whether a geographic (lat/lon) CRS should be rejected is settled: it is (see RISK_REGISTER.md) — a project cannot adopt one, and planar measurements are refused for any project that already carries one.
- Query-level `Tenant` scoping is enforced, `User.username` is unique per `(tenant_id, username)` rather than globally (with a new globally-unique `email` column added as the login identifier — migration `0020_add_user_email_tenant_scoped_username`), Postgres Row-Level Security is written on `Project`/`Client` as a database-enforced backstop (migration `0021_add_row_level_security`, **unverified against a real Postgres instance**), and a tenant-provisioning API (`POST`/`GET /tenants`) exists (all 2026-09-20 — see RISK_REGISTER.md and PLAN.md Phase 16). Still open: extending Row-Level Security to tables nested under `Project`, and to `User` itself (a bootstrapping paradox — see migration `0021`'s docstring).
- `User`, `Session`, and `ProjectMembership` (added in Phase 15) are not yet documented in "Initial Entities" above — a pre-existing gap noted here rather than backfilled in this pass.
