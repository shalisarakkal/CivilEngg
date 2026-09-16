# Technology Stack

This documents what the application actually uses today, with versions read directly from the installed environment (not the aspirational stack described in early planning — see DECISIONS.md and README.md for what was deliberately not adopted and why).

## Frontend

| Technology | Version | Role |
| --- | --- | --- |
| Next.js | 16.3.5 | React framework, dev server, build |
| React / React DOM | 19.3.0 | UI rendering |
| TypeScript | 6.0.3 | Static typing |
| Plain CSS | — | Styling (`globals.css`); no CSS framework (TailwindCSS was evaluated and not adopted — see DECISIONS.md) |
| Custom SVG | — | Site-model geometry preview (`GeometryPreview` in `ProjectWorkspace.tsx`); no map library (Leaflet/Mapbox was evaluated and not adopted) |
| ESLint | 9.39.5 (with `eslint-config-next` 16.3.5) | Linting |
| Playwright (`@playwright/test`) | 1.63.0 | End-to-end browser tests |

The frontend is a single Next.js app under `frontend/`, run via npm workspaces from the repo root `package.json`.

## Backend

| Technology | Version | Role |
| --- | --- | --- |
| Python | 3.12.7 | Language runtime |
| FastAPI | 0.141.1 | Web framework / API routing |
| Uvicorn | 0.52.4 | ASGI server |
| SQLAlchemy | 2.0.52 | ORM |
| Alembic | 1.20.0 | Database migrations |
| Pydantic / pydantic-settings | 2.13.5 / 2.15.0 | Request/response schemas, environment-driven settings (`config.py`) |
| python-multipart | 0.0.32 | Multipart file-upload parsing |

## Database

| Technology | Version | Role |
| --- | --- | --- |
| PostgreSQL | 18.6 | The backend's actual default (`config.py`'s `database_url`) and what running the application locally connects to |
| PostGIS | 3.6 | Installed and migration-enabled, but not currently used for anything — geometry is stored as plain JSON (GeoJSON-like dicts), not native PostGIS geometry types; no spatial index or `ST_*` function is used |
| psycopg (binary) | 3.3.5 | PostgreSQL driver |
| SQLite | (Python stdlib, via SQLAlchemy) | Used only by the automated backend test suite and Playwright end-to-end runs, which override the database with an isolated in-memory/temp-file instance for speed and isolation — never used by the running application itself |

## Geospatial / Engineering Libraries

| Technology | Version | Role |
| --- | --- | --- |
| Shapely | 2.1.2 | Geometry validation and deterministic calculations (distance, area, perimeter) |
| PyProj | 3.8.0 | Coordinate reference system transformation |

NumPy, SciPy, Pandas, and GeoPandas were part of the original planning stack but are unused — no shipped extraction or calculation path needs them (see DECISIONS.md).

## File Parsing

| Technology | Version | Handles |
| --- | --- | --- |
| ezdxf | 1.4.4 | DXF parsing and extraction; also renders DXF-sourced plan-sheet snippets to SVG |
| pypdf | 5.9.0 | PDF text extraction |
| Pillow | 11.3.0 | TIFF/TIF raster metadata |
| Python stdlib `xml.etree.ElementTree` | — | LandXML parsing (`CoordGeom`, `AlignPIs`, `pntRef`, `Parcel`, points/surfaces) |
| Python stdlib `csv` | — | CSV parsing, including quadrant bearing/distance (COGO) courses |

No OCR library is used — TIFF and scanned/image-only PDF pages report "no extractable text" rather than attempting OCR (see RISK_REGISTER.md).

## AI

| Technology | Version | Role |
| --- | --- | --- |
| `MockAIProvider` (in-house) | — | The only implementation of the `AIProvider` interface. Deterministic: routes computable questions to Shapely/PyProj calculations, retrieves source text for explanatory answers, and never calls a real network model |

A real network-calling provider (e.g. OpenAI) is deferred; the provider interface exists to support one later without changing call sites (see RISK_REGISTER.md and PLAN.md).

## Testing & Quality

| Technology | Version | Role |
| --- | --- | --- |
| pytest | 8.4.2 | Backend unit/API/integration tests |
| httpx | 0.28.1 | Backend test HTTP client (via FastAPI's `TestClient`) |
| ruff | 0.16.7 | Backend linting and formatting |
| mypy (strict) | 1.20.2 | Backend static type checking |
| Playwright | 1.63.0 | Frontend end-to-end tests, including real-backend workflow tests with an isolated SQLite database |
| ESLint / `tsc --noEmit` | 9.39.5 / 6.0.3 | Frontend linting and type checking |

## Tooling

| Technology | Version | Role |
| --- | --- | --- |
| uv | 0.12.12 | Python dependency management and script running for the backend |
| npm (workspaces) | 11.19.0 | Node dependency management; root `package.json` orchestrates the `frontend` workspace and backend scripts via `cd backend && ...` |
| Node.js | 24.20.0 | JavaScript runtime for the frontend toolchain |

## Deployment Model

- Local-only, single-user MVP: no authentication (ADR-005 in DECISIONS.md), local file storage under a configurable directory, CORS origins configurable via `CORS_ALLOWED_ORIGINS`.
- No containerization, CI/CD pipeline, or hosting platform is configured yet (Phase Z in PLAN.md).
- No error/analytics tracking (Sentry/PostHog) or payment processing (Stripe) is integrated — these appear only as future/post-MVP items (PLAN.md's Post-MVP Roadmap), not shipped.

## Explicitly Not Used

Named in AGENTS.md's original architecture brief and/or PLAN.md's initial "Technical Direction," but not part of what's actually shipped:

- TailwindCSS — plain CSS used instead (DECISIONS.md)
- Leaflet / Mapbox — a custom SVG schematic view used instead (DECISIONS.md)
- NumPy, SciPy, Pandas, GeoPandas — no shipped path needs them (PLAN.md §3)
- Native PostGIS geometry types — plain JSON geometry used instead, despite PostGIS being installed and migration-enabled (PLAN.md §3)
- A real AI provider (OpenAI or otherwise) — a deterministic mock provider is used instead (DECISIONS.md, RISK_REGISTER.md)
- Clerk / Auth0 — no authentication is implemented; single-user local MVP (AGENTS.md, DECISIONS.md ADR-005)
- Stripe — no payment processing (AGENTS.md)
- Sentry / PostHog — no error or analytics tracking yet; listed as a post-MVP roadmap item (PLAN.md)
