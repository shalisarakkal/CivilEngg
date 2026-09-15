# Civil Engineering AI Application

A local-first application for extracting civil-engineering information from plans, CAD files, surveys, and related documents.

## Current Status

The project has working Phase 0 through Phase 8 foundations: file ingestion, extraction, a versioned site model, deterministic calculations, a workspace UI, deterministic/mock source-grounded summaries and question answering, and Phase 8 quality/security/integration hardening (structured logging, request limits, path-traversal protection, real end-to-end Playwright coverage, and a documented non-licensed review of the calculation engine). Supported MVP inputs include PDF, DXF, CSV, TXT, TIFF/TIF, LandXML, and related document files. TIFF/TIF files currently provide raster metadata; OCR is planned for a later vision phase. Phase 9 is closing remaining gaps against the original requirements before the Phase Z release; LandXML parsing (points, surface points, and straight alignment segments), DXF label-to-geometry proximity linking, narrative key-phrase extraction, and CSV bearing/distance (COGO) parsing are done, and semantic site-model classification, directional questions, and plan-sheet snippets remain:

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

## Planned Stack

- Frontend: Next.js, React, and TailwindCSS
- Backend: FastAPI and Python
- Database: PostgreSQL with PostGIS
- Engineering libraries: NumPy, SciPy, Pandas, Shapely, GeoPandas, and PyProj
- Local file storage for the initial deployment
- Playwright and backend tests for verification

## Development

Prerequisites: Node.js, npm, Python 3.12+, and `uv`. PostgreSQL with PostGIS will be required locally when database-backed features are implemented.

```powershell
Copy-Item .env.example .env
npm install
npm run lint
npm run build
npm test
```

Run database migrations after PostgreSQL/PostGIS is available:

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

Database-backed features will use a locally installed PostgreSQL/PostGIS service. The current health endpoint and tests do not require a running database.

Do not commit secrets. Use a local environment file based on `.env.example`.

## Scope Rule

Keep the first release focused on site-plan ingestion, geometry-backed measurements, and traceable answers. New capabilities should be added to [PLAN.md](PLAN.md) before implementation.
