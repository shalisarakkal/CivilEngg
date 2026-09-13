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

- **Frontend:** Next.js, React, TailwindCSS, and Leaflet or another compatible mapping library
- **Backend:** FastAPI with Python engineering services
- **Numerical and data processing:** NumPy, SciPy, Pandas, Shapely, GeoPandas, and PyProj as needed
- **Database:** PostgreSQL with PostGIS for project, geometry, and revision data
- **Local file storage:** A configurable local data directory, with file metadata stored in the database
- **AI:** OpenAI API behind a provider interface, with source-grounded prompts and configurable credentials
- **Testing:** Pytest for backend logic, frontend tests appropriate to the selected stack, and Playwright for end-to-end workflows
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
- [ ] A representative sample set of civil files is available for testing

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
- [ ] Selecting a result highlights the relevant geometry or source location where possible
- [x] The UI clearly distinguishes extracted, calculated, and AI-generated information
- [x] Core screens work at desktop and mobile viewport sizes
- [ ] Frontend tests cover upload state, calculation state, and error state

Phase 6 lifecycle additions:

- [x] Make revision acceptance idempotent
- [x] Archive deleted source files and preserve metadata
- [x] Preserve archived checksums for duplicate detection
- [x] Add in-app deletion confirmation
- [x] Add admin archive list, restore, and permanent purge routes/UI

### Phase 7 - Site Summaries and Source-Grounded Question Answering

**Objective:** Add useful AI assistance without allowing unsupported claims to appear as engineering facts.

**Work items:**

- [ ] Define a provider interface for OpenAI and a deterministic local/mock provider for tests
- [ ] Generate a structured site summary from the site model and extracted document text
- [ ] Add high-level, grading, drainage, and utilities summary sections when data exists
- [ ] Generate attention flags for steep slopes, tight setbacks, missing data, and unusual elevations
- [ ] Parse question intent for measurements such as setback distance and elevation
- [ ] Route computable questions to deterministic geometry calculations first
- [ ] Use retrieval of relevant source text and geometry context for explanatory responses
- [ ] Return numeric answer, units, method, source reference, confidence/limitations, and timestamp
- [ ] Clearly label unknown or insufficient-data answers
- [ ] Add prompt-injection and untrusted-document handling rules
- [ ] Store question and answer revisions without storing secrets

**Exit criteria:**

- [ ] “What is the setback distance?” can produce a calculation when the required entities exist
- [ ] AI responses cite the file/page/layer/entity context used to answer
- [ ] The system refuses to invent measurements when source data is missing
- [ ] Mock-provider tests run without network access
- [ ] Golden test cases cover correct answers, ambiguous questions, and insufficient data

### Phase 8 - Quality, Security, and Integration Hardening

**Objective:** Validate the complete workflow and prepare a reliable MVP release.

**Work items:**

- [ ] Add end-to-end Playwright coverage for create project, upload, process, inspect, calculate, and ask
- [ ] Add API integration tests using an isolated test database and file directory
- [ ] Test restart and recovery behavior for interrupted processing jobs
- [ ] Test large files, malformed files, duplicate files, and concurrent requests
- [ ] Add authorization boundaries if multi-user access is enabled
- [ ] Protect local file paths against traversal and unsafe filenames
- [ ] Validate upload limits, request limits, and AI-provider timeout behavior
- [ ] Add structured logging with correlation IDs and remove sensitive content from logs
- [ ] Add basic error monitoring and operational diagnostics
- [ ] Review calculation outputs with a civil-engineering subject-matter expert

**Exit criteria:**

- [ ] The primary workflow passes in a clean environment
- [ ] Critical failures have actionable logs and user-facing messages
- [ ] Security checks cover uploads, file access, secrets, and prompt inputs
- [ ] Engineering calculations pass subject-matter review for the supported cases
- [ ] MVP has documented known limitations and test results

### Phase 9 - MVP Release and Deployment

**Objective:** Deliver a usable, repeatable MVP with a documented operational path.

**Work items:**

- [ ] Freeze MVP scope and tag a release candidate
- [ ] Provide local deployment instructions and sample configuration
- [ ] Configure production database migrations and backup strategy
- [ ] Define local-storage backup and restore procedures
- [ ] Add deployment configuration for the selected frontend and backend hosts if needed
- [ ] Configure environment secrets outside source control
- [ ] Run a final smoke test against the deployed environment
- [ ] Publish a short user guide for supported files, units, calculations, and limitations
- [ ] Record post-MVP issues and prioritize the next release

**Exit criteria:**

- [ ] The MVP is running in the target environment
- [ ] A new project can be created and processed end to end
- [ ] Backups and recovery steps have been tested
- [ ] Deployment, configuration, and rollback steps are documented
- [ ] The server is left running and ready for user acceptance testing

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

1. Expand CAD support to DWG and richer Civil 3D entities.
2. Improve PDF plan-set vision, OCR, title-block, viewport, and callout extraction.
3. Add contours, TIN surfaces, alignments, and profile analysis.
4. Add stormwater, earthwork, structural, and pipe-network calculation modules.
5. Add embeddings and semantic search for large document collections.
6. Add multi-user authentication, permissions, billing, and audit history.
7. Add cloud storage while retaining a local-storage deployment option.
8. Add Sentry, PostHog, and centralized logging after the core workflow is stable.
