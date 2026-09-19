<#
.SYNOPSIS
    Single control point for the Civil Engineering AI local dev servers.
    Replaces the old start-dev.ps1 (which only started servers and bolted
    a -Stop switch on top) with one script and one -Action parameter:
    Start, Stop, Restart, or Status -- each optionally scoped to just the
    backend or just the frontend.

.DESCRIPTION
    Start: checks PostgreSQL is reachable (backend only), applies
    migrations, bootstraps the sysadmin account on a fresh database, then
    launches the targeted server(s) in the background, hidden, with output
    redirected to logs\backend.log / logs\frontend.log instead of a
    visible window.

    Log versioning: every Start (including the second half of Restart)
    rotates that service's existing log to .1 first (shifting older
    numbered backups up, dropping anything beyond -MaxLogFiles), so each
    run gets a clean live file and past runs stay available. This is the
    only point logs are rotated -- true live rotation (while a server
    keeps running) would mean either fighting the file handle PowerShell's
    `*>` redirection holds open for the process's whole lifetime, or
    routing output through a custom capture layer; the latter was tried
    and dropped after it silently swallowed uvicorn's real startup/request
    logs on Windows (a process-handle-inheritance issue through
    `uv -> uvicorn --reload -> its reload worker`), which is worse than no
    rotation at all. So instead, -Action Status flags a log once it's past
    -MaxLogSizeMB as a signal to run -Action Restart for that service.

    Stop: finds whatever process actually owns each targeted port and
    kills its whole process tree (not just that one PID -- uvicorn
    --reload's multiprocessing worker in particular runs as a child of the
    PID that's actually bound to the port, and killing only the parent
    leaves that worker running as an orphan still holding the port).

    Restart: Stop, then Start.

    Status: reports whether each targeted service is running (with its
    pid), and its log file's path/size (flagged if past -MaxLogSizeMB).

.PARAMETER Action
    Start (default), Stop, Restart, or Status.

.PARAMETER Backend
    Target only the backend (port 8000). Pass both -Backend and -Frontend
    (or neither) to target both.

.PARAMETER Frontend
    Target only the frontend (port 3000).

.PARAMETER SkipMigrate
    Start/Restart only: skip the `alembic upgrade head` step (useful if
    you just ran it yourself).

.PARAMETER MaxLogSizeMB
    Status only: flag a service's log as needing rotation once it reaches
    this size (see log-versioning note above for why this isn't automatic
    mid-run). Start/Restart don't consult this -- they always rotate.

.PARAMETER MaxLogFiles
    Start/Restart only: total log files kept per service, live file
    included (e.g. 10 means backend.log plus up to 9 numbered backups).

.EXAMPLE
    .\control-dev.ps1
.EXAMPLE
    .\control-dev.ps1 -Action Stop
.EXAMPLE
    .\control-dev.ps1 -Action Restart -Backend
.EXAMPLE
    .\control-dev.ps1 -Action Status
#>
param(
    [ValidateSet("Start", "Stop", "Restart", "Status")]
    [string]$Action = "Start",

    [switch]$Backend,
    [switch]$Frontend,

    [switch]$SkipMigrate,
    [int]$MaxLogSizeMB = 5,
    [int]$MaxLogFiles = 10
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$logDir = Join-Path $root "logs"

# Neither switch given means "both".
$targetBackend = $Backend.IsPresent -or (-not $Backend.IsPresent -and -not $Frontend.IsPresent)
$targetFrontend = $Frontend.IsPresent -or (-not $Backend.IsPresent -and -not $Frontend.IsPresent)

$services = @()
if ($targetBackend) {
    $services += [pscustomobject]@{
        Name       = "backend"
        Port       = 8000
        WorkingDir = Join-Path $root "backend"
        Command    = "uv run uvicorn --app-dir src civil_engineering.main:app --reload --port 8000"
        LogPath    = Join-Path $logDir "backend.log"
        Url        = "http://localhost:8000"
    }
}
if ($targetFrontend) {
    $services += [pscustomobject]@{
        Name       = "frontend"
        Port       = 3000
        WorkingDir = $root
        Command    = "npm run dev"
        LogPath    = Join-Path $logDir "frontend.log"
        Url        = "http://localhost:3000"
    }
}

function Get-PortOwnerPid {
    param([int]$Port)
    (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty OwningProcess)
}

# The PID bound to a dev server's port isn't always the whole process
# tree (uvicorn --reload's multiprocessing worker, in particular, runs as
# a child of it) -- so stopping cleanly means walking down to every
# descendant, not just the one PID owning the socket.
function Get-ProcessTreeIds {
    param([int]$RootProcessId)
    $ids = @($RootProcessId)
    $frontier = @($RootProcessId)
    while ($frontier.Count -gt 0) {
        $children = @()
        foreach ($parentId in $frontier) {
            $children += Get-CimInstance Win32_Process -Filter "ParentProcessId = $parentId" -ErrorAction SilentlyContinue
        }
        $newIds = @($children | Select-Object -ExpandProperty ProcessId | Where-Object { $ids -notcontains $_ })
        $ids += $newIds
        $frontier = $newIds
    }
    return $ids
}

function Stop-DevService {
    param($Service)
    $ownerId = Get-PortOwnerPid -Port $Service.Port
    if (-not $ownerId) {
        Write-Host "$($Service.Name): not running (port $($Service.Port) is free)."
        return
    }
    foreach ($procId in (Get-ProcessTreeIds -RootProcessId $ownerId)) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Stopping $($proc.ProcessName) (pid $procId) [$($Service.Name)]"
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Show-DevStatus {
    param($Service)
    $ownerId = Get-PortOwnerPid -Port $Service.Port
    if ($ownerId) {
        $proc = Get-Process -Id $ownerId -ErrorAction SilentlyContinue
        $procName = if ($proc) { $proc.ProcessName } else { "unknown" }
        Write-Host "$($Service.Name): RUNNING - $procName (pid $ownerId) on port $($Service.Port)"
    } else {
        Write-Host "$($Service.Name): STOPPED - port $($Service.Port) is free"
    }
    if (Test-Path $Service.LogPath) {
        $sizeBytes = (Get-Item $Service.LogPath).Length
        $sizeKB = [math]::Round($sizeBytes / 1KB, 1)
        $flag = if (($sizeBytes / 1MB) -ge $MaxLogSizeMB) { " [past ${MaxLogSizeMB}MB - run -Action Restart to rotate it]" } else { "" }
        Write-Host "  log: $($Service.LogPath) ($sizeKB KB)$flag"
    } else {
        Write-Host "  log: $($Service.LogPath) (none yet)"
    }
}

function Invoke-LogRotation {
    param([string]$Path, [int]$MaxFiles)
    if (-not (Test-Path $Path)) { return }
    if ($MaxFiles -le 1) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
        return
    }
    $oldest = "$Path.$($MaxFiles - 1)"
    if (Test-Path -LiteralPath $oldest) {
        Remove-Item -LiteralPath $oldest -Force -ErrorAction SilentlyContinue
    }
    for ($i = $MaxFiles - 2; $i -ge 1; $i--) {
        $src = "$Path.$i"
        $dst = "$Path.$($i + 1)"
        if (Test-Path -LiteralPath $src) {
            Move-Item -LiteralPath $src -Destination $dst -Force -ErrorAction SilentlyContinue
        }
    }
    Move-Item -LiteralPath $Path -Destination "$Path.1" -Force -ErrorAction SilentlyContinue
}

function Start-DevService {
    param($Service)
    # Every start gets a fresh live log; the previous run becomes .1,
    # shifting older backups up and dropping anything past -MaxLogFiles.
    Invoke-LogRotation -Path $Service.LogPath -MaxFiles $MaxLogFiles
    Write-Host "Starting $($Service.Name) on $($Service.Url) (log: $($Service.LogPath)) ..."
    # `2>&1 | Out-File -Encoding utf8`, not `*>`: `*>` writes UTF-16 (PowerShell's
    # default), which renders as garbled double-spaced text in any plain-text
    # tool (grep, tail, most editors). This gets real UTF-8 instead.
    $command = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; cd '$($Service.WorkingDir)'; $($Service.Command) 2>&1 | Out-File -FilePath '$($Service.LogPath)' -Encoding utf8"
    Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile", "-Command", $command
}

if ($Action -eq "Status") {
    foreach ($service in $services) { Show-DevStatus -Service $service }
    return
}

if ($Action -eq "Stop" -or $Action -eq "Restart") {
    foreach ($service in $services) { Stop-DevService -Service $service }
    if ($Action -eq "Stop") {
        Write-Host "Done."
        return
    }
    Start-Sleep -Seconds 1
}

# --- Start (also reached by Restart, right after stopping) ---

# 1. Local env file
$envPath = Join-Path $root ".env"
$envExamplePath = Join-Path $root ".env.example"
if (-not (Test-Path $envPath)) {
    if (Test-Path $envExamplePath) {
        Write-Host "No .env found - creating one from .env.example."
        Copy-Item $envExamplePath $envPath
    } else {
        Write-Error "No .env or .env.example found at repo root. Create .env first (see README.md)."
        exit 1
    }
}

# 2. PostgreSQL reachability (only matters if the backend is targeted;
#    default port -- override by editing this script if your DATABASE_URL
#    in .env points elsewhere)
if ($targetBackend) {
    $pg = Test-NetConnection -ComputerName localhost -Port 5432 -WarningAction SilentlyContinue
    if (-not $pg.TcpTestSucceeded) {
        Write-Error "PostgreSQL is not reachable on localhost:5432. Start the PostgreSQL service and re-run this script."
        exit 1
    }
    Write-Host "PostgreSQL is reachable on port 5432."
}

# 3. Refuse to double-start if a targeted server is already running
$busyPorts = $services | Where-Object { Get-PortOwnerPid -Port $_.Port } | Select-Object -ExpandProperty Port
if ($busyPorts.Count -gt 0) {
    Write-Warning "Port(s) $($busyPorts -join ', ') are already in use - a dev server may already be running."
    Write-Warning "Run '.\control-dev.ps1 -Action Stop' first if you want a clean restart."
    exit 1
}

# 4. Migrations (backend only)
if ($targetBackend -and -not $SkipMigrate) {
    Write-Host "Applying database migrations..."
    Push-Location (Join-Path $root "backend")
    uv run alembic upgrade head
    Pop-Location
}

# 5. Bootstrap the sysadmin account on a brand-new database (backend only)
if ($targetBackend) {
    Push-Location (Join-Path $root "backend")
    $userCount = (uv run python -c "import sys; sys.path.insert(0, 'src'); from civil_engineering.database import SessionLocal; from civil_engineering.models import User; db = SessionLocal(); print(db.query(User).count()); db.close()" 2>$null | Select-Object -Last 1).Trim()
    Pop-Location

    if ($userCount -eq "0") {
        Write-Host ""
        Write-Host "No users exist yet - this looks like a fresh database. Setting up the 'sysadmin' account."
        $securePwd = Read-Host "Choose an initial sysadmin password" -AsSecureString
        $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePwd)
        try {
            $env:SYSADMIN_INITIAL_PASSWORD = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        } finally {
            [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
        Push-Location (Join-Path $root "backend")
        uv run python scripts/create_sysadmin.py
        Pop-Location
        Remove-Item Env:\SYSADMIN_INITIAL_PASSWORD
    }
}

# 6. Launch the targeted server(s) in the background; output goes to
#    self-rotating log files instead of a visible window.
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}
Write-Host ""
foreach ($service in $services) {
    Start-DevService -Service $service
}

# 7. Wait for the backend health check, if targeted
if ($targetBackend) {
    Write-Host "Waiting for backend health check..."
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) { $ready = $true; break }
        } catch {}
        Start-Sleep -Seconds 1
    }
    Write-Host ""
    if ($ready) {
        Write-Host "Backend is up: http://localhost:8000/health"
    } else {
        Write-Warning "Backend did not respond within 30s - check logs\backend.log for errors."
    }
}

if ($targetFrontend) {
    Write-Host "Frontend: http://localhost:3000"
}
Write-Host "Logs: $logDir (tail with: Get-Content -Wait -Tail 20 <path>)"
if ($targetBackend) {
    Write-Host "Log in with the sysadmin account (or an account an admin has created)."
}
Write-Host "Run '.\control-dev.ps1 -Action Status' to check what's running, or '-Action Stop' to shut it down."
