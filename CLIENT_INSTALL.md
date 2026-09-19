# Client-Site Install (Manual, Interim)

## Status

**Interim procedure.** There is no packaged installer today — see
[PLAN.md](PLAN.md) Post-MVP Roadmap item 9 ("Package as an installable
desktop app"). Once that ships, installing at a client site should mean
running one installer rather than following the steps below by hand.
This document exists to cover client-site installation until then, and
should be retired (or reduced to "see the installer") once that roadmap
item is delivered.

This is **not** the same as [DEPLOYMENT.md](DEPLOYMENT.md), which
covers turning the *development* machine into a standing local
instance. This document is for installing on a **different, fresh
machine** at a client's site that has never had the project's
prerequisites on it.

## Verification status

Everything below has only been verified on **Windows** (the same OS
this project's own instance runs on and that [VERIFY.md](VERIFY.md) is
written against). The application's own source code has no
Windows-specific logic (no hardcoded paths, no `platform`/`win32`
checks in `backend/src` or `frontend/app`), so it is expected to work
on macOS/Linux with the equivalent steps, but that has **not been
tested**. Treat a macOS/Linux install as unverified until someone
actually runs it end to end there.

## Minimum requirements

### Hardware (practical estimate, not benchmarked)

- A single machine to host both the frontend and backend (per the
  MVP's single-machine, single-user scope — ADR-002/ADR-005 in
  DECISIONS.md)
- 4 GB RAM minimum, 8 GB recommended (Node.js build/dev server +
  Python backend + PostgreSQL running concurrently)
- Disk space: enough for PostgreSQL itself, plus uploaded source files
  and their processed data under `LOCAL_STORAGE_PATH` — size this
  against the client's expected file volume (uploads are capped at 50
  MB each; there is no total-storage cap)

### Software

| Requirement | Minimum version | Notes |
| --- | --- | --- |
| OS | Windows 10/11 | Verified. macOS/Linux believed compatible, unverified (see above) |
| Node.js | 24.x | This project's own instance runs 24.20.0 — see TECHNOLOGY.md |
| npm | bundled with Node.js | Used for workspace scripts |
| Python | 3.12 or later | Backend `pyproject.toml` requires `>=3.12` |
| uv | latest | Python dependency management/script runner for the backend |
| PostgreSQL | 18.x, with the PostGIS extension (3.6) enabled | This is the database the running application actually connects to — see VERIFY.md section 3 |

There is no internet dependency at runtime: the AI provider is a
deterministic mock that makes no network calls (ADR-006 in
DECISIONS.md). Internet access is only needed during install, to
download the prerequisites above and the project's own dependencies.

## Install procedure

Run as an administrator/local account with permission to install
software and create Windows services.

### 1. Install prerequisites

- Install Node.js 24.x (includes npm)
- Install Python 3.12+
- Install `uv` (see https://docs.astral.sh/uv/getting-started/installation/)
- Install PostgreSQL 18 with the PostGIS extension. During setup:
  - Create a database and role for the application (the project's own
    defaults are database `civil_engineering`, role `civil_engineering`
    — reuse these names unless there's a reason not to, since they're
    what `.env.example`'s `DATABASE_URL` already assumes)
  - Enable PostGIS on that database:
    ```sql
    CREATE EXTENSION IF NOT EXISTS postgis;
    ```
  - Set the role's password to something client-specific — **do not**
    reuse the `civil_engineering`/`civil_engineering` development
    default (see DEPLOYMENT.md section 4)
  - Confirm PostgreSQL is running as a Windows service set to start
    automatically (`Get-Service postgresql*` should show `Running` /
    `Automatic`, matching VERIFY.md section 3)

### 2. Build a distribution package (on your own machine, not the client's)

The full git repository also contains developer-only material that the
running application never reads: root-level planning docs (`PLAN.md`,
`ARCHITECTURE.md`, `DATA_MODEL.md`, `API.md`, `TESTING.md`,
`RISK_REGISTER.md`, `DECISIONS.md`, `CHANGELOG.md`, `Requirements.md`,
`TECHNOLOGY.md`, `ReviewCommentsV.0.1.0.md`, `AGENTS.md`), the
`backend/tests` and `frontend/tests` suites, `frontend/playwright.config.ts`,
`frontend/AGENTS.md`/`frontend/CLAUDE.md`, `frontend/eslint.config.mjs`,
and `backend/README.md`. None of it is needed to run the app, and there's
no reason for a client's machine to end up with your internal ADRs,
risk register, or code-review notes on its disk. `git clone` is still
fine as a fallback if you'd rather not bother trimming, but the
following gives a clean, minimal package to zip and hand over instead.

From a clean checkout on your own machine, copy only these paths into a
new folder (e.g. `civil-engineering-dist/`), preserving the directory
structure:

```text
civil-engineering-dist/
├── package.json
├── package-lock.json
├── .env.example
├── backend/
│   ├── alembic.ini
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── migrations/
│   ├── scripts/
│   └── src/
└── frontend/
    ├── package.json
    ├── next.config.ts
    ├── tsconfig.json
    └── app/
```

In PowerShell:

```powershell
$dist = "civil-engineering-dist"
New-Item -ItemType Directory -Force "$dist\backend", "$dist\frontend" | Out-Null

Copy-Item package.json, package-lock.json, .env.example -Destination $dist

Copy-Item backend\alembic.ini, backend\pyproject.toml, backend\uv.lock -Destination "$dist\backend"
Copy-Item backend\migrations, backend\scripts, backend\src -Destination "$dist\backend" -Recurse

Copy-Item frontend\package.json, frontend\next.config.ts, frontend\tsconfig.json -Destination "$dist\frontend"
Copy-Item frontend\app -Destination "$dist\frontend" -Recurse

Compress-Archive -Path $dist -DestinationPath "civil-engineering-dist.zip" -Force
```

Transfer `civil-engineering-dist.zip` to the client machine (removable
media, secure file transfer — whatever fits the client's environment)
and extract it to wherever you want the application to live, e.g.
`C:\CivilEngineeringApp\`.

Sanity-check the extracted folder against the tree above before moving
on — a missing `uv.lock` or `migrations` folder will surface as a
confusing failure several steps later rather than an obvious one here.

**Verified 2026-09-17:** this exact manifest (no `eslint.config.mjs`,
no `tests/`) was assembled in an isolated folder and both `npm run
build` (frontend production build, including its TypeScript check) and
`uv run alembic current` (backend, against this project's real
database) completed successfully from it alone.

A ready-to-run copy of the assembly script above lives at
`S:\Civill-Beta\build-dist.ps1` on the primary dev machine (run it with
no arguments to rebuild `civil-engineering-dist.zip` there). It's kept
outside this repository by choice, so it is **not version-controlled**
alongside this file — if the required-file list above ever changes,
that script must be updated by hand to match; it will not update
itself. The inline script above is the source of truth for what the
manifest should contain.

### 3. Install dependencies

From the project root:

```powershell
npm install
```

The backend's Python dependencies are installed automatically by `uv`
the first time a `uv run` command executes (no separate install step).

### 4. Configure the environment

```powershell
Copy-Item .env.example .env
```

Edit `.env`:

- `DATABASE_URL` — point at the database/role/password created in step 1
- `APP_ENV=production`
- `CORS_ALLOWED_ORIGINS` — the exact origin the frontend will actually
  be served from on this machine (e.g. `http://localhost:3000`, or the
  machine's hostname/IP if accessed from other devices on the client's
  network)
- `NEXT_PUBLIC_API_URL` — the backend's actual address, matching
  whatever host/port it's started on
- `LOCAL_STORAGE_PATH` — a durable location on this machine, sized per
  the client's expected upload volume; this is what needs backing up
  (see DEPLOYMENT.md section 6)

Full checklist: DEPLOYMENT.md section 4.

### 5. Apply database migrations

```powershell
npm run db:upgrade
```

Verify it landed on the expected head (see VERIFY.md section 3 for the
current expected revision — check this project's own `backend/migrations`
for the latest if it's changed since).

### 5a. Create the first admin account

```powershell
cd backend
$env:SYSADMIN_INITIAL_PASSWORD = "<a real password, not the example below>"
uv run python scripts/create_sysadmin.py
Remove-Item Env:SYSADMIN_INITIAL_PASSWORD
cd ..
```

Creates the `sysadmin` account (role: Admin) used to log in and create
the client's real user accounts. `SYSADMIN_INITIAL_PASSWORD` is a
one-shot shell variable, never written to `.env` or any file — unset it
immediately after, as shown above.

### 6. Build and start

```powershell
npm run build
npm run start
```

In a separate terminal:

```powershell
npm run start:backend
```

Confirm the backend is healthy:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health | ConvertTo-Json -Compress
```

Expected: `{"status":"ok","environment":"production","database":"ok"}`

### 7. Keep it running

There is no service wrapper yet. Keep both processes running via
Windows Task Scheduler (run-at-startup tasks) or dedicated always-on
terminals — same approach as DEPLOYMENT.md section 5.

### 8. Set up backups

Follow DEPLOYMENT.md section 6 (`backend/scripts/backup.py`) on this
machine, on a cadence matched to the client's acceptable data-loss
window. Do this **before** the client starts putting real data in —
verify a backup/restore cycle actually works on this machine, not just
on the development machine.

## Known gaps in this procedure

- No installer: every step above is manual and assumes command-line
  comfort. This is exactly what PLAN.md's desktop-packaging roadmap
  item is meant to remove.
- No automated smoke test at the end of install — manually create a
  project, upload a sample file, and confirm it processes, as a final
  check (see VERIFY.md section 4 onward for the shape of that check).
- No uninstall procedure documented (stopping the services/tasks,
  dropping the database, removing `LOCAL_STORAGE_PATH`) — write one
  before this is used for a real client engagement that might need it.
