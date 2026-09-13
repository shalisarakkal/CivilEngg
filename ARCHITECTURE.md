# System Architecture

## Goal

Provide a local-first workflow that converts engineering source files into a traceable site model, deterministic calculations, and source-grounded explanations.

## Logical Components

### Frontend

Next.js and React provide project management, uploads, processing status, map or drawing inspection, calculation forms, summaries, and question answering.

### API

FastAPI exposes project, file, processing, site-model, calculation, summary, and question endpoints. The API validates inputs and coordinates the application services.

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

- PostgreSQL stores application records, revisions, calculation results, and geometry.
- PostGIS stores spatial data and supports geometry operations.
- Local storage holds uploaded and generated files.
- File metadata stores checksums, type, size, status, and source references.

## Data Flow

```text
User
  -> Frontend
  -> FastAPI API
  -> Project/File Services
  -> Local Storage + PostgreSQL/PostGIS
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
