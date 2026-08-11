# ============================================================
# bouzegui.ps1 - one-shot launcher for the web UI (bouzecode.web_v2 Flask app)
# Loads .env, ensures uv is available, keeps .venv-ui in sync, then launches the app.
#
# ASCII ONLY. Windows PowerShell 5.1 re-reads a BOM-less .ps1 as ANSI, which is
# how the banner used to print as "BouzeGUI" with a mangled accent.
# ============================================================

$ErrorActionPreference = "Stop"

$RepoDir   = $PSScriptRoot
$VenvDir   = Join-Path $RepoDir ".venv-ui"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$BouzequiExe = Join-Path $VenvDir "Scripts\bouzegui.exe"
$PyProject = Join-Path $RepoDir "pyproject.toml"
$Stamp     = Join-Path $VenvDir ".bouzegui_installed"

# --- 1. Load .env (proxy, index, credentials) --------------------------------
# BEFORE the install step: the package index may only be reachable through the
# proxy declared in .env.
. (Join-Path $PSScriptRoot "load_dotenv.ps1")
Import-DotEnv -Path (Join-Path $RepoDir ".env") -Label "bouzegui"

# --- 2. Locate uv ------------------------------------------------------------
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

# --- 3. Ensure venv ----------------------------------------------------------
if (-not (Test-Path $PythonExe)) {
    Write-Host "[bouzegui] creating venv..." -ForegroundColor Cyan
    Push-Location $RepoDir
    & $UvExe venv $VenvDir --python 3.13
    Pop-Location
}

# --- 4. Install / update deps if pyproject changed --------------------------
$needInstall = $true
if ((Test-Path $Stamp) -and (Test-Path $BouzequiExe)) {
    $stampTime = (Get-Item $Stamp).LastWriteTimeUtc
    $pyprojectTime = (Get-Item $PyProject).LastWriteTimeUtc
    if ($stampTime -ge $pyprojectTime) { $needInstall = $false }
}

if ($needInstall) {
    Write-Host "[bouzegui] syncing deps (editable install with the [web] extra)..." -ForegroundColor Cyan
    Push-Location $RepoDir
    & $UvExe pip install --python $PythonExe -e ".[web]"
    Pop-Location
    New-Item -ItemType File -Path $Stamp -Force | Out-Null
}

# --- 5. Runtime env ---------------------------------------------------------
$env:PYTHONIOENCODING  = "utf-8"

# --- 6. Launch ---------------------------------------------------------------
$port = if ($args.Count -gt 0 -and $args[0] -match "^\d+$") { $args[0] } else { "5055" }
Write-Host ""
Write-Host "=== bouzegui ===" -ForegroundColor Green
Write-Host "Repo: $RepoDir"
Write-Host "URL : http://127.0.0.1:$port"
Write-Host ""

& $BouzequiExe --port $port
