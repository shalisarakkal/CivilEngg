# Civil Engineering AI Application Development Plan

## 1. Product Goal

Build a local-first web application for civil engineering firms that can ingest CAD drawings, PDFs, survey reports, and related data; extract engineering information; create a structured site model; perform geometry calculations; summarize site plans; and answer user questions with traceable results.

The first release will focus on a small, end-to-end vertical slice rather than implementing every file type and engineering discipline at once.

## 2. MVP Scope

### Included in the MVP

- Project and client records
- Local upload and storage of PDF, DXF, CSV, TXT, TIFF/TIF, and supported document files
- File metadata, processing status, and processing errors
- PDF/text extraction, TIFF/TIF raster metadata extraction, and a basic DXF ingestion path
- A normalized project coordinate system and site model
- Property boundaries, building footprints, points, elevations, and annotations where available
- Distance, elevation, and slope calculations
- A map or drawing view for inspecting extracted geometry
- A basic site-plan summary
- Natural-language questions that return a numeric result, calculation explanation, and source reference when available
- Automated unit, API, and integration tests
- Playwright coverage for the primary user workflow

### Deferred until after the MVP

- Full DWG support
- Advanced PDF vision/OCR for every plan-set layout
- Complete Civil 3D object support
- Full structural, stormwater, and earthwork design modules
- Multi-user authentication and billing
- Cloud object storage and hosted deployment
- Production-grade embeddings/search infrastructure

## 3. Technical Direction

This was the direction proposed at Phase 0. As implemented, several choices were deliberately simplified for the MVP; see the note after each line and DECISIONS.md for the record.

- **Frontend:** Next.js and React. *As implemented:* plain CSS instead of TailwindCSS, and a custom SVG schematic view instead of Leaflet/Mapbox — no map library was adopted (see DECISIONS.md).
- **Backend:** FastAPI with Python engineering services
- **Numerical and data processing:** Shapely and PyProj. *As implemented:* NumPy, SciPy, Pandas, and GeoPandas are unused — no shipped calculation or extraction path needs them.
- **Database:** PostgreSQL with PostGIS for project, geometry, and revision data. *As implemented:* PostgreSQL is the backend's actual default (`config.py`'s `database_url`) and what running the application locally connects to; automated tests and Playwright e2e override this with SQLite instead (`Base.metadata.create_all`), for speed and isolation. A `psycopg` driver and a PostGIS-enabling migration exist, but geometry is stored as plain JSON, not native PostGIS geometry types, and no PostGIS-specific feature is used.
- **Local file storage:** A configurable local data directory, with file metadata stored in the database
- **AI:** OpenAI API behind a provider interface, with source-grounded prompts and configurable credentials. *As implemented:* the provider interface (`AIProvider`) exists, but the only implementation is a deterministic `MockAIProvider` that never makes a network call. Real OpenAI integration is deferred (see RISK_REGISTER.md).
- **Testing:** Pytest for backend logic, `tsc`/`eslint` for the frontend, and Playwright for end-to-end workflows
- **Development:** Local environment first; deployment adapters may target Vercel and Railway or another compatible platform later

## 4. Development Phases

### Phase 0 - Decisions, Scope, and Risk Register

**Objective:** Confirm the smallest useful product and record assumptions before implementation.

**Work items:**

- [x] Choose the first engineering workflow: site-plan measurement and question answering
- [x] Confirm supported MVP file types: PDF, DXF, CSV, TXT, TIFF/TIF, and optionally DOCX
- [x] Define supported units and conversion rules, including feet, inches, meters, and percentages
- [x] Define the initial site-model entities and their source references
- [x] Document handling expectations for unsupported, corrupt, password-protected, or oversized files
- [x] Decide whether the first deployment is single-user local use or includes basic authentication
- [x] Create a risk register for extraction accuracy, coordinate systems, OCR quality, and AI reliability

**Exit criteria:**

- [x] MVP scope and deferred features are approved
- [x] Supported input formats and units are documented
- [x] Accuracy and traceability expectations are documented
- [ ] A representative sample set of client-like civil files is available for testing; current tests use sanitized/generated fixtures

### Phase 1 - Project Scaffolding and Developer Workflow

**Objective:** Establish a reproducible full-stack foundation.

**Work items:**

- [x] Create the frontend and backend application structure
- [x] Add `.gitignore`, environment-variable templates, and local configuration
- [x] Add dependency management and documented setup commands
- [x] Add database configuration and the initial migration workflow
- [x] Add formatting, linting, type checking, and test commands
- [x] Add a minimal health-check endpoint and application shell
- [x] Add CI checks for tests, linting, and type checking where practical
- [x] Keep the README concise and focused on setup and development commands

**Exit criteria:**

- [x] A new developer can install dependencies and start the application locally
- [x] Frontend and backend health checks work
- [x] A clean checkout passes the initial quality checks
- [x] Unit tests run with one documented command

### Phase 2 - Projects, Clients, Files, and Local Storage

**Objective:** Make project data and source files manageable before adding intelligence.

**Work items:**

- [x] Create database models for clients, projects, files, processing jobs, and revisions
- [x] Add project and client create, read, update, and archive operations
- [x] Implement local file storage outside the source tree
- [x] Add file type, size, checksum, upload date, and processing-status metadata
- [x] Validate file extensions and MIME types without trusting the extension alone
- [x] Add upload, list, download, and delete/archive workflows
- [x] Add clear processing states: queued, processing, completed, failed, and unsupported

**Exit criteria:**

- [x] A user can create a project and upload supported files to it
- [x] Uploaded files remain available after application restart
- [x] Duplicate files are detected by checksum or handled explicitly
- [x] Invalid and unsupported files produce clear user-facing errors
- [x] Storage-path and database tests pass

### Phase 3 - File Normalization and Extraction Pipeline

**Objective:** Convert source files into consistent, traceable intermediate data.

**Work items:**

- [x] Define a common internal document and geometry representation
- [x] Implement PDF text extraction and page metadata extraction
- [x] Implement TIFF/TIF raster metadata extraction; defer OCR to a later vision phase
- [x] Implement TXT and CSV parsing with encoding and delimiter handling
- [x] Implement the initial DXF parser for layers, lines, polylines, text, points, and dimensions where available
- [ ] Add optional DOCX parsing if it is required by the sample files
- [x] Preserve source file, page, layer, entity, and bounding-box references
- [x] Record parser warnings rather than silently dropping unsupported content
- [x] Add a processing-job interface so extraction can later run asynchronously
- [x] Store normalized extraction output in a versioned form

**Exit criteria:**

- [x] Representative sample files can be processed through the pipeline
- [x] Extracted text and geometry can be traced to the source file
- [x] Parser failures are isolated to the affected file and reported
- [x] Unit tests cover normal files, malformed input, empty input, unsupported entities, and raster metadata
- [x] At least one PDF and one DXF fixture are checked into the test strategy without exposing confidential project data

### Phase 4 - Coordinate System and Site Model

**Objective:** Build the structured model used by calculations, maps, summaries, and AI answers.

**Work items:**

- [x] Define initial site-model schemas for extracted entities and source references
- [x] Normalize supported geometry into a project coordinate system when CRS values are provided
- [x] Support explicit coordinate reference systems and report transformation failures
- [x] Use Shapely for geometry validation and PyProj for coordinate transformations
- [x] Build a site-model revision when new extraction results are accepted
- [x] Add validation for invalid and unsupported geometries
- [x] Expose a read-only project/site-model API for the frontend

**Exit criteria:**

- [x] An ingested sample project produces a queryable site model
- [x] Geometry has consistent engineering units and complete coordinate metadata
- [x] Source references are retained for every user-visible model element
- [x] Invalid geometry is reported with validation status
- [x] Revision changes can be compared

### Phase 5 - Engineering Calculation Engine

**Objective:** Provide deterministic, testable calculations independent of the UI and AI layer.

**Work items:**

- [x] Implement unit conversion and input validation
- [x] Implement point-to-point and geometry-to-geometry distances
- [x] Implement elevation lookup and elevation statistics where data supports them
- [x] Implement slope as `slope = (change in elevation / horizontal distance) * 100`
- [x] Support slope direction and clearly label percent versus ratio outputs
- [x] Add parcel area and basic geometry measurements
- [x] Return calculation inputs, assumptions, formula, result, units, and source entities
- [x] Add deterministic fixtures for known civil-engineering examples
- [x] Add tolerance-based tests for floating-point results

**Exit criteria:**

- [x] Identical inputs produce identical results
- [x] Calculations reject missing, incompatible, or invalid inputs
- [x] Results include enough detail for an engineer to reproduce them
- [x] Unit tests cover positive, zero, negative, and boundary cases
- [x] Calculation results can be requested through an API without using the AI provider

### Phase 6 - Engineering Workspace UI and Map View

**Objective:** Give users a practical way to inspect files, extracted data, and results.

**Work items:**

- [x] Create project dashboard with files, processing status, and recent revisions
- [x] Add upload and processing-status interactions
- [x] Add map/drawing view with fit-to-project behavior
- [x] Render selectable site-model layers and source references
- [x] Add calculation forms for distance, elevation, slope, and area
- [x] Display assumptions, units, warnings, and calculation provenance
- [x] Add responsive layouts for desktop and smaller screens
- [x] Use the project color scheme consistently while preserving readable contrast
- [x] Add loading, empty, error, and unsupported-data states

**Exit criteria:**

- [x] A user can upload a file, inspect extracted geometry, and run a calculation from the UI
- [x] Selecting a calculation result highlights the relevant geometry or source location where possible
- [x] The UI clearly distinguishes extracted, calculated, and AI-generated information
- [x] Core screens work at desktop and mobile viewport sizes
- [x] Frontend browser tests cover upload state, calculation state, and error state; automated backend coverage is complete

Phase 6 lifecycle additions:

- [x] Make revision acceptance idempotent
- [x] Archive deleted source files and preserve metadata
- [x] Preserve archived checksums for duplicate detection
- [x] Add in-app deletion confirmation
- [x] Add admin archive list, restore, and permanent purge routes/UI

### Phase 7 - Site Summaries and Source-Grounded Question Answering

**Objective:** Add useful AI assistance without allowing unsupported claims to appear as engineering facts.

**Work items:**

- [x] Define a provider interface for OpenAI and a deterministic local/mock provider for tests
- [x] Generate a structured site summary from the site model and extracted document text
- [x] Add high-level, grading, drainage, and utilities summary sections when data exists
- [x] Generate attention flags for steep slopes, tight setbacks, missing data, and unusual elevations
- [x] Parse question intent for measurements such as setback distance and elevation
- [x] Route computable questions to deterministic geometry calculations first
- [x] Use retrieval of relevant source text and geometry context for explanatory responses
- [x] Return numeric answer, units, method, source reference, confidence/limitations, and timestamp
- [x] Clearly label unknown or insufficient-data answers
- [x] Add prompt-injection and untrusted-document handling rules
- [x] Store question and answer revisions without storing secrets

**Exit criteria:**

- [x] “What is the setback distance?” can produce a calculation when the required entities exist
- [x] AI responses cite the file/page/layer/entity context used to answer
- [x] The system refuses to invent measurements when source data is missing
- [x] Mock-provider tests run without network access
- [x] Golden test cases cover correct answers, ambiguous questions, and insufficient data

### Phase 8 - Quality, Security, and Integration Hardening

**Objective:** Validate the complete workflow and prepare a reliable MVP release.

**Work items:**

- [x] Add end-to-end Playwright coverage for create project, upload, process, inspect, calculate, and ask
- [x] Add API integration tests using an isolated test database and file directory
- [x] Test restart and recovery behavior for interrupted processing jobs
- [x] Test large files, malformed files, duplicate files, and concurrent requests
- [x] Add authorization boundaries if multi-user access is enabled; not applicable for the MVP (ADR-005: single-user local deployment, no multi-user access)
- [x] Protect local file paths against traversal and unsafe filenames
- [x] Validate upload and request limits; AI-provider timeout behavior is deferred until a real network provider is integrated (see RISK_REGISTER.md)
- [x] Add structured logging with correlation IDs and remove sensitive content from logs
- [x] Add basic error monitoring and operational diagnostics
- [x] Review calculation outputs with a civil-engineering subject-matter expert; performed as a non-licensed technical review by Claude in the absence of an available licensed engineer (see VERIFY.md section 12) — formulas and hand-verified test cases check out, one real gap (missing negative/zero/downhill edge-case tests) was found and fixed, and one real risk (calculations assume a projected CRS, unenforced) was newly logged in RISK_REGISTER.md. **A licensed civil engineer should still review this before real engineering use.**

**Exit criteria:**

- [x] The primary workflow passes in a clean environment (isolated SQLite database and storage directory; see VERIFY.md test results)
- [x] Critical failures have actionable logs and user-facing messages
- [x] Security checks cover uploads, file access, secrets, and prompt inputs (no secrets are handled in the MVP; see RISK_REGISTER.md)
- [x] Engineering calculations pass subject-matter review for the supported cases (non-licensed technical review; see VERIFY.md section 12 — licensed PE review still recommended before real-world use)
- [x] MVP has documented known limitations and test results (see VERIFY.md)

### Phase 9 - Closing Requirements Gaps

**Objective:** Implement the capabilities from Requirements.md that were never explicitly built or explicitly deferred, so the release in Phase Z reflects a deliberate, complete scope decision rather than silent omissions. Found during a Phase 8 documentation audit (see CHANGELOG.md); each item below was present in the original requirements but absent from both the MVP scope and the deferred/roadmap lists.

**Work items:**

- [x] Add LandXML parsing to the extraction pipeline (points and surfaces/alignments where present), producing the same normalized document representation used by the other parsers
- [x] Link extracted text labels (e.g. "FF=102.50", "Top of curb 101.80") to nearby geometry by spatial proximity, and preserve that link as a source reference
- [x] Extract key phrases from narrative text (e.g. "setback", "finished floor elevation") during document parsing and surface them as searchable site-model annotations, rather than only matching keywords in the user's question
- [x] Parse bearing/distance (COGO) values for parcel boundary segments where present in DXF/CSV/LandXML input, in addition to the raw coordinates already extracted
- [x] Add semantic site-model entity classification (parcel boundary, building footprint, driveway/road, curb cut) with optional zoning tags, beyond today's generic point/line/polygon/text typing
- [x] Support directional/targeted questions (e.g. "distance to the north property line") by resolving a named entity role and direction, instead of always picking whichever two mapped geometries exist
- [x] Generate an annotated snippet/screenshot of the source plan sheet with the relevant geometry highlighted, in addition to the existing in-app schematic highlight

**Exit criteria:**

- [x] A LandXML fixture can be ingested and produces site-model entities
- [x] At least one extracted label is correctly linked to its nearest geometry entity with a traceable source reference
- [x] Key phrases extracted from a sample document are retrievable and shown in the UI
- [x] At least one parcel boundary case demonstrates bearing/distance-derived geometry alongside raw coordinates
- [x] Site-model entities can carry a semantic type (parcel/building/driveway/etc.) and it is visible in the UI
- [x] A directional question ("north property line") returns a different, correct answer than a generic nearest-geometry query
- [x] A question or calculation result can produce an annotated image/snippet of the source plan sheet, not just the in-app schematic view

### Phase 10 - Project Lifecycle and Multi-File Operations

**Objective:** Close a gap found during manual verification: a project can be archived via the API (Phase 2), but there is no restore, no permanent purge, and no UI for any of it — unlike source files, which got the full archive/restore/purge lifecycle with an admin panel in Phase 6. Also add multi-file operations within a project, so a user isn't limited to one file at a time for upload, processing, deletion, restore, and purge.

**Work items:**

- [x] Add a project restore endpoint (reverse an archive)
- [x] Add a project permanent-purge endpoint: delete the project row (cascading to its files, jobs, revisions, entities, calculations, summaries, and Q&A history via existing `ondelete="CASCADE"` foreign keys) and delete its local storage subdirectory
- [x] Add an in-app archive action with confirmation for a project, mirroring the existing file-row pattern
- [x] Add archived projects to the admin panel (or a dedicated section) with restore and permanent-purge actions, mirroring the existing archived-files panel
- [x] Fix the empty-workspace state showing "Create your first project" even when projects exist (found via the new archive action: archiving the currently-active project always clears the selection to null, even when other projects remain). Shows "Select your project" instead when one or more projects exist but none is selected, and auto-selects the remaining project when exactly one is left after archiving the active one.
- [x] Support selecting multiple files in a project's file list (checkboxes or a "select all")
- [x] Support uploading multiple files in one action instead of one at a time
- [x] Support drag-and-drop file upload (single or multiple files) as an alternative to the file picker, with drag-over visual feedback and unsupported-type rejection before upload
- [x] Support processing multiple selected/queued files in one action
- [x] Support archiving (deleting) multiple selected files in one action
- [x] Support accepting a revision for multiple selected files in one action (not originally scoped here, added afterward for parity with the other per-file actions). Runs sequentially rather than concurrently like the other batch actions, since accepting assigns the next revision number for the project and concurrent accepts already caused a real duplicate-number bug once; a selected file that's already accepted or not yet completed is skipped client-side rather than sent to the server.
- [x] Support restoring multiple archived files in one action
- [x] Support permanently purging multiple archived files in one action
- [x] Add client-side sort (name, date, status) and filter (status, file type) controls to a project's file list
- [x] Report partial success/failure clearly for every multi-file action (e.g. if one file fails to process, the others still complete and the failure is called out) rather than an all-or-nothing result
- [x] Add unit and API integration tests for the new project-lifecycle endpoints and every multi-file batch path, including partial-failure cases. Multi-file operations turned out not to need new backend endpoints at all: each batch action (upload, process, archive, restore, purge) is the frontend calling the same existing single-file endpoint once per selected file (`Promise.all` for process/archive/restore/purge, sequential for upload to preserve duplicate-checksum ordering) and aggregating the per-file results into one status message. So "API integration tests for batch paths" is covered by the existing single-file endpoint tests in `test_api.py` plus the new Playwright coverage below, which exercises the aggregation and partial-failure reporting directly.
- [x] Add Playwright coverage for project archive/restore/purge and at least one multi-file flow. Both halves are now covered in `workspace.spec.ts`: a full project archive/restore/re-archive/purge lifecycle test, plus the multi-file upload and partial-failure batch-archive tests added earlier.

**Exit criteria:**

- [x] A user can archive a project from the UI with confirmation, see it in an admin list, restore it, and permanently purge it — the same lifecycle files already have
- [x] Permanently purging a project removes its database rows and its on-disk storage directory
- [x] A user can select multiple files in a project and upload, process, archive, restore, or permanently purge them in a single action
- [x] A user can drag one or more files onto the upload area to upload them, with clear feedback while dragging and a clear rejection message for an unsupported file type
- [x] A user can sort a project's file list (name, date, status) and filter it (status, file type)
- [x] A multi-file action where one file fails still completes the others and clearly reports which failed and why

### Phase 11 - Site Intelligence Follow-ups

**Objective:** Close a gap found during manual verification of the multi-revision project-boundary summary/question feature (added after Phase 7): a generated site summary is persisted in the database on every request, but the workspace UI only ever holds the single most recent one in memory. Generating a new summary (e.g. for a different file or scope selection) silently replaces the one on screen, with no way to see an earlier summary again without querying the database directly — unlike questions, which already keep a visible history list.

**Work items:**

- [x] Add a `GET /projects/{project_id}/summaries` endpoint listing past summaries (most recent first). Turned out the existing `question_answers` "history" isn't actually a backend-persisted pattern to match: there's no `GET /questions` endpoint at all, and the frontend's question history is a session-local array that resets on reload/project switch. Summaries now do better than that baseline — real backend persistence, fetched on project load, surviving reloads and project switches — rather than reproducing the same session-only limitation.
- [x] Show generated summaries in the workspace as a history list (like the existing Q&A list) instead of a single replaceable card, each labeled with its resolved scope (whole project vs. specific revisions) and timestamp

**Exit criteria:**

- [x] Generating a new summary does not hide a previously generated one from the UI
- [x] Each summary in the list clearly shows which revisions it covered and when it was generated

### Phase 12 - Activity Events (not yet scoped)

**Objective:** Found via a real report: processing 26 files, then running a calculation before checking back, silently lost the processing outcome. The status banner is a single line covering the single most recent action across the whole app, and a multi-file batch doesn't block the rest of the page while it runs — so whichever action's status update lands last simply overwrites the banner with no way to recover what was there before. A narrower fix (a small panel preserving just the last few multi-file batch outcomes) was built and verified, then deliberately rolled back in favor of this: a proper activity-events system recording every notable action app-wide (not just multi-file batches), not only the ones that happen to involve more than one file.

**Work items (not yet broken down):**

- [ ] Decide what counts as a loggable "activity event" app-wide (every action currently passed to the status banner, or a curated subset) and its retention (session-only vs. persisted, how many/how long)
- [ ] Decide the UI: a persistent panel/log, a toast/notification stack, or something else
- [ ] Design and implement the event model and storage
- [ ] Implement the chosen UI, replacing or complementing the existing single-line status banner
- [ ] Add test coverage

### Phase 13 - Archive Retention and Purge History

**Objective:** Prompted by a real incident: a large, real project was manually purged (correctly, deliberately, by the user) and there was no record afterward of what it had been or when it went, and no safety net for an archived item nobody ever gets around to purging or restoring. Two related but distinct mechanisms: (1) an audit trail of every purge, manual or automatic, that outlives the purged data itself; (2) archived projects and files are no longer kept indefinitely — they're automatically, permanently purged after a configurable retention window if nobody restores or manually purges them first, with a visible warning as that deadline approaches.

**Work items:**

- [x] Add a `purge_history` table recording every purge (manual or automatic): resource type/id/name, owning project (for files), when it was archived, why it was purged, when. No foreign keys to the purged resource, since by definition that row is gone by the time this one matters.
- [x] Add `ARCHIVE_RETENTION_DAYS` (default 180), `ARCHIVE_PURGE_WARNING_DAYS` (default 15), and `PURGE_HISTORY_RETENTION_DAYS` (default 365) settings
- [x] Auto-purge archived projects and files once their retention window elapses, via a lazy sweep (no scheduler/cron dependency exists in this app) run at the top of the archived-list endpoints rather than on a timer
- [x] Prune `purge_history` rows past their own (separate, longer) retention in the same sweep
- [x] Surface `purge_scheduled_at` and a `purge_warning` flag (true inside the warning window) on the archived-projects and archived-files list responses
- [x] Show an auto-purge countdown on each archived row in both admin panels, visually flagged once inside the warning window
- [x] `GET /admin/purge-history` endpoint so the log is queryable now; no browsing UI yet (deferred — capture the data first, decide what's worth showing once there's real history to look at)
- [ ] (Optional, deferred) Compress archived files above a size threshold, decompressing on restore; compress a project's files when the project itself is archived. Not started — project-archive today never touches storage at all (only purge does), so the project-level half is a bigger change than the file-level half, and compression benefit varies a lot by file type (text/CSV/XML compress well, PDF/TIFF often don't).

**Exit criteria:**

- [x] Every purge, manual or automatic, is recorded with enough detail to answer "what was this and when did it go" after the fact
- [x] An archived project or file nobody acts on is eventually purged on its own rather than kept forever
- [x] A user can see, before it happens, that something is about to be auto-purged

### Phase Z - MVP Release and Deployment

**Objective:** Deliver a usable, repeatable MVP with a documented operational path.

**Work items:**

- [x] Freeze MVP scope — see DECISIONS.md ADR-008 (tagging itself is still pending the smoke test below and your approval)
- [x] Provide local deployment instructions and sample configuration — see DEPLOYMENT.md
- [x] Configure production database migrations and backup strategy — see DEPLOYMENT.md sections 6-7 and `backend/scripts/backup.py`/`restore.py`
- [x] Define local-storage backup and restore procedures — captured together with the database (DEPLOYMENT.md section 6), since they must stay in sync
- [x] Add deployment configuration for the selected frontend and backend hosts if needed — not applicable; the MVP is a single local machine per ADR-002/ADR-005 (see DEPLOYMENT.md section 1)
- [x] Configure environment secrets outside source control — already enforced via `.gitignore`; see DEPLOYMENT.md section 4 for the checklist
- [x] Run a final smoke test against the deployed environment — 2026-09-16: built and ran the actual production frontend (`npm run build`, `npm run start`) and backend (`npm run start:backend`, no `--reload`) against the real database, and exercised create/upload/process/accept-revision/ask end to end via the API. Surfaced and fixed a real bug along the way (CSV point elevation was dropped, see RISK_REGISTER.md) and found an open gap (perimeter/area questions aren't routed, see RISK_REGISTER.md), both logged. Not yet done: a pass through the UI itself in a browser rather than the API directly
- [x] Publish a short user guide for supported files, units, calculations, and limitations — see USER_GUIDE.md
- [x] Record post-MVP issues and prioritize the next release — see section 8 below

**Exit criteria:**

- [x] The MVP is running in the target environment — production frontend (`npm run start`) and backend (`npm run start:backend`) running locally as of 2026-09-16
- [x] A new project can be created and processed end to end — verified via the smoke test above
- [x] Backups and recovery steps have been tested — verified 2026-09-16 against a real backup restored into a disposable scratch database/storage directory (see DEPLOYMENT.md section 6)
- [x] Deployment, configuration, and rollback steps are documented — see DEPLOYMENT.md
- [x] The server is left running and ready for user acceptance testing — production frontend/backend left running on ports 3000/8000 after the smoke test

## 5. Testing Strategy

### Unit tests

- Parsers and normalizers
- Unit conversion and validation
- Geometry operations
- Slope, distance, elevation, and area calculations
- Site-model validation
- AI intent routing and response formatting

### Integration tests

- API and database operations
- File storage and processing jobs
- Extraction-to-site-model flow
- Site-model-to-calculation flow
- Mock AI provider and source references

### End-to-end tests

- Project creation
- File upload and status updates
- Map/drawing inspection
- Calculation execution
- Source-grounded question answering
- Error and unsupported-file workflows

### Engineering acceptance tests

- Known distance and slope calculations with hand-verified expected values
- Known coordinate transformation cases
- Known sample plan-set extraction cases
- Review of source references and displayed assumptions

## 6. Initial Data and API Boundaries

### Initial entities

- Client
- Project
- Source file
- Processing job
- Project revision
- Site-model entity
- Calculation request/result
- Question/answer record

### Initial API groups

- `/health`
- `/clients`
- `/projects`
- `/projects/{project_id}/files`
- `/projects/{project_id}/processing`
- `/projects/{project_id}/site-model`
- `/projects/{project_id}/calculations`
- `/projects/{project_id}/summaries`
- `/projects/{project_id}/questions`

These are logical boundaries; exact routes and schemas should be finalized during Phase 1 and Phase 2.

## 7. MVP Definition of Done

- [ ] A user can create a project
- [ ] A user can upload a supported PDF, DXF, CSV, TXT, or TIFF/TIF file
- [ ] The application processes the file and displays status and warnings
- [ ] Extracted geometry and text are available in the project site model
- [ ] A user can view the project geometry on a map or drawing surface
- [ ] A user can calculate distance, elevation, slope, or area
- [ ] Results show units, inputs, assumptions, formula, and source references
- [ ] A user can request a site summary
- [ ] A user can ask at least one geometry-backed question such as setback distance
- [ ] The application does not fabricate a result when required data is absent
- [ ] Unit, integration, and Playwright tests pass
- [ ] Local setup, storage, backup, limitations, and deployment instructions are documented

## 8. Post-MVP Roadmap

**Nearest-term, ahead of the numbered list below** (per ADR-008's scope
freeze):

1. **Phase 12 - Activity Events** (PLAN.md, not yet scoped): highest
   priority of anything deferred from this release — it's the direct fix
   for a real reported failure (a multi-file batch outcome silently lost
   because a later action overwrote the single-line status banner), not
   a speculative improvement.
2. **Wire perimeter and area into the question router** (`route_question`
   in ai_service.py): found via the Phase Z final smoke test — both
   calculations already work through `/calculations` directly, they're
   just unreachable by asking a question about them. See RISK_REGISTER.md.
3. **Phase 13 optional - archive/project file compression**: lowest
   urgency of the deferred work — no reported pain point yet, and
   project-level compression is a bigger change than file-level since
   project archival doesn't touch storage at all today.

Everything below is unprioritized relative to each other and to the
items above:

1. Expand CAD support to DWG and richer Civil 3D entities.
2. Improve PDF plan-set vision, OCR, title-block, viewport, and callout extraction.
3. Add contours, TIN surfaces, alignments, and profile analysis.
4. Add stormwater, earthwork, structural, and pipe-network calculation modules.
5. Add embeddings and semantic search for large document collections.
6. Add multi-user authentication, permissions, billing, and audit history.
7. Add cloud storage while retaining a local-storage deployment option.
8. Add Sentry, PostHog, and centralized logging after the core workflow is stable.
