# System Architecture

## Goal

Provide a local-first workflow that converts engineering source files into a traceable site model, deterministic calculations, and source-grounded explanations.

## Logical Components

### Frontend

Next.js and React provide project management, uploads, processing status, map or drawing inspection, calculation forms, summaries, and question answering.

### API

FastAPI exposes project, file, processing, site-model (including a plan-sheet snippet endpoint for DXF-sourced entities), calculation, summary, and question endpoints. The API validates inputs and coordinates the application services. See API.md for the current route list.

### Processing Pipeline

1. Accept and validate an uploaded file.
2. Store the file outside the source tree and record metadata.
3. Create a processing job.
4. Select a parser based on detected file type.
5. Normalize text, geometry, units, and source references.
6. Validate and persist a site-model revision.
7. Publish processing status, warnings, and errors.

### Engineering Services

The calculation engine is deterministic and independent of the AI provider. It handles unit conversion, distances, elevations, slopes, areas, and later discipline-specific calculations.

### AI Services

The AI layer receives selected site-model data and source context. Computable questions are routed to deterministic calculations first. The AI provider explains results, summarizes documents, and identifies limitations; it must not invent missing measurements.

### Data and Storage

- PostgreSQL stores application records, revisions, calculation results, and geometry when running the application locally — it's the backend's actual default (`DATABASE_URL` in `config.py`), not an opt-in deployment path. Automated backend tests and Playwright e2e runs override this with an isolated SQLite database instead, for speed and isolation.
- Geometry is stored as plain JSON (GeoJSON-like dicts), not native PostGIS geometry types; a PostGIS-enabling migration exists but no PostGIS-specific feature (spatial index, `ST_*` function) is used. All geometry operations run in application code via Shapely — see DATA_MODEL.md's Resolved Modeling Questions.
- Local storage holds uploaded and generated files.
- File metadata stores checksums, type, size, status, and source references.

## Data Flow

```text
User
  -> Frontend
  -> FastAPI API
  -> Project/File Services
  -> Local Storage + PostgreSQL (SQLite in automated tests)
  -> Processing Pipeline
  -> Normalized Site Model
  -> Calculation and AI Services
  -> Traceable Result
```

## Design Principles

- Keep calculations deterministic and testable.
- Preserve source file, page, layer, and entity references.
- Treat extracted data as uncertain until validated.
- Make units and coordinate systems explicit.
- Keep local storage configurable and replaceable.
- Isolate external AI providers behind an interface.
- Prefer simple synchronous processing initially; introduce a queue when processing time requires it.

## Initial Deployment Boundary

The first deployment is intended for local, single-user use. Authentication, billing, cloud storage, and horizontal scaling are post-MVP concerns unless Phase 0 changes this decision.
