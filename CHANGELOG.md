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

### Planned

- Project scaffolding and local development commands.
- Project, client, file, and processing-job models.
- Initial document extraction and processing-state transitions.
