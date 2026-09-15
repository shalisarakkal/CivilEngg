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

## ADR-005: No Authentication for the MVP; Single-User Local Deployment

- **Status:** Accepted
- **Date:** 2026-09-15
- **Context:** Phase 8 hardening asked whether authorization boundaries were needed. The application is intended to run locally for a single user, per the Phase 0 scope decision and ARCHITECTURE.md.
- **Decision:** Ship the MVP without authentication or multi-user authorization boundaries. The API is not intended to be exposed beyond local use.
- **Consequence:** RISK_REGISTER.md records the unauthenticated local API as an accepted limitation. Authentication, authorization, and multi-user access remain post-MVP work (see the Post-MVP Roadmap).

## ADR-006: Deterministic Mock AI Provider Instead of a Live LLM Integration

- **Status:** Accepted
- **Date:** 2026-09-13
- **Context:** Requirements.md calls for an LLM-based summarization and question-answering engine. A network-calling provider introduces latency, cost, availability risk, and the possibility of an AI inventing an engineering fact that was never actually verified.
- **Decision:** Define a provider-agnostic `AIProvider` interface (`summarize`, `answer`), and ship the MVP with only `MockAIProvider`: a deterministic implementation that never makes a network call. Computable questions are routed to the deterministic calculation engine first (ADR-003); everything else is answered from retrieved source text or an explicit insufficient-data/ambiguous response, never an invented value.
- **Consequence:** Summaries and answers are limited to what the site model and extracted text can actually support — no generative narrative beyond that. A real network provider (e.g. OpenAI, per the original architecture brief in AGENTS.md), and its timeout/retry/failure handling, is deferred to a post-MVP release (see RISK_REGISTER.md).

## ADR-007: No Map Library; a Custom Lightweight Schematic View

- **Status:** Accepted
- **Date:** 2026-09-13
- **Context:** The original architecture brief (AGENTS.md) and PLAN.md's initial technical direction called for Leaflet/Mapbox GL for site-plan visualization. The MVP's site-model geometry is schematic (extracted lines/points/polygons in a local project coordinate system), not geographic map data, and most projects have no real-world basemap coordinates at all.
- **Decision:** Render extracted geometry with a small custom SVG-based component (`GeometryPreview` in ProjectWorkspace.tsx) instead of adopting a map library. Likewise, use plain CSS instead of TailwindCSS, since the workspace UI's needs didn't justify adopting a utility-CSS framework.
- **Consequence:** No basemap, tiling, panning/zooming, or geographic overlay support. If a future phase needs true geographic mapping (e.g. real-world basemaps, flood zone overlays per AGENTS.md), a map library would need to be introduced then.

## Resolved (not full ADRs)

- Database migration tool: Alembic (`backend/migrations/`).

## Proposed Decisions

- Background job mechanism
- Supported coordinate reference systems
- DWG parsing strategy
