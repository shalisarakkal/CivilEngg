# Changelog

All notable project changes will be recorded here. Entries should describe user-visible or architecture-relevant changes.

## Unreleased

### Added

- Initial development plan with phased work items and exit criteria.
- Initial project documentation set.
- MVP scope centered on local file ingestion, site-model creation, deterministic measurements, and source-grounded answers.
- Phase 2 client and project CRUD API.
- Local PDF, DXF, CSV, and TXT upload storage with size/type validation and SHA-256 duplicate detection.
- Source-file download, deletion, and queued processing-job API workflows.
- Project/file workspace UI and PostgreSQL-backed Phase 2 smoke-test coverage.
- Normalized TXT, CSV, PDF, and DXF extraction with source references and warnings.
- Versioned extracted-document storage and completed/failed processing statuses.
- TIFF/TIF upload support with raster metadata extraction; OCR remains deferred.
- Initial site-model revisions with Shapely validation, PyProj transformation support, and read APIs.
- Deterministic distance, area, perimeter, and slope calculations with persisted provenance.
- Phase 6 workspace controls for file deletion, site-model revision inspection, and calculation forms/results.
- Explicit geometry coordinate units for calculations, preventing unintended meter-to-feet conversion.
- Native Circle geometry support for area and perimeter calculations.
- Phase 6 idempotent revision acceptance and soft-delete file archiving with in-app confirmation.
- Phase 6 admin archive restore/purge, revision comparison, elevation statistics, and geometry preview.
- Phase 7 deterministic/mock source-grounded summaries and question-answer persistence.
- CSV site-model acceptance now aggregates non-geometric table rows and maps coordinate rows to points instead of creating one unmapped entity per row.
- TXT site-model acceptance now aggregates text lines into one text entity with line count and sample lines.

### Planned

- Project scaffolding and local development commands.
- Project, client, file, and processing-job models.
- Initial document extraction and processing-state transitions.
