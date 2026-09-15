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
- Phase 7 grading, drainage, and utilities summary sections, plus attention flags for steep slopes, tight clearances, unusual elevation ranges, and unmapped entities.
- Deterministic distance, slope, and elevation question answering from site-model geometry, with clear ambiguous/insufficient-data responses when the required entities are not present or not uniquely identifiable.
- Source-text retrieval for explanatory answers, with prompt-injection sanitization applied to extracted document text before use.
- Phase 6 calculation-to-geometry highlighting: selecting a calculation result highlights the site-model geometry it references (switching revisions if needed) or explains when a calculation type has no associated geometry.
- Playwright browser tests covering upload, calculation, and error states, run via `npm run test:e2e`.
- Fixed `createProject`, `uploadFile`, and `createCalculation` leaving the UI permanently disabled after a network failure by adding the same try/catch/finally handling already used elsewhere; the project-creation status message now renders even before a project is selected.
- Phase 8 request correlation IDs (`X-Request-ID`), structured request logging, and a JSON error response with request id for unhandled exceptions instead of a bare "Internal Server Error" body.
- Phase 8 request-body size limit (2 MB) for non-upload endpoints, and a `/health` database-connectivity check.
- Fixed a race condition where concurrent uploads of the same file content could all succeed instead of only the first: added a database-level unique constraint on (project, checksum) and a matching migration, with the duplicate-upload response now also covering the concurrent case.
- Added a "Retry" action for files stuck in `failed` or `processing` status (e.g. after an interrupted server process), and surfaced the stored processing error message in the file list.
- Added unit tests for path-traversal and unsafe-filename rejection in local storage, and API-level tests for malformed-file processing, interrupted-job recovery, and concurrent duplicate uploads.
- Added a "Site intelligence" workspace section: a "Request site summary" action and an "Ask a question" form, closing the gap where Phase 7's summary/question-answering API had no frontend UI. Answers and summaries are clearly labeled AI-generated with method, confidence, and limitations shown alongside the result.
- Formalized the no-authentication/single-user MVP decision as ADR-005 and updated the risk register to reflect Phase 7/8 mitigations (deterministic AI answers, the checksum race fix, and the request-body size limit); AI-provider timeout handling is explicitly deferred until a real network provider is integrated.
- Added real end-to-end Playwright coverage (create project, upload, process, inspect, calculate, select-to-highlight, ask, and request-summary) running against a live backend with an isolated SQLite database and storage directory, in addition to the existing mocked component tests.
- Documented current known limitations and a test-results summary in VERIFY.md for the Phase 8 exit criteria.
- Completed Phase 8 with a non-licensed technical review of the calculation engine (VERIFY.md section 12): verified every formula against standard civil-engineering/geometry definitions and hand-verified test cases, added missing edge-case tests (downhill/level slope, negative elevations, zero distance, negative-input rejection), and logged a newly found risk that calculations assume a projected CRS with nothing yet enforcing it. A licensed PE review is still recommended before real engineering use.
- Re-planned PLAN.md's remaining phases after auditing Requirements.md against the shipped implementation: found seven capabilities from the original requirements (LandXML, label-to-geometry linking, key-phrase extraction, bearing/COGO parsing, semantic site-model classification, directional questions, and plan-sheet snippets) that were never explicitly built or explicitly deferred. Moved release/deployment work to a renamed Phase Z and inserted a new Phase 9 to close these gaps beforehand.
- Phase 9: added LandXML parsing (`.xml` uploads) to the extraction pipeline, using the standard library's XML parser (no new dependency). Extracts `CgPoints` and surface `Pnts`/`P` points, and straight `Line` segments from alignment `CoordGeom`; curved (`Curve`/`Spiral`) alignment segments are explicitly skipped with a warning rather than approximated, consistent with the project's rule against inventing geometry. Points and lines flow through the same site-model acceptance path as the other parsers.
- Phase 9: labels extracted with a location (currently DXF `TEXT` entities, e.g. "FF=102.50") are now linked to their nearest valid geometry entity when accepting a site-model revision. The link is stored on the label entity's properties as `linked_geometry` (target entity id, type, distance, and the target's own source reference) so it is traceable through the API. A label with nothing within 10 coordinate units is left unlinked rather than matched to unrelated geometry.
- Phase 9: narrative text parsing (`.txt` and PDF page text) now scans for a fixed vocabulary of civil-engineering key phrases (e.g. "setback", "finished floor elevation", "property line", "easement") and surfaces each match as its own searchable `key_phrase` site-model entity with the matched phrase and surrounding line as context, rather than only matching keywords reactively when a question is asked. Shown in the workspace's entity grid with the matched phrase in place of a source file name.
- Phase 9: CSV parsing now recognizes quadrant bearing/distance boundary courses (e.g. `N45.00E`, `100.00`) alongside a starting point of beginning (explicit x/y or easting/northing columns), chaining each course from the previous point into a `cogo_line` entity with derived line geometry, so a parcel boundary can be described either by raw coordinates or by bearing/distance courses in the same file.
- Phase 9: site-model entities now carry an optional `semantic_type` (parcel boundary, building footprint, driveway/road, curb cut) inferred from a DXF layer name or an explicit CSV type/classification column, plus an optional `zoning` tag passed through from a CSV zoning/zone column. Shown on the entity card in the workspace UI in place of the generic entity type badge.
- Phase 9: questions naming a compass direction and an entity role (e.g. "distance to the north property line") now resolve to a new `directional_distance` intent that picks the correctly-classified entity furthest in that direction (using the `semantic_type` from the previous Phase 9 item) and measures its distance to another mapped entity, rather than requiring exactly two mapped geometries and refusing as ambiguous whenever more exist.
- Phase 9 (final item): added a `GET /projects/{project_id}/site-model/entities/{entity_id}/snippet` endpoint that re-renders a DXF-sourced entity's source file to SVG with that entity highlighted in red, using ezdxf's built-in SVG drawing backend (no new dependency). Added a "View plan-sheet snippet" button in the workspace's site-model section, available whenever an entity is highlighted (via the entity grid or a selected calculation result), which fetches and displays the highlighted plan sheet inline. Scoped to DXF-sourced entities only, since PDF rasterization would require a new dependency; other file types return a clear 400 response rather than attempting an unsupported render. This closes the seventh and final Phase 9 item.
- Added Playwright end-to-end coverage for the three Phase 9 UI additions (key-phrase display, semantic-type badges, and plan-sheet snippets), run against the real backend like `full-workflow.spec.ts`: uploading a narrative `.txt` file shows the extracted key phrases as quoted entity cards, and uploading a DXF fixture with named layers shows the resulting "parcel boundary"/"building footprint" badges and produces a viewable plan-sheet snippet image.

### Planned

- Project scaffolding and local development commands.
- Project, client, file, and processing-job models.
- Initial document extraction and processing-state transitions.
