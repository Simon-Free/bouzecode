# ============================================================
# bouzegui.ps1 — one-shot launcher for BouzéGUI (Flask web UI for bouzecode)
# Ensures uv is available, keeps .venv in sync, then launches the app.
# ============================================================

$ErrorActionPreference = "Stop"

$RepoDir   = $PSScriptRoot
$VenvDir   = Join-Path $RepoDir ".venv-ui"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$BouzequiExe = Join-Path $VenvDir "Scripts\bouzegui.exe"
$PyProject = Join-Path $RepoDir "pyproject.toml"
$Stamp     = Join-Path $VenvDir ".bouzegui_installed"

# --- 1. Locate uv ------------------------------------------------------------
function Find-Uv {
    $parent = Split-Path $RepoDir -Parent
    $candidates = @(
        (Join-Path $RepoDir "uv.exe"),
        (Join-Path $parent "uv.exe"),
        "$env:USERPROFILE\.local\bin\uv.exe",
        "$env:LOCALAPPDATA\uv\uv.exe"
    )
    foreach ($path in $candidates) { if (Test-Path $path) { return $path } }
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$UvExe = Find-Uv
if (-not $UvExe) {
    Write-Error "uv not found. Install it from https://astral.sh/uv or place uv.exe next to the bouzecode/ directory."
    exit 1
}
Write-Host "[bouzegui] uv: $UvExe" -ForegroundColor Cyan

# --- 2. Ensure venv ----------------------------------------------------------
if (-not (Test-Path $PythonExe)) {
    Write-Host "[bouzegui] creating venv..." -ForegroundColor Cyan
    Push-Location $RepoDir
    & $UvExe venv $VenvDir --python 3.13
    Pop-Location
}

# --- 3. Install / update deps if pyproject changed --------------------------
$needInstall = $true
if ((Test-Path $Stamp) -and (Test-Path $BouzequiExe)) {
    $stampTime = (Get-Item $Stamp).LastWriteTimeUtc
    $pyprojectTime = (Get-Item $PyProject).LastWriteTimeUtc
    if ($stampTime -ge $pyprojectTime) { $needInstall = $false }
}

if ($needInstall) {
    Write-Host "[bouzegui] syncing deps (editable install with [web] extras)..." -ForegroundColor Cyan
    Push-Location $RepoDir
    & $UvExe pip install --python $PythonExe -e ".[web]"
    Pop-Location
    New-Item -ItemType File -Path $Stamp -Force | Out-Null
}

# --- 4. Load .env (proxy, index, credentials) --------------------------------
$EnvFile = Join-Path $RepoDir ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $eqIdx = $line.IndexOf("=")
            $key   = $line.Substring(0, $eqIdx)
            $val   = $line.Substring($eqIdx + 1).Trim('"')
            [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
        }
    }
    Write-Host "[bouzegui] loaded .env ($EnvFile)" -ForegroundColor DarkGray
}

# --- 5. Runtime env ---------------------------------------------------------
$env:PYTHONIOENCODING  = "utf-8"

# --- 6. Launch ---------------------------------------------------------------
$port = if ($args.Count -gt 0 -and $args[0] -match "^\d+$") { $args[0] } else { "5055" }
Write-Host ""
Write-Host "=== BouzéGUI ===" -ForegroundColor Green
Write-Host "Repo: $RepoDir"
Write-Host "URL : http://127.0.0.1:$port"
Write-Host ""

& $BouzequiExe --port $port
