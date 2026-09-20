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

## ADR-008: MVP Scope Freeze for Release Candidate

- **Status:** Accepted
- **Date:** 2026-09-16
- **Context:** Phase Z (PLAN.md) calls for freezing MVP scope and tagging a release candidate. Phases 0-11 and 13 are complete; Phase 12 (Activity Events) is explicitly logged as "not yet scoped" with open product decisions, and Phase 13's compression work item is explicitly optional and deferred.
- **Decision:** The MVP release candidate is Phases 0-11 plus Phase 13's core work (purge history and archive auto-purge retention), on top of the earlier vertical slice (ADR-001). Phase 12 (Activity Events), Phase 13's optional compression item, and everything in the Post-MVP Roadmap (PLAN.md section 8) are explicitly out of scope for this release.
- **Consequence:** The release candidate ships with the existing single-line status banner (no activity-event log) and without archive/project file compression. See DEPLOYMENT.md for how to run this release.

## ADR-009: Role Model, Session-Cookie Auth, and Ownership (Phase 15)

- **Status:** Accepted
- **Date:** 2026-09-17
- **Context:** ADR-005 deferred authentication entirely for the MVP. A real client-site install (CLIENT_INSTALL.md) is one shared, unauthenticated instance with no way to tell users apart — requested directly as the next piece of work, not found via audit. DEPLOYMENT.md already flagged that moving to multi-user changes the trust boundary and needs its own ADR.
- **Decision:**
  - **Three roles:** `admin` (everything, every project, user management), `power_user` (full capabilities — including archive/purge — scoped to projects they own or are a member of; auto-becomes owner of a project they create), `user` (project working capabilities — upload, process, calculate, ask questions — but never archive/purge, anywhere).
  - **Ownership** is a single FK, `Project.owner_id` (not a flag on the membership table), to avoid two sources of truth. A project's owner must be a `power_user`. Deleting/archiving a project and managing its membership are owner(+admin)-only; file-level archive/purge within a project is available to any associated `power_user`, not just the owner.
  - **Auth mechanism:** server-side sessions (`sessions` table), an opaque UUID as both the row id and the httpOnly cookie value, `bcrypt` password hashing. Chosen over JWTs since it needs no separate revocation-list mechanism — disabling a user or logging out just marks/deletes the session row, checked on every request via `get_current_user`.
  - **Validation stays app-layer, not DB-layer:** `role` is a plain `String` column (not a DB enum) validated by a Pydantic `Field(pattern=...)`, matching every other status-like field already in this codebase (`SiteModelEntity.validation_status`, `CalculationResult.calculation_type`) rather than introducing a new convention. `Project.owner_id` is nullable at the DB level — required-on-create is enforced in the route, not a `NOT NULL` constraint — since existing project rows predate the `users` table and no user exists yet at migration time to backfill onto (a one-time bootstrap script backfills them onto the seeded `sysadmin` account after migration).
  - **`purge_history.purged_by_user_id`** stores the purged resource's owner *at the time of purge* (not literally who clicked purge — an automatic retention sweep isn't a click), since the project's own ownership row disappears along with it once purged, and a Power User otherwise has no way to find their own purge history for a fully-deleted project.
- **Consequence:** Every existing route gained a permission dependency (`require_admin`/`require_project_member`/`require_project_archive_rights`/`require_project_owner`). The 11 pre-existing backend test files needed a one-line `get_current_user` override each (`tests/auth_helpers.py`) to keep testing business logic unaffected by the new permission layer, rather than a full auth-flow retrofit. The frontend gained its first React context, first shared fetch wrapper, and first client-side route (`/login`) — none of which existed before. UI-level role-gating (hiding buttons a role can't use) and Playwright e2e coverage are not yet complete; see PLAN.md Phase 15's open work items. RISK_REGISTER.md's "Unauthenticated local API" row is updated from "Accepted limitation" to "Mitigated."

## ADR-010: A `Tenant` Entity for a Hybrid Dedicated/Shared-Instance Business Model (Phase 16, foundation only)

- **Status:** Accepted (schema only — see Consequence)
- **Date:** 2026-09-20
- **Context:** Multi-tenant SaaS was studied and deliberately not started after Phase 15 shipped (2026-09-18; see the former "Proposed Decisions" entry this ADR replaces), on the assumption it meant trading ADR-002's dedicated-install-per-firm isolation for a single shared hosted instance. Discussion on 2026-09-20 identified a second, additive business model that doesn't require that trade at all: a single customer whose infrastructure (backend, frontend, database, storage) is entirely vendor-provided and vendor-operated, but is *dedicated to that one customer* — no different from today's dedicated install except who runs the servers. A third model layers on top of that: the same vendor-operated infrastructure serving *several* subscribing customers at once, each one a `Tenant`, with no data shared between them. The first two models need no `Tenant` concept at all (isolation is already the whole install); the third does, and is the original SaaS case with the isolation requirement fully back in force. Since a customer may move between models over time (a vendor-operated dedicated instance is the natural upsell path to a shared one, and the reverse — a shared-instance customer outgrowing it into their own dedicated instance — is just as real), building two different schemas for "has a tenant" vs. "doesn't" would mean migrating a customer's data between two data models to change deployment topology.
- **Decision:**
  - **One schema serves all three models.** A `Tenant` table is added now; `tenant_id` (nullable) is added to `User`, `Client`, and `Project`. A dedicated install — whether the customer's own infrastructure (ADR-002) or vendor-operated-but-dedicated — has exactly one `Tenant` row, created automatically at bootstrap (`backend/scripts/create_sysadmin.py`) and never exposed to that customer. A shared instance has one `Tenant` row per subscribing customer. The application code is identical in every case; only how many `Tenant` rows exist in the database differs, which is an operational/provisioning decision, not a code branch.
  - **Isolation rigor is deliberately NOT part of this phase.** No query anywhere is yet scoped by `tenant_id`, and no route exists to create, list, or manage a `Tenant`. This phase only proves the schema and the backfill path (see Consequence) — it is explicitly not safe to run a shared instance on this alone. See PLAN.md Phase 16's follow-on work items for what closes that gap (query scoping across every list/read endpoint, `username` uniqueness moving from global to per-`(tenant_id, username)`, a platform-admin role tier above today's install-wide `admin`, and Postgres Row-Level Security as a database-enforced backstop for the shared-instance case specifically — not needed for a dedicated instance, where the OS/database separation, or simply having only one tenant row, already provides it).
  - **Naming and hierarchy**, confirmed as originally studied: `Tenant` sits above `Client` (`Tenant → Client → Project`), and above `User`. `Client` keeps its existing meaning ("the engineering firm's own customer," e.g. a city) — it is not renamed or repurposed to mean tenant, avoiding the collision risk flagged in the original study.
- **Consequence:** `Tenant` model, migration `0019_add_tenants`, and `create_sysadmin.py`'s tenant-creation/backfill logic are the only things this ADR covers. Every existing list/read query is unaudited for tenant scoping and must not be assumed to enforce any isolation boundary yet — RISK_REGISTER.md carries this as an explicit open item so it isn't mistaken for done. Enforcement, the platform-admin split, and Row-Level Security are separate, larger follow-on phases, sized similarly to or larger than Phase 15 (that added a permission *layer* on unchanged data; this partitions the data itself, so a missed scoping check is a cross-*customer* leak rather than a contained permission bug).

## Resolved (not full ADRs)

- Database migration tool: Alembic (`backend/migrations/`).

## Proposed Decisions

- Background job mechanism
- Supported coordinate reference systems
- DWG parsing strategy
