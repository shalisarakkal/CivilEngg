# Verification Guide

This guide verifies the current Phase 1 through Phase 5 implementation on Windows using PowerShell and local PostgreSQL/PostGIS.

## 1. Open The Project

```powershell
Set-Location "S:\AI-Projects\Civil Engineering"
```

Confirm the repository state:

```powershell
git status --short --branch
git log --oneline --max-count=4
```

The latest committed checkpoint before the current changes is:

```text
c29a94b Complete Phase 3 extraction pipeline
```

The current Phase 4 and Phase 5 changes may be uncommitted until reviewed.

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

The backend test suite currently covers models, API workflows, PDF, DXF, CSV, TXT, TIFF extraction, site-model geometry, and deterministic calculations.

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
0005_add_calculation_results (head)
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
{"status":"ok","environment":"development"}
```

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
4. Select a `.txt`, `.csv`, `.pdf`, `.dxf`, `.tif`, or `.tiff` file.
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
  -Body '{"calculation_type":"slope","inputs":{"start_elevation":100,"end_elevation":104,"horizontal_distance":100},"unit":"ft"}'

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
- DOCX parsing is optional and not implemented unless sample requirements require it.
- Processing is synchronous for the MVP; background processing is deferred.
- Elevation lookup and elevation statistics are not yet implemented.
- Authentication is not yet enabled for the local single-user workflow.
- The real PostgreSQL migration is verified locally, but the application still requires PostgreSQL/PostGIS to be running for database-backed API checks.
