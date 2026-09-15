# Civil Engineering AI Application

A local-first application for extracting civil-engineering information from plans, CAD files, surveys, and related documents.

## Current Status

The project has working Phase 0 through Phase 9 foundations: file ingestion, extraction, a versioned site model, deterministic calculations, a workspace UI, deterministic/mock source-grounded summaries and question answering, Phase 8 quality/security/integration hardening (structured logging, request limits, path-traversal protection, real end-to-end Playwright coverage, and a documented non-licensed review of the calculation engine), and Phase 9's closing of the original requirements gaps. Supported MVP inputs include PDF, DXF, CSV, TXT, TIFF/TIF, LandXML, and related document files. TIFF/TIF files currently provide raster metadata; OCR is planned for a later vision phase. Phase 9 closed the remaining gaps against the original requirements before the Phase Z release: LandXML parsing (points, surface points, and straight alignment segments), DXF label-to-geometry proximity linking, narrative key-phrase extraction, CSV bearing/distance (COGO) parsing, semantic site-model classification, directional questions, and DXF plan-sheet snippets are all done. See RISK_REGISTER.md for the scope limitations accepted along the way (e.g. plan-sheet snippets are DXF-only for now).

1. Create a project.
2. Upload a supported file.
3. Store file metadata locally.
4. Process the file and report its status.
5. Display extracted data.
6. Process the source into normalized document and geometry data.
7. Accept the extraction into a site-model revision.
8. Run deterministic calculations with explicit coordinate/output units.

See [PLAN.md](PLAN.md) for phases and acceptance criteria.

## Documentation

- [Requirements.md](Requirements.md) - product capabilities and input requirements
- [PLAN.md](PLAN.md) - development phases and definition of done
- [ARCHITECTURE.md](ARCHITECTURE.md) - system structure and processing flow
- [DATA_MODEL.md](DATA_MODEL.md) - initial entities and relationships
- [API.md](API.md) - initial API contract
- [TESTING.md](TESTING.md) - testing strategy
- [VERIFY.md](VERIFY.md) - manual verification runbook
- [RISK_REGISTER.md](RISK_REGISTER.md) - MVP risks and mitigations
- [DECISIONS.md](DECISIONS.md) - recorded technical decisions
- [CHANGELOG.md](CHANGELOG.md) - notable project changes

## Stack

- Frontend: Next.js, React, and plain CSS (no styling framework); a custom SVG schematic view rather than a map library
- Backend: FastAPI and Python
- Database: SQLite for local development, automated tests, and Playwright e2e runs. PostgreSQL/PostGIS support exists (driver dependency and migration) but isn't exercised by the normal dev/test workflow — see DATA_MODEL.md and VERIFY.md section 3
- Engineering libraries: Shapely and PyProj
- AI: a deterministic mock provider that never makes a network call; a real provider integration is deferred — see RISK_REGISTER.md
- Local file storage for the initial deployment
- Playwright and backend tests for verification

## Development

Prerequisites: Node.js, npm, Python 3.12+, and `uv`. No database installation is required — the backend defaults to SQLite automatically, which is what local development, the test suite, and Playwright all use.

```powershell
Copy-Item .env.example .env
npm install
npm run lint
npm run build
npm test
```

If you're deliberately testing the PostgreSQL/PostGIS deployment path (see VERIFY.md section 3), point `DATABASE_URL` at it and run migrations:

```powershell
cd backend
uv run alembic upgrade head
```

Start the frontend with:

```powershell
npm run dev
```

Start the backend with:

```powershell
cd backend
uv run uvicorn --app-dir src civil_engineering.main:app --reload
```

The frontend runs at `http://localhost:3000` and the backend health endpoint is available at `http://localhost:8000/health`.

All database-backed features work out of the box against the default SQLite database; no separate database service needs to be running for local development or tests.

Running either server on a different port than the defaults above requires updating two settings in `.env`: `NEXT_PUBLIC_API_URL` (so the frontend calls the right backend address) and `CORS_ALLOWED_ORIGINS` (so the backend accepts requests from the frontend's actual origin).

Do not commit secrets. Use a local environment file based on `.env.example`.

## Scope Rule

Keep the first release focused on site-plan ingestion, geometry-backed measurements, and traceable answers. New capabilities should be added to [PLAN.md](PLAN.md) before implementation.
