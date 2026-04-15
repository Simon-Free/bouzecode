# ============================================================
# bouzecode.ps1 — one-shot launcher for bouzecode CLI
# Ensures uv is available, keeps .venv in sync, then launches the REPL.
# Usage: .\bouzecode.ps1 [bouzecode args...]
# ============================================================

$ErrorActionPreference = "Stop"

$RepoDir      = $PSScriptRoot
$VenvDir      = Join-Path $RepoDir ".venv"
$PythonExe    = Join-Path $VenvDir "Scripts\python.exe"
$BouzecodeExe = Join-Path $VenvDir "Scripts\bouzecode.exe"
$PyProject    = Join-Path $RepoDir "pyproject.toml"
$Stamp        = Join-Path $VenvDir ".bouzecode_installed"

# --- 1. Locate uv ------------------------------------------------------------
function Find-Uv {
    # 1. PATH first (normal install)
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    # 2. Known locations as fallback
    $parent = Split-Path $RepoDir -Parent
    $candidates = @(
        (Join-Path $RepoDir "uv.exe"),
        (Join-Path $parent "uv.exe"),
        "$env:USERPROFILE\.local\bin\uv.exe",
        "$env:LOCALAPPDATA\uv\uv.exe"
    )
    foreach ($path in $candidates) { if (Test-Path $path) { return $path } }
    return $null
}

$UvExe = Find-Uv
if (-not $UvExe) {
    Write-Error "uv not found. Install it from https://astral.sh/uv or place uv.exe next to the repo."
    exit 1
}
Write-Host "[bouzecode] uv: $UvExe" -ForegroundColor Cyan

# --- 2. Ensure venv ----------------------------------------------------------
if (-not (Test-Path $PythonExe)) {
    Write-Host "[bouzecode] creating venv..." -ForegroundColor Cyan
    Push-Location $RepoDir
    & $UvExe venv --python 3.13
    Pop-Location
}

# --- 3. Install / update deps if pyproject changed ---------------------------
$needInstall = $true
if ((Test-Path $Stamp) -and (Test-Path $BouzecodeExe)) {
    $stampTime = (Get-Item $Stamp).LastWriteTimeUtc
    $pyprojectTime = (Get-Item $PyProject).LastWriteTimeUtc
    if ($stampTime -ge $pyprojectTime) { $needInstall = $false }
}

if ($needInstall) {
    Write-Host "[bouzecode] syncing deps (editable install)..." -ForegroundColor Cyan
    Push-Location $RepoDir
    & $UvExe pip install -e .
    Pop-Location
    New-Item -ItemType File -Path $Stamp -Force | Out-Null
}

# --- 4. Ensure ripgrep is available ------------------------------------------
if (-not (Get-Command rg -ErrorAction SilentlyContinue)) {
    Write-Host "[bouzecode] ripgrep (rg) not found, installing via winget..." -ForegroundColor Yellow
    winget install BurntSushi.ripgrep.MSVC --accept-source-agreements --accept-package-agreements 2>$null
    if (Get-Command rg -ErrorAction SilentlyContinue) {
        Write-Host "[bouzecode] ripgrep installed." -ForegroundColor Green
    } else {
        Write-Host "[bouzecode] ripgrep install failed. Grep will use fallback (slower)." -ForegroundColor Yellow
        Write-Host "  Install manually: winget install BurntSushi.ripgrep.MSVC" -ForegroundColor Yellow
    }
}

# --- 5. Load .env (proxy, credentials) ---------------------------------------
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
    Write-Host "[bouzecode] loaded .env" -ForegroundColor DarkGray
}

# --- 6. Runtime env ----------------------------------------------------------
$env:PYTHONIOENCODING  = "utf-8"

# Map ANTHROPIC_AUTH_TOKEN -> ANTHROPIC_API_KEY if not already set
if (-not $env:ANTHROPIC_API_KEY -and $env:ANTHROPIC_AUTH_TOKEN) {
    $env:ANTHROPIC_API_KEY = $env:ANTHROPIC_AUTH_TOKEN
}

if (-not $env:ANTHROPIC_API_KEY) {
    Write-Host "[bouzecode] WARNING: ANTHROPIC_API_KEY not set." -ForegroundColor Yellow
    Write-Host "  Add ANTHROPIC_API_KEY=sk-... to your .env file or set it as env var." -ForegroundColor Yellow
}

# --- 7. Launch ----------------------------------------------------------------
Write-Host ""
Write-Host "=== bouzecode ===" -ForegroundColor Green
Write-Host "Repo:  $RepoDir"
Write-Host "Model: claude-opus-4-6"
Write-Host ""

& $BouzecodeExe @args
