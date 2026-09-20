# Deployment

This covers running the application as a standing local deployment, as
distinct from the `--reload`/`next dev` developer workflow in the main
[README.md](README.md). See [PLAN.md](PLAN.md) Phase Z and
[DECISIONS.md](DECISIONS.md) for the decisions behind this.

## 1. Scope

Per ADR-002 and ADR-005 in DECISIONS.md, the MVP is a **local
deployment**: one instance on one machine, no multi-tenant or
multi-host setup. Phase 15 (ADR-009) added authentication and a
role/ownership model on top of that — this remains single-machine, but
is no longer single-user. Because of that:

- There is no cloud/hosting configuration in this document — the "frontend
  and backend hosts" work item from PLAN.md Phase Z is not applicable to a
  single local machine. If a future release moves to a hosted or multi-user
  deployment, that decision needs its own ADR, and this document should be
  revisited alongside it (host/CORS config, secrets management, and the
  authentication boundary all change).
- "Deployment" below means running the built application persistently on
  the same machine used for development, not shipping it elsewhere.

## 2. Prerequisites

Same as development (see README.md), plus PostgreSQL/PostGIS actually
running as a service rather than started ad hoc — see VERIFY.md section 3
for how this project verifies that setup (Windows service, `psql` at
`S:\Program Files\PostgreSQL\18\bin\psql.exe`, database/user
`civil_engineering`, PostGIS extension enabled).

The `civil_engineering` role also needs `CREATEDB` so that testing
`restore.py` (section 6) can create and drop a disposable scratch
database instead of restoring into the real one. Grant it once, as the
`postgres` superuser:

```powershell
& "S:\Program Files\PostgreSQL\18\bin\psql.exe" -h localhost -U postgres -d postgres `
  -c "ALTER ROLE civil_engineering CREATEDB;"
```

This isn't needed for normal application operation (the app itself never
creates databases) — only for exercising the restore script against a
throwaway database rather than production data.

## 3. One-time setup

```powershell
Copy-Item .env.example .env
```

Edit `.env` per the checklist in section 4 below, then apply migrations:

```powershell
npm run db:upgrade
```

Then create the first admin account (Phase 15) — this is a one-time step,
a no-op if `sysadmin` already exists:

```powershell
cd backend
$env:SYSADMIN_INITIAL_PASSWORD = "<a real password, not the example below>"
uv run python scripts/create_sysadmin.py
Remove-Item Env:SYSADMIN_INITIAL_PASSWORD
cd ..
```

This also backfills any project that predates Phase 15 (no owner) onto
the new `sysadmin` account — reassign real ownership to a Power User
account afterward via `PATCH /projects/{id}/owner` — and creates a
default tenant (Phase 16), backfilling every pre-existing user/client/
project onto it. See DECISIONS.md ADR-010 and RISK_REGISTER.md: this is
schema/bootstrap only and doesn't change anything about running a single,
dedicated instance.

## 4. Environment and secrets checklist

- `.env` is already gitignored (`.gitignore`) — never commit it. Only
  `.env.example` (with placeholder values) belongs in source control.
- Change `DATABASE_URL`'s password away from the `civil_engineering`/
  `civil_engineering` development default before leaving the MVP's
  single-machine, single-user trust boundary in any way (e.g. if the
  machine is shared or network-reachable).
- Set `APP_ENV=production` for a deployed run.
- Review `CORS_ALLOWED_ORIGINS` — it must list the exact origin the
  frontend is actually served from.
- Point `LOCAL_STORAGE_PATH` at a durable location you intend to back up
  (see section 6); it defaults to `./storage` relative to wherever the
  backend process starts.
- `SYSADMIN_INITIAL_PASSWORD` is not a `.env` setting — it's only ever
  passed as a one-shot shell environment variable to
  `create_sysadmin.py` (section 3) and unset immediately after, never
  written to a file.
- There are no other secrets today: the AI provider is a deterministic
  mock that makes no network calls (ADR-006), so there's no API key to
  manage yet. That changes if/when a real provider is integrated
  post-MVP — this checklist should grow an entry for it then.

## 5. Running the deployed build

Build and start the frontend in production mode:

```powershell
npm run build
npm run start
```

Start the backend without the dev auto-reloader, in its own terminal:

```powershell
npm run start:backend
```

This binds the backend to `127.0.0.1:8000` (local-only, matching the
single-user scope in section 1). The frontend serves on port 3000 by
default; see README.md for changing either port.

Keep both processes running (e.g. as scheduled tasks or in dedicated
terminals) for a standing local deployment.

## 6. Backup and restore

The database and local file storage must be backed up and restored
**together**: `SourceFile` rows reference paths under
`LOCAL_STORAGE_PATH`, so pairing a database snapshot with storage from a
different point in time can leave dangling file references. Two scripts
under `backend/scripts/` handle both in one step:

```powershell
cd backend
uv run python scripts/backup.py
```

Writes a timestamped folder under `backend/backups/` (gitignored)
containing `database.dump` (`pg_dump -Fc`) and a copy of the storage
directory. Restore with:

```powershell
uv run python scripts/restore.py backups/20260916T153000Z --pg-user postgres
```

**Always pass `--pg-user postgres`** (or whichever role owns the PostGIS
extension in your database). The dump includes PostGIS's own objects
(the `postgis` extension and its `spatial_ref_sys` table), which are
owned by whoever created that extension — normally the `postgres`
superuser, not the app's `civil_engineering` role — and `--clean`
restores need to drop and recreate them. Restoring as the app's own role
fails partway through with `must be owner of extension postgis` /
`permission denied for table spatial_ref_sys`; the application tables
themselves (`projects`, `source_files`, etc.) restore fine either way,
so this only bites once PostGIS-owned objects are involved. `pg_restore`
prompts for that role's password on the terminal if `PGPASSWORD` isn't
already set for it — never put a superuser password in `.env` or pass it
as a script argument.

This is destructive by design (`pg_restore --clean --if-exists`) and
refuses to overwrite a non-empty storage directory unless you pass
`--force`. Both scripts refuse to run against a non-PostgreSQL
`DATABASE_URL`, so they can't be pointed at the automated test database
by mistake.

If `pg_dump`/`pg_restore` aren't on `PATH`, pass `--pg-dump`/
`--pg-restore` with the full path (they live alongside `psql.exe`, e.g.
`S:\Program Files\PostgreSQL\18\bin\pg_dump.exe`).

**Verified 2026-09-16** against a real backup of the production database
(23 projects, 201 source files, 244 MB of storage) restored into a
disposable scratch database and storage directory — both the row counts
and the file count matched afterward. To repeat that verification
without touching real data (requires `CREATEDB` on the `civil_engineering`
role — section 2):

```powershell
& "S:\Program Files\PostgreSQL\18\bin\createdb.exe" -h localhost -U civil_engineering civil_engineering_restore_test
$env:DATABASE_URL = "postgresql+psycopg://civil_engineering:<password>@localhost:5432/civil_engineering_restore_test"
$env:LOCAL_STORAGE_PATH = "$env:TEMP\restore_test_storage"
uv run python scripts/restore.py backups/20260916T153000Z --pg-user postgres
# ...inspect the scratch database/storage, then clean up:
Remove-Item Env:DATABASE_URL, Env:LOCAL_STORAGE_PATH
& "S:\Program Files\PostgreSQL\18\bin\dropdb.exe" -h localhost -U civil_engineering civil_engineering_restore_test
Remove-Item -Recurse -Force "$env:TEMP\restore_test_storage"
```

There's no built-in scheduler in this app (see PLAN.md Phase 12's
objective for why lazy sweeps are preferred over adding one) — run
`backup.py` on a cadence that fits how much data you can afford to lose,
via Windows Task Scheduler or manually before risky operations (bulk
purges, migrations).

## 7. Migrations

Always back up (section 6) before running a migration against real data:

```powershell
npm run db:upgrade
```

Alembic migrations in this project are written and tested forward-only;
there's no rollback testing, so treat a backup as the actual rollback
plan rather than `alembic downgrade`.

## 8. Release process

See DECISIONS.md for the MVP scope-freeze ADR. A release candidate is a
git tag on `main` once the scope-freeze ADR is recorded and this document
reflects how to actually run that tag's code.
