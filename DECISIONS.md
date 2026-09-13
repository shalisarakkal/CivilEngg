# Technical Decisions

This file records decisions that affect the project direction. Add a date, context, decision, and consequence for each new entry.

## ADR-001: Start With a Site-Plan Measurement Vertical Slice

- **Status:** Accepted
- **Date:** 2026-09-13
- **Context:** The requirements include many disciplines and file types. Implementing all of them first would delay a usable product.
- **Decision:** Start with project creation, file upload, basic extraction, site-model data, deterministic measurements, and one geometry-backed question.
- **Consequence:** Structural, stormwater, earthwork, advanced OCR, and full CAD support remain post-MVP work.

## ADR-002: Use Local File Storage Initially

- **Status:** Accepted
- **Date:** 2026-09-13
- **Context:** The project architecture specifies local storage for the initial application.
- **Decision:** Store uploaded files in a configurable local data directory and store only metadata and references in the database.
- **Consequence:** Backup, path security, retention, and future cloud-storage migration must be designed explicitly.

## ADR-003: Keep Calculations Independent From AI

- **Status:** Accepted
- **Date:** 2026-09-13
- **Context:** Engineering measurements must be reproducible and auditable.
- **Decision:** Route computable questions to deterministic calculation services. Use AI for interpretation, summarization, and explanation.
- **Consequence:** AI provider failures do not prevent core measurements, and AI answers must expose source context and limitations.

## ADR-004: Version the Site Model

- **Status:** Accepted
- **Date:** 2026-09-13
- **Context:** Reprocessing files and accepting new extraction results can change project data.
- **Decision:** Store site-model output as revisions rather than overwriting the active model without history.
- **Consequence:** APIs and calculations must identify the revision used to produce a result.

## Proposed Decisions

- Database migration tool
- Exact frontend component and map libraries
- Background job mechanism
- Authentication boundary
- Supported coordinate reference systems
- DWG parsing strategy
