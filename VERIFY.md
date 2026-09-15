# Verification Guide

This guide verifies the current Phase 0 through Phase 6 implementation on Windows using PowerShell and local PostgreSQL/PostGIS.

## 1. Open The Project

```powershell
Set-Location "S:\AI-Projects\Civil Engineering"
```

Confirm the repository state:

```powershell
git status --short --branch
git log --oneline --max-count=4
```

The latest committed checkpoint is:

```text
e844f56 Complete Phase 0 through Phase 6 foundations
```

The repository should be clean before starting Phase 7.

## 2. Run Automated Checks

From the project root:

```powershell
npm run format:check
npm run lint
npm run typecheck
npm run build
npm test
```

Expected results:

- Ruff formatting passes
- ESLint passes
- TypeScript checking passes
- Next.js production build succeeds
- Backend tests pass

The backend test suite currently covers models, API workflows, PDF, DXF, CSV, TXT, TIFF, LandXML extraction, site-model geometry, deterministic calculations, elevation statistics, and archive lifecycle behavior.

## 3. Verify PostgreSQL/PostGIS

Check the Windows service:

```powershell
Get-Service postgresql* | Select-Object Name,Status,StartType
```

Expected:

```text
Status     : Running
StartType  : Automatic
```

The PostgreSQL client is installed at:

```powershell
& "S:\Program Files\PostgreSQL\18\bin\psql.exe" --version
```

Verify the database and PostGIS extension:

```powershell
& "S:\Program Files\PostgreSQL\18\bin\psql.exe" `
  -h localhost `
  -U civil_engineering `
  -d civil_engineering `
  -c "SELECT current_database(), current_user, PostGIS_Version();"
```

Expected:

- Database: `civil_engineering`
- User: `civil_engineering`
- A PostGIS version such as `3.6`

Check the migration head:

```powershell
Set-Location "S:\AI-Projects\Civil Engineering\backend"
uv run alembic current
```

Expected:

```text
0009_unique_source_file_checksum (head)
```

Return to the project root:

```powershell
Set-Location "S:\AI-Projects\Civil Engineering"
```

## 4. Start The Backend

Open a dedicated PowerShell terminal:

```powershell
Set-Location "S:\AI-Projects\Civil Engineering"
npm run dev:backend -- --port 8000
```

Keep this terminal running.

In another terminal, verify the health endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health | ConvertTo-Json -Compress
```

Expected:

```json
{"status":"ok","environment":"development","database":"ok"}
```

`database` reports `"unavailable"` instead of failing the request if the configured database cannot be reached.

If port `8000` is busy, use another port:

```powershell
npm run dev:backend -- --port 8002
```

Then use `http://127.0.0.1:8002` in the commands below.

## 5. Start The Frontend

Open another dedicated PowerShell terminal:

```powershell
Set-Location "S:\AI-Projects\Civil Engineering"
npm run dev -- --port 3000
```

Open this address in a browser:

```text
http://localhost:3000
```

You should see the Project Workspace screen with:

- Project creation form
- Project list
- Source-file upload area
- File status list
- Processing action

## 6. Test The UI Workflow

1. Enter a project name such as `Manual Verification Site`.
2. Select the `+` button.
3. Confirm the project appears in the project list.
4. Select a `.txt`, `.csv`, `.pdf`, `.dxf`, `.tif`, `.tiff`, or `.xml` (LandXML) file.
5. Upload it.
6. Confirm the file appears with `queued` status.
7. Select `Process`.
8. Confirm the status changes to `completed` for a readable supported file.
9. Uploading the same file again should return a duplicate-file message.
10. Try an unsupported file such as `.exe`; it should be rejected.

For TIFF/TIF files, processing currently verifies raster metadata. OCR is intentionally not enabled yet, so a warning about OCR should be recorded.

## 7. Test The API Workflow Directly

Create a project:

```powershell
$project = Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/projects" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"name":"Manual API Verification"}'

$project | Format-List
```

Create a small TXT fixture outside the repository:

```powershell
$tempFile = Join-Path $env:TEMP "civil-engineering-verification.txt"
[System.IO.File]::WriteAllText($tempFile, "FF=102.50`nTop of curb 101.80`n")
```

Upload it. This uses `curl.exe` because it handles multipart file uploads simply:

```powershell
$upload = (
  & curl.exe -sS `
    -X POST "http://127.0.0.1:8000/projects/$($project.id)/files" `
    -F "file=@$tempFile;type=text/plain"
) | ConvertFrom-Json

$upload | Format-List
```

Confirm the upload has:

- A file ID
- Original name
- Size greater than zero
- A 64-character checksum
- `queued` status

Process the file:

```powershell
$job = Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/projects/$($project.id)/files/$($upload.id)/process" `
  -Method Post

$job | Format-List
```

Expected:

```text
status : completed
```

Retrieve normalized extraction:

```powershell
$extraction = Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/projects/$($project.id)/files/$($upload.id)/extraction"

$extraction | ConvertTo-Json -Depth 8
```

Confirm that the result contains:

- `parser_name` equal to `text`
- `revision_number` equal to `1`
- Extracted source text
- A source reference containing the original filename

Try the duplicate upload:

```powershell
& curl.exe -sS -o NUL -w "%{http_code}`n" `
  -X POST "http://127.0.0.1:8000/projects/$($project.id)/files" `
  -F "file=@$tempFile;type=text/plain"
```

Expected HTTP status:

```text
409
```

Clean up the temporary file and archive the test project:

```powershell
Remove-Item $tempFile -Force
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/projects/$($project.id)/archive" `
  -Method Post | Out-Null
```

## 8. Test Site-Model Revisions And Calculations

After processing a file, accept it into a site-model revision:

```powershell
$revision = Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/projects/$($project.id)/site-model/revisions/from-extraction/$($upload.id)" `
  -Method Post

$revision | Format-List
```

Read the revision entities:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/projects/$($project.id)/site-model/revisions/$($revision.id)/entities" |
  ConvertTo-Json -Depth 8
```

Run a deterministic slope calculation:

```powershell
$calculation = Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/projects/$($project.id)/calculations" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"calculation_type":"slope","inputs":{"start_elevation":100,"end_elevation":104,"horizontal_distance":100},"coordinate_unit":"ft","unit":"ft"}'

$calculation | Format-List
```

Expected:

```text
result : 4
unit   : percent
```

The calculation response also includes its formula, inputs, assumptions, and optional source/revision references.

## 9. Review Before Commit

Stop the frontend and backend terminals with `Ctrl+C`, then from the project root run:

```powershell
git diff --check
git status --short --branch
git diff --stat
git diff
```

For new files, stage them only after reviewing:

```powershell
git add .
git diff --cached --check
git diff --cached --stat
git diff --cached
```

Do not commit generated local data, `.env`, uploads, or secrets.

## 10. Current Scope Limitations

- TIFF/TIF metadata is supported; TIFF OCR is deferred.
- LandXML parsing (Phase 9) covers `CgPoints`, surface `Pnts`/`P` points, and straight alignment `Line` segments; curved (`Curve`/`Spiral`) alignment segments and surface triangulation (`Faces`) are not extracted. The parser assumes the common "northing easting [elevation]" coordinate order (see RISK_REGISTER.md); a producer using the reverse order would silently swap X/Y.
- Label-to-geometry proximity linking (Phase 9) only covers DXF `TEXT` labels today, since those are the only extracted items that carry a per-label coordinate; it uses a fixed 10-unit distance cutoff that is not aware of the project's coordinate units (see RISK_REGISTER.md).
- Key-phrase extraction (Phase 9) scans `.txt` narrative lines and PDF page text against a fixed vocabulary of civil-engineering terms (`KEY_PHRASES` in extraction.py); it does not scan DXF/CSV/LandXML input (not narrative text) and will miss any relevant term not in that list (see RISK_REGISTER.md).
- DOCX parsing is optional and not implemented unless sample requirements require it.
- Processing is synchronous for the MVP; background processing is deferred.
- Elevation statistics are available through the calculations API.
- User deletion archives the physical file; admin restore and permanent purge are available through the archive panel/API.
- Authentication is not enabled (ADR-005): the MVP targets single-user, local-only deployment. Authorization boundaries are deferred to a future multi-user release.
- The AI provider is a deterministic mock (Phase 7): it never calls a real network model, so summaries and answers are limited to what can be computed or retrieved from the site model and extracted text. A real provider (e.g. OpenAI), and its timeout/retry handling, is deferred to a post-MVP release.
- Test fixtures are synthetic/sanitized files, not real client plan sets (Phase 0 exit criterion still open).
- Engineering calculation outputs have received a non-licensed technical review (see section 12) and automated hand-verified test coverage in `backend/tests/test_calculations.py`, but have not been reviewed by a licensed civil engineer. Treat calculation results as unverified for real engineering decisions until that review happens.
- The real PostgreSQL migration is verified locally, but the application still requires PostgreSQL/PostGIS to be running for database-backed API checks. Automated tests run against an isolated SQLite database instead.

## 11. Test Results Summary (as of Phase 8 hardening)

- Backend: `uv run pytest` — 58 tests passing (unit, API/integration, storage, processing-resilience, and operations/diagnostics tests), each using an isolated SQLite database and temporary storage directory.
- Backend: `ruff check`, `ruff format --check`, and `mypy src` all pass cleanly.
- Frontend: `npm run typecheck`, `npm run lint`, and `npm run build` all pass cleanly.
- Frontend: `npm run test:e2e` (Playwright) — 6 tests passing:
  - 4 component-level tests against a mocked API (upload, calculation, and two error states).
  - 2 true end-to-end tests against a real backend, isolated SQLite database, and local storage directory, covering create project, upload, process, inspect, calculate, select-to-highlight, ask, and request-summary; plus a refusal case with no accepted revision.
- Notable issues found and fixed while writing this coverage (see CHANGELOG.md for detail): a UI-stuck-on-network-failure bug in three form handlers, a missing status message on first-project-creation failure, a missing retry path for interrupted processing jobs, and a genuine race condition allowing concurrent duplicate uploads (fixed with a database-level unique constraint).

## 12. Calculation Engine Technical Review (Non-Licensed)

**This is a technical review performed by Claude (an AI assistant), not a licensed Professional Engineer (PE) review.** It checks that the implemented formulas match standard, textbook civil-engineering and geometry definitions, and that the automated tests actually exercise the cases they claim to. It is not a substitute for sign-off by a licensed civil engineer, and calculation results should not be relied on for real engineering, permitting, or construction decisions until that sign-off happens.

Formulas reviewed against `backend/src/civil_engineering/calculations.py`:

| Calculation | Formula used | Standard reference | Verdict |
| --- | --- | --- | --- |
| Unit conversion | Table-driven, via meters (1 ft = 0.3048 m, 1 in = 0.0254 m exactly) | International foot/inch definitions | Correct |
| Distance | Shapely `geometry.distance()` (Euclidean, planar) | Straight-line distance between projected-plane coordinates | Correct for projected (planar) coordinates. **Caveat found in this review:** nothing validates that the project's CRS is actually projected rather than geographic (lat/lon); see the new "Calculations assume planar coordinates" risk register entry |
| Area | Shapely `geometry.area` (shoelace formula) for polygons; `pi * r^2` for circles | Standard polygon and circle area formulas | Correct for projected coordinates; same planar-CRS caveat as distance |
| Perimeter | Shapely `geometry.length` (sum of segment lengths / boundary length) for lines and polygons; `2 * pi * r` for circles | Standard path-length, polygon-boundary, and circle-circumference formulas | Correct for projected coordinates, same caveat as above. An open `LineString` reports its path length, not an implicitly closed perimeter — the caller must close the ring for a true perimeter, which is deliberate and covered by both an open- and closed-path test |
| Slope | `(elevation change / horizontal distance) * 100`, with a `H:1` ratio (`horizontal_distance / abs(elevation_change)`) and an uphill/downhill/level label | `slope % = rise/run * 100`; slope ratio is the conventional civil/geotechnical "H:1" notation | Correct, matches PLAN.md's specified formula exactly |
| Elevation statistics | Minimum, maximum, arithmetic mean | Standard descriptive statistics | Correct; assumes a single consistent vertical datum and unit across the input values, which is stated in the response's `assumptions` |

Hand-verified test cases (all pass): a 3-4-5 right triangle for distance, a 10×20 rectangle for area, a rectangle for perimeter (closed and open path variants), a circle at a known radius, and a 4-in-100 slope. Each was independently recomputed by hand during this review and matches the code's output.

Gaps found and fixed during this review (before it, Phase 5's "positive, zero, negative, and boundary cases" claim in PLAN.md was not fully backed by tests):

- No test exercised a **downhill** slope (negative percent) or a **level** slope (zero percent, and confirming `slope_ratio` is `None` rather than a division-by-zero) — added.
- No test exercised **negative elevations** (e.g. below a benchmark or sea level) — added; the code already handled this correctly, it was simply untested.
- No test exercised **zero distance** between identical points, or **zero** as a boundary value for unit conversion — added.
- No test exercised rejection of a **negative** distance value passed to `convert_distance`, or a **negative** horizontal distance passed to `calculate_slope` — added.

None of these were code defects — the implementation already handled every case correctly — but the missing coverage meant that claim in PLAN.md wasn't actually verified. `backend/tests/test_calculations.py` now has 14 tests (up from 9) covering these cases explicitly.

**What this review does not cover:** whether the chosen formulas are the right ones for a specific jurisdiction's engineering code or permitting requirements, unit-conversion edge cases beyond the four supported units, or anything requiring professional engineering judgment. A licensed civil engineer should still review this file before the application is used for real project decisions.
