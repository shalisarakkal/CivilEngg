# Civil Engineering AI Application

A local-first application for extracting civil-engineering information from plans, CAD files, surveys, and related documents.

## Current Status

The project is in planning and documentation. The implementation will begin with a small vertical slice:

1. Create a project.
2. Upload a supported file.
3. Store file metadata locally.
4. Process the file and report its status.
5. Display extracted data.
6. Run a deterministic measurement.

See [PLAN.md](PLAN.md) for phases and acceptance criteria.

## Documentation

- [Requirements.md](Requirements.md) - product capabilities and input requirements
- [PLAN.md](PLAN.md) - development phases and definition of done
- [ARCHITECTURE.md](ARCHITECTURE.md) - system structure and processing flow
- [DATA_MODEL.md](DATA_MODEL.md) - initial entities and relationships
- [API.md](API.md) - initial API contract
- [TESTING.md](TESTING.md) - testing strategy
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

The exact setup commands will be added during Phase 1. Do not commit secrets. Use a local environment file based on the future `.env.example`.

## Scope Rule

Keep the first release focused on site-plan ingestion, geometry-backed measurements, and traceable answers. New capabilities should be added to [PLAN.md](PLAN.md) before implementation.
