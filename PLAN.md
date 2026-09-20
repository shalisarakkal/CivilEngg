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
- Billing (multi-user authentication, roles, and per-project ownership shipped as Phase 15 — see section 8's roadmap item 6 and DECISIONS.md ADR-009)
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

Phase 1 lifecycle additions:

- [x] Replace the original `start-dev.ps1` (start-only, `-Stop` bolted on
  as an afterthought) with `control-dev.ps1`: one script, one `-Action`
  parameter (`Start`/`Stop`/`Restart`/`Status`), each independently
  scopable to `-Backend` and/or `-Frontend` (neither switch means both).
  Prompted directly in conversation, not found via audit.
- [x] Stop both dev servers in the background instead of opening a
  visible PowerShell window each (`Start-Process ... -WindowStyle
  Hidden`), with output going to `logs/backend.log` / `logs/frontend.log`
  — raised after the visible windows were flagged as unwanted, and, along
  the way, needed to switch from `*>` file redirection to
  `2>&1 | Out-File -Encoding utf8` (`*>` defaults to UTF-16, which renders
  as garbled double-spaced text in `grep`/`tail`/most editors) plus an
  explicit `[Console]::OutputEncoding` set so Next.js's own box-drawing
  glyphs (▲/✓/⚠) render correctly instead of as mojibake.
  A custom `.NET Process`-based capture layer (to allow true live,
  in-process log rotation) was tried and deliberately dropped: on Windows
  it silently swallowed uvicorn's real startup/request-log output going
  through `uv -> uvicorn --reload -> its multiprocessing reload worker`
  — a correctness regression worse than not having live rotation, caught
  by manually diffing the resulting log against a known-working run
  before this shipped.
- [x] Add configurable log versioning (`-MaxLogSizeMB` default 5,
  `-MaxLogFiles` default 10): every `Start`/the start-half of `Restart`
  rotates a service's existing log to `.1` (shifting older numbered
  backups up, dropping anything past `-MaxLogFiles`), so each run gets a
  clean live file and past runs stay available. True live rotation
  (rewriting a log file's content while the writing process keeps running
  without restarting it) was investigated and intentionally not built —
  it would mean either fighting the file handle PowerShell's redirection
  holds open for the process's whole lifetime, or the same custom-capture
  approach already ruled out above for silently losing output.
  `-Action Status` instead flags a log once it's past `-MaxLogSizeMB` as
  a visible signal to restart that service.
- [x] Fix a real, independently-discovered bug the same day this was
  built: stopping a server by killing only the PID that owns its listening
  port left `uvicorn --reload`'s multiprocessing worker process running
  as an orphan, still holding the port — first hit and manually
  diagnosed/fixed mid-session (`Get-CimInstance Win32_Process` to find
  the orphaned child), then generalized into `Stop`'s process-tree walk
  (`Get-ProcessTreeIds`) so it can't recur for either service.
- [x] Verified end to end against the real dev environment: `Start`,
  `Stop`, `Restart` (both services and each scoped individually),
  `Status` (including the oversized-log flag), log content correctness
  (UTF-8, full uvicorn/Next.js output present, no data loss versus the
  original `*>`-redirected/visible-window approach), and log versioning
  across repeated restarts (`backend.log`, `.log.1`, `.log.2`).

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
- [x] Run a final smoke test against the deployed environment — 2026-09-16: built and ran the actual production frontend (`npm run build`, `npm run start`) and backend (`npm run start:backend`, no `--reload`) against the real database, and exercised create/upload/process/accept-revision/ask end to end via the API. Surfaced and fixed two real bugs along the way (CSV point elevation was dropped; perimeter/area questions weren't routed — both now fixed, see RISK_REGISTER.md). Not yet done: a pass through the UI itself in a browser rather than the API directly
- [x] Publish a short user guide for supported files, units, calculations, and limitations — see USER_GUIDE.md
- [x] Record post-MVP issues and prioritize the next release — see section 8 below

**Exit criteria:**

- [x] The MVP is running in the target environment — production frontend (`npm run start`) and backend (`npm run start:backend`) running locally as of 2026-09-16
- [x] A new project can be created and processed end to end — verified via the smoke test above
- [x] Backups and recovery steps have been tested — verified 2026-09-16 against a real backup restored into a disposable scratch database/storage directory (see DEPLOYMENT.md section 6)
- [x] Deployment, configuration, and rollback steps are documented — see DEPLOYMENT.md
- [x] The server is left running and ready for user acceptance testing — production frontend/backend left running on ports 3000/8000 after the smoke test

### Phase 14 - Question-Answering Coverage Expansion (not yet scoped)

**Objective:** Found via a manual audit against `TestQuestions` (a checklist of realistic site-plan questions covering document metadata, property/building/parking/site-feature geometry, elevations, and deterministic calculations): the natural-language Q&A endpoint (`ai_service.py`'s `route_question`/`MockAIProvider.answer`) only recognizes six intents by keyword (`area`, `perimeter`, `distance`/`setback`, `slope`, `elevation`, and four-direction `north/south/east/west` + `property line`/`building`/`driveway`/`curb cut`). Everything else — document metadata, counts, named-feature lookups, specific labeled elevations — falls through to a generic text-retrieval fallback with no computed value. Additionally, `_answer_area`/`_answer_perimeter` don't filter candidates by semantic role the way `_answer_directional` does, so a site model containing both a parcel boundary and a building footprint polygon makes "What is the property area?" and "What is the building footprint area?" collide on the same candidate pool and return "ambiguous" instead of picking the right one.

**Work items (not yet broken down), roughly in increasing effort:**

- [x] Fixed the area/perimeter role-filtering gap (2026-09-19, see RISK_REGISTER.md): extracted `_question_role()` from `_parse_directional_question`'s existing `ROLE_TO_SEMANTIC_TYPE` lookup and reused it in `_answer_area`/`_answer_perimeter` to narrow candidates before the ambiguity check when the question names a role ("parcel"/"property line" -> `parcel_boundary`, "building"/"footprint" -> `building_footprint`, etc.); a role-less question still considers every candidate, unchanged. Regression test: `test_area_and_perimeter_questions_pick_the_named_role_instead_of_colliding`
- [x] Added semantic-type keywords for previously-unclassified features referenced in `TestQuestions` (utility easement, parking space/lot, tree, sidewalk, stormwater detention basin), mirroring the existing `DRIVEWAY_TYPE_KEYWORDS`/`CURB_CUT_TYPE_KEYWORDS` pattern in `routes.py`. Also added bare `"property"`/`"lot"` as `parcel_boundary` role phrases in `ai_service.py`'s `ROLE_TO_SEMANTIC_TYPE` — TestQuestions' literal wording ("property area", "property dimensions") never included "line"/"boundary", so it never matched the pre-existing role phrases at all (2026-09-19).
- [x] Wired the existing drainage/utility keyword rollups (`_keyword_summary` in `ai_service.py`) into `ask_question` via new `drainage`/`utility` intents (`_answer_keyword_topic`), so "Is a utility easement shown?" now gets a real answer instead of the generic text fallback. `_entity_text` now also folds in an entity's `semantic_type`, so e.g. a `detention_basin` polygon surfaces in the drainage rollup even if its CAD layer isn't literally named with a drainage word (2026-09-19).
- [x] Added a `count` intent (`_answer_count`) for "How many X are shown?", resolved via the same role vocabulary; a role with zero classified entities returns insufficient-data rather than an affirmative zero, since classification is deterministic/keyword-based and a miss is indistinguishable from a true absence (2026-09-19).
- [x] Added building/lot dimension, width, length, and orientation answers (`_answer_dimensions`/`_answer_orientation`) from a polygon's minimum-area oriented bounding rectangle (`shapely.oriented_envelope`), narrowed by role the same way area/perimeter are. Orientation is reported as a 0-180 degree compass axis, not a directed 0-360 bearing, since a rectangle's long side has no inherent direction (2026-09-19).
- [x] Added a deterministic setback-compliance/clearance check (`_answer_setback_compliance`) for a building-role setback question, replacing the previous behavior of routing it to the generic "exactly two mapped geometries in the whole model" distance answer (ambiguous in any real site model with more than two). Measures boundary-to-boundary clearance (not polygon-to-polygon, which is always 0 once one is nested inside the other) between the building footprint and the parcel boundary. If the question states an explicit numeric setback with a unit (e.g. "at least 25 ft"), reports compliant/not compliant against it; otherwise reports the measured clearance alone and says compliance can't be determined, since the project has no general way to read a *required* setback value back out of extracted text (2026-09-19).
- [x] Extended the existing DXF label-to-geometry proximity linking (RISK_REGISTER.md) to elevation lookups specifically (`_answer_elevation_lookup`): a question naming a labeled spot elevation in the plan's own "EL <number>" convention (e.g. "Where is EL 102.5 located?", "elevation difference between EL 102.5 and EL 101.0") is resolved to the matching text label rather than only reporting the overall min/max/average — grounded in an actual matching label, not the number the question happens to contain (2026-09-19). Implemented via the label's own text/location rather than its `linked_geometry` reference, since the label already states its own elevation value.
  - Not done: a generic "Where is the parking lot located?"/"Where is the detention basin located?" location lookup for an arbitrary role (only count/presence was built for these roles, not a location answer). Left open below.
- [ ] Investigate document title-block metadata extraction (project name, sheet number, revision, drawing date, scale, construction-ready flag, sheet count, drawing type, legend contents) — a new parsing pass over PDF/DXF text, not just a keyword-list extension; treat as the largest and most speculative item since title-block layouts vary a lot per drawing set (related to the existing "Improve PDF plan-set vision, OCR, title-block ... extraction" line in the Post-MVP Roadmap below)
- [ ] Add a generic "where is the X located?" answer for any classified role (parking, detention basin, utility easement, sidewalk, tree) using centroid/description, mirroring `_answer_directional`'s centroid resolution but without requiring a direction word

**Found and fixed along the way (2026-09-19):** `_parse_directional_question` matched compass words as bare substrings (`word in normalized`), so any threshold-style question containing "at least" was misdetected as asking about compass east ("east" is a substring of "least"). Fixed with word-boundary regex matching; incidentally also stopped "northeast"/"southwest"-style intercardinal phrasing from being silently misread as one of the four supported cardinal directions (still unsupported, per the existing "only four compass words" accepted limitation, but now falls through instead of guessing wrong). Regression test: `test_directional_parsing_does_not_misfire_on_east_as_a_word_fragment`.

**Exit criteria (draft, pending scoping):**

- [x] `TestQuestions` categories 2, 3, and 7 (property/building area, perimeter, and dimensions; deterministic calculations) resolve correctly even when the site model contains multiple similar-role geometries
- [ ] Category 6 (elevation) is partially done: a specific labeled spot elevation and the difference between two are answerable; "What elevation values are shown?"/highest/lowest were already answerable before this phase
- [x] Utility easements, parking, and trees are classified and answerable for count where geometry supports it; location lookup by role is not yet built (see the open work item above)
- [ ] Document-metadata questions (category 1) are scoped as accepted-limitation or given a concrete extraction plan — decide which before implementation starts

### Phase 15 - Roles, Ownership, and Authentication

**Objective:** The application had no user concept at all (ADR-005): no
login, no session, no permission check anywhere in the API. Implements
a three-role model (Admin / Power User / User) with project ownership,
requested directly rather than found via audit. See ADR-009 in
DECISIONS.md for the full role/permission matrix and the design choices
behind it (session-cookie auth, app-layer role validation instead of a
DB enum, `purge_history.purged_by_user_id`).

**Work items:**

- [x] Add `User`, `Session`, `ProjectMembership` models and
  `projects.owner_id`; migrations `0017_add_users_roles_ownership` and
  `0018_add_purge_history_purged_by`
- [x] Session-cookie authentication (`backend/src/civil_engineering/auth.py`):
  bcrypt password hashing, server-side sessions, `get_current_user` and
  role/ownership-aware permission dependencies (`require_admin`,
  `require_project_member`, `require_project_archive_rights`,
  `require_project_owner`)
- [x] `POST/GET /auth/login|logout|me`, `POST/GET/PATCH/DELETE /users`,
  project membership/ownership-transfer endpoints
  (`POST/GET/DELETE /projects/{id}/members`, `PATCH /projects/{id}/owner`)
- [x] Every existing project/client/admin endpoint wired to the
  appropriate permission dependency (34 handlers)
- [x] `backend/scripts/create_sysadmin.py` bootstrap script (reads
  `SYSADMIN_INITIAL_PASSWORD` from the environment, never hardcoded;
  backfills any pre-existing ownerless project onto the new sysadmin)
- [x] Backend tests: `tests/test_auth.py` (14 new tests covering login,
  session expiry-on-disable, the full role/ownership matrix); the 11
  pre-existing test files patched with a one-line `get_current_user`
  override (`tests/auth_helpers.py`) so they keep testing business logic
  unaffected by the new permission layer — all 113 backend tests pass
- [x] Frontend: `/login` page, `AuthContext` (first React context in
  this codebase), `apiFetch` wrapper (first shared fetch helper — all
  ~30 existing raw `fetch` call sites in `ProjectWorkspace.tsx` migrated
  to it) sending the session cookie and redirecting to `/login` on 401,
  `/admin/users` management page
  (`Manage users`/create/role-change/disable), sign-out button
- [x] Verified end to end against the real Postgres dev database and a
  live browser session, and via direct HTTP: login, `/auth/me`, a Power
  User creating a project and becoming owner, adding a User as a
  collaborator, the collaborator viewing but being denied (403)
  archiving, and a plain `POST /projects` being denied for the `user`
  role. Found and fixed one real bug this way: `auth.py`'s original
  `_as_utc` only relabeled a naive datetime's tzinfo instead of
  converting an aware one, which broke `set_cookie`'s `usegmt=True`
  against Postgres (`timestamptz` columns come back in the connection's
  session timezone, not literally UTC) — 500'd every real login until
  fixed
- [x] Extended role-gated UI beyond "Archive project" to every
  archive/purge/restore control: file-level "Archive"/"Archive
  selected", and the "Archived files"/"Archived projects" admin panels
  (both their fetch and their rendering — previously a `user`-role
  account triggered a 403'd fetch and saw a misleading "0 archived"
  empty state instead of the panel being absent). Also found and fixed
  a related precision bug while doing this: "Archive project" and the
  per-project Restore/Purge buttons in the archived-projects panel were
  gated on `role !== "user"` (any Power User), but their actual backend
  routes (`archive_project`, `restore_archived_project`,
  `purge_archived_project`) require `require_project_owner` —
  owner-or-admin specifically, matching what "Reassign owner" already
  required. A Power User *collaborator* (not owner) would have seen
  those buttons and gotten a 403. Tightened to
  `role === "admin" || currentUser.id === project.owner_id` to match.
  File-level archive/restore/purge only needs `role !== "user"` per
  `require_project_archive_rights` (any collaborator, not owner-only),
  confirmed against the actual dependency before gating rather than
  assumed. Verified end to end logged in as `u-bob` (`user` role): no
  Reassign owner/Archive project buttons, no archived panels at all.
- [x] Playwright e2e coverage updated for the auth layer, exactly as
  scoped: `scripts/e2e_bootstrap.py` now seeds one fixed-credential
  account per role (`e2e-admin`/`e2e-power-user`/`e2e-user`, idempotent —
  skips any that already exist, since the e2e SQLite database persists
  across local runs); `frontend/global-setup.ts` logs in as
  `e2e-power-user` via the API and saves a `storageState`
  (`playwright/.auth/power-user.json`), wired into `playwright.config.ts`
  via `globalSetup` + `use.storageState` so `full-workflow.spec.ts` and
  `phase9.spec.ts` (real backend) start already authenticated with no
  per-test login step; `workspace.spec.ts`'s `mockBaseline()` now mocks
  `GET /auth/me` too (its own fixed mock user, independent of the real
  login above, keeping that spec's full-mock isolation), and its `PROJECT`
  fixture got an `owner_id` matching the mock user so the newly
  role-gated owner-only buttons it exercises (Archive project, etc.)
  still render. Found and fixed a real, unrelated pre-existing gap along
  the way: `.e2e-data/e2e.db` is a long-lived SQLite file (intentionally
  persists across local runs), and `e2e_bootstrap.py` only ever ran
  `Base.metadata.create_all`, which creates missing tables but never
  alters existing ones — so the leftover pre-Phase-15 database (no
  `owner_id` column, no `users` table) 500'd every project creation with
  `table projects has no column named owner_id` the first time this
  suite ran since Phase 15 shipped. Not caused by this work, but this was
  the first time anyone ran the e2e suite since Phase 15 added those
  columns/tables, so nothing had surfaced it yet. Fixed by clearing
  `.e2e-data/` (schema is then created fresh and correct); added a
  comment in `playwright.config.ts` so the next schema change doesn't
  cause the same confusing 500. Verified by actually running the suite,
  not just reading the code: all 22 tests pass (3 full-workflow, 2
  phase9, 17 workspace) against a fresh e2e database
- [x] A "reassign owner" action from within the UI itself (prompted
  directly in conversation): a "Reassign owner" button on the active
  project, visible to its current owner or any admin, opens a modal
  listing the project's Power User collaborators
  (`GET /projects/{id}/members`, extended to carry `username`/`role` so
  the picker doesn't need admin-only `GET /users`) and calls the
  existing `PATCH /projects/{id}/owner`. Verified end to end as both an
  admin and as the actual non-admin owner. "Add collaborator" is still
  addressed by the "Add collaborator" item below
- [x] An "add collaborator" action from within the UI itself. Needed a
  small new backend endpoint first: `GET /users/lookup?username=...`,
  callable by any authenticated user (exact-match only, doesn't
  enumerate the directory), since the existing `GET /users` is
  admin-only and a non-admin Power User owner has no other way to
  resolve a username to a user id before calling
  `POST /projects/{id}/members`. New test:
  `test_non_admin_can_look_up_a_username_but_not_list_all_users`. "Add
  collaborator" button next to "Reassign owner"/"Archive project"
  (same owner-or-admin gate), a modal taking a username, resolving it
  via the lookup endpoint, then adding the membership. Verified end to
  end as an admin adding `u-bob` to a project, confirmed in the database
- [x] `CLIENT_INSTALL.md`/`DEPLOYMENT.md` already document the
  `create_sysadmin.py` bootstrap step and `SYSADMIN_INITIAL_PASSWORD`
  in their setup checklists (CLIENT_INSTALL.md section 5a, DEPLOYMENT.md
  section 3) — found already complete when reviewed, not new work
- [x] `USER_GUIDE.md` already has a "Signing in and roles" section
  covering the three roles, disabled-account/session behavior, and the
  owner-must-be-a-Power-User rule, plus a "Known limitations" section
  cross-referencing the still-open items above — found already complete
  when reviewed, not new work

**Exit criteria:**

- [x] A disabled user cannot log in; an already-open session is
  rejected on its next request (not instantly)
- [x] A Power User can create a project (auto-owner), add collaborators
  to it, and delete/archive it; a non-owner collaborator cannot
- [x] A `user`-role account can do project working-capability actions
  (upload, process, calculate, ask questions) but never archive/purge,
  anywhere
- [x] The last active Admin cannot be disabled or deleted; a user who
  still owns a project cannot be disabled or deleted until ownership is
  reassigned
- [x] UI role-gating and Playwright coverage are complete (all work
  items above are done; Playwright verified by an actual run — 22/22
  passing — not just by reading the code)

### Phase 16 - Multi-Tenant Foundation (schema only)

**Objective:** Raised in conversation (2026-09-20) as a hybrid business model
not covered by ADR-002's dedicated-install assumption: a customer whose
infrastructure is entirely vendor-provided and vendor-operated, but
dedicated to that one customer (no `Tenant` concept needed — it's still one
install), versus vendor-operated infrastructure shared across several
subscribing customers at once, each one a `Tenant`, with no data shared
between them. See DECISIONS.md ADR-010 for the full analysis and why one
schema serves both cases plus the original dedicated-install model, rather
than three different data models. This phase is schema and bootstrap only —
it deliberately does not turn on any isolation, and is not safe to run a
shared instance on by itself.

**Work items:**

- [x] Add the `tenants` table and a nullable `tenant_id` on `users`,
  `clients`, and `projects` (migration `0019_add_tenants`)
- [x] `create_sysadmin.py` creates a default tenant and backfills every
  pre-existing user/client/project onto it, so a dedicated install behaves
  exactly as it did before this existed — verified end-to-end against a
  scratch database (creates the tenant, backfills pre-existing rows,
  idempotent on a second run)
- [x] Regression test proving the schema round-trips through the ORM
  (`backend/tests/test_models.py::test_tenant_scopes_users_clients_and_projects`)
- [x] A `platform_admin` role above today's install-wide `admin` (2026-09-20):
  a strict superset — everywhere `admin` bypasses a per-project/per-install
  restriction, `platform_admin` does too (`auth.py`'s `ADMIN_TIER_ROLES`,
  used by `require_admin`, `is_project_member`, `is_project_owner`,
  `require_project_owner`, the "last active admin" safety net, and every
  admin-vs-everyone-else list-scoping check in `routes.py`). A new
  `require_platform_admin` dependency exists for platform-only actions but
  is not yet used by any route (nothing needs it until tenant provisioning).
  No migration needed — `role` is an unconstrained string (ADR-009). No
  frontend change either: `platform_admin` isn't exposed in any role picker
  yet, since it has no user-visible effect until query scoping (below)
  exists to actually cross a tenant boundary with it. A dedicated install
  has no reason to ever create one, and none of the 134 existing tests
  changed behavior. Regression tests: `test_platform_admin_is_a_superset_of_admin`,
  `test_last_active_admin_protection_spans_both_admin_tier_roles`.

**Explicitly not done in this phase** (see DECISIONS.md ADR-010's
Consequence) — each is its own follow-on phase, not a checklist item here:

- [ ] Scope every list/read query by `tenant_id` (the real isolation
  enforcement; comparable in size to Phase 15's ~34 permission call sites,
  but a missed one is a cross-*customer* leak, not a contained permission
  bug). `platform_admin` from the item above is what such scoping would
  exempt from the `tenant_id` filter, the same way `admin` is exempted from
  today's project-ownership filters
- [ ] Move `username` uniqueness from global to per-`(tenant_id, username)`
  (or switch to email as the identifier) — required before a second tenant
  can share the instance, since two different customers could otherwise
  collide on a username
- [ ] Postgres Row-Level Security as a database-enforced backstop for the
  shared-instance case specifically (not needed for a dedicated instance)
- [ ] A tenant provisioning flow (create a new tenant + its first admin) and
  any billing/subscription metadata — not needed until a second tenant
  actually exists on a shared instance

**Exit criteria:**

- [x] A dedicated install (single tenant, backfilled automatically) behaves
  identically to before this phase — no endpoint, permission check, or test
  changed behavior
- [ ] Deliberately open until a follow-on phase closes it: nothing yet
  enforces tenant isolation, so this phase alone does not make a
  shared-instance deployment safe

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
2. **Phase 13 optional - archive/project file compression**: lowest
   urgency of the deferred work — no reported pain point yet, and
   project-level compression is a bigger change than file-level since
   project archival doesn't touch storage at all today.
3. **Phase 14 - Question-Answering Coverage Expansion** (not yet
   scoped): found via a manual audit against `TestQuestions`; closes
   real gaps in what the Q&A endpoint can answer (see the phase entry
   above for the full breakdown).

Everything below is unprioritized relative to each other and to the
items above:

1. Expand CAD support to DWG and richer Civil 3D entities.
2. Improve PDF plan-set vision, OCR, title-block, viewport, and callout extraction.
3. Add contours, TIN surfaces, alignments, and profile analysis.
4. Add stormwater, earthwork, structural, and pipe-network calculation modules.
5. Add embeddings and semantic search for large document collections.
6. Add billing and a full audit-event history. (Multi-user authentication, roles, and per-project ownership/permissions shipped as Phase 15 — see DECISIONS.md ADR-009. Multi-*tenant* SaaS, i.e. one shared instance serving multiple separate firms, is a distinct, larger consideration — see item 10 below.)
7. Add cloud storage while retaining a local-storage deployment option.
8. Add Sentry, PostHog, and centralized logging after the core workflow is stable.
9. Package as an installable desktop app (e.g. Electron) instead of a
   terminal-run local deployment — raised in conversation, no reported
   need yet. The frontend/backend source itself has no OS-specific code
   (Next.js, FastAPI, Shapely, and PyProj are all cross-platform, and a
   grep of `backend/src` and `frontend/app` turned up no hardcoded
   Windows paths or `platform`/`win32` checks), so the app is expected to
   run on macOS/Linux already for anyone willing to set it up manually
   there. It's only the *documented, verified* setup (VERIFY.md,
   DEPLOYMENT.md) and the packaging story that are Windows-only and
   Windows-manual today. A desktop-installer effort would need to: pick
   one OS's install experience first (or all three), bundle/auto-launch
   the Python backend, and either bundle PostgreSQL/PostGIS per OS or
   switch to an embedded database (e.g. SQLite+SpatiaLite) the
   calculation engine and tests would need to be re-verified against.
   This item is also what would replace [CLIENT_INSTALL.md](CLIENT_INSTALL.md)'s
   manual, interim client-site install procedure with a single installer.
10. **`Tenant` entity for a hybrid dedicated/shared-instance business
    model** — schema and bootstrap foundation shipped as Phase 16
    (2026-09-20); see that phase entry above and DECISIONS.md ADR-010 for
    the full analysis of why one schema serves a customer's own dedicated
    install (ADR-002), a vendor-operated-but-still-dedicated install, and
    a vendor-operated instance shared across several subscribing
    customers. Real tenant-isolation *enforcement* is not part of Phase
    16 and remains here as later, larger follow-on work, roughly in order
    of what a shared instance would need first:
    - Scope every list/read query by `tenant_id` — comparable in size to
      Phase 15's ~34 permission call sites, but a missed one here is a
      cross-*customer* data leak rather than a contained permission bug.
      (The `platform_admin` role this scoping would exempt already exists,
      shipped 2026-09-20 — see the phase entry above.)
    - Move `username` uniqueness from global to per-`(tenant_id,
      username)`, or switch to email as the identifier — required before
      a second tenant can safely share an instance.
    - Postgres Row-Level Security as a database-enforced backstop for the
      shared-instance case specifically (a dedicated instance doesn't
      need it — the OS/database separation, or simply having only one
      tenant row, already provides it).
    - A tenant provisioning flow and billing/subscription metadata — not
      needed until a second tenant actually exists on a shared instance.

## 9. Nice-to-Have Improvements

Small, optional quality-of-life items — not required for any phase's exit
criteria, not phase-gated, and not prioritized relative to each other or
to the Post-MVP Roadmap above. Pick these up opportunistically rather
than scheduling them. (Phase 13's optional archive/project file
compression is tracked in its own section above, not duplicated here.)

- DWF file support. Not DWG/DXF: DWF is Autodesk's lightweight
  publish/view format (closer to "a PDF for CAD drawings" than an
  editable drawing format), and hasn't been mentioned anywhere else in
  Requirements.md/AGENTS.md/this plan. Raised in conversation with no
  specific source-file need behind it yet; would need its own parsing
  approach separate from the DWG post-MVP item above.
- A browsing UI for the purge-history log (`GET /admin/purge-history`
  has existed since Phase 13; deliberately deferred until there's enough
  real history to know what's worth showing).
- A regression test for the file-level branch of `_sweep_expired_archives`
  (`backend/src/civil_engineering/routes.py`) — the project-level branch
  is fully tested (`test_archive_auto_purge_retention_and_history`), the
  structurally-identical file branch isn't. Noted as a coverage gap, not
  a known bug, in ReviewCommentsV.0.1.0.md.
- Investigate the pre-existing Playwright flakiness in
  `full-workflow.spec.ts`/`phase9.spec.ts` (5 tests fail against the real
  backend even on unmodified code — confirmed via `git stash` while
  fixing the issues in ReviewCommentsV.0.1.0.md). The webServer log shows
  "Slow filesystem detected... is a network drive," suggesting this
  machine's `S:` drive is the cause rather than an application defect;
  worth trying a longer test timeout or relocating `frontend/.next` to a
  local disk before assuming it's a real bug.
