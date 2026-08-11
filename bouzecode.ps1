# ============================================================
# bouzecode.ps1 - one-shot launcher for the bouzecode CLI
# Loads .env, ensures uv is available, keeps .venv in sync, then launches the REPL.
# Usage: .\bouzecode.ps1 [bouzecode args...]
#
# ASCII ONLY. Windows PowerShell 5.1 re-reads a BOM-less .ps1 as ANSI, which
# turns any accent / em dash / box character into mojibake on the console.
# ============================================================

$ErrorActionPreference = "Stop"

$RepoDir      = $PSScriptRoot
$VenvDir      = Join-Path $RepoDir ".venv"
$PythonExe    = Join-Path $VenvDir "Scripts\python.exe"
$BouzecodeExe = Join-Path $VenvDir "Scripts\bouzecode.exe"
$PyProject    = Join-Path $RepoDir "pyproject.toml"
$Stamp        = Join-Path $VenvDir ".bouzecode_installed"

# --- 1. Load .env (proxy, index credentials) --------------------------------
# BEFORE the install step: on a network where the package index is only
# reachable through a proxy, HTTP(S)_PROXY has to be in the environment by the
# time uv runs, otherwise there is no way to bootstrap at all.
. (Join-Path $PSScriptRoot "load_dotenv.ps1")
Import-DotEnv -Path (Join-Path $RepoDir ".env") -Label "bouzecode"

# --- 2. Locate uv ------------------------------------------------------------
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

# --- 3. Ensure venv ----------------------------------------------------------
if (-not (Test-Path $PythonExe)) {
    Write-Host "[bouzecode] creating venv..." -ForegroundColor Cyan
    Push-Location $RepoDir
    & $UvExe venv --python 3.13
    Pop-Location
}

# --- 4. Install / update deps if pyproject changed ---------------------------
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

# --- 5. Ensure ripgrep is available ------------------------------------------
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

# --- 6. Runtime env ----------------------------------------------------------
$env:PYTHONIOENCODING  = "utf-8"

# Map ANTHROPIC_AUTH_TOKEN -> ANTHROPIC_API_KEY if not already set
if (-not $env:ANTHROPIC_API_KEY -and $env:ANTHROPIC_AUTH_TOKEN) {
    $env:ANTHROPIC_API_KEY = $env:ANTHROPIC_AUTH_TOKEN
}

# Warn only when NO provider at all can serve a model. With OPENROUTER_KEY (or a
# gateway key) set, bouzecode itself tells the user which models are reachable.
$ProviderKeys = @(
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
    "OPENROUTER_KEY", "OPENROUTER_API_KEY",
    "BOUZECODE_GATEWAY_API_KEY"
)
$HasProviderKey = $false
foreach ($name in $ProviderKeys) {
    if ([System.Environment]::GetEnvironmentVariable($name, "Process")) { $HasProviderKey = $true }
}
if (-not $HasProviderKey) {
    Write-Host "[bouzecode] WARNING: no provider API key found." -ForegroundColor Yellow
    Write-Host "  Add one of these to your .env file (repo root) or set it as an env var:" -ForegroundColor Yellow
    Write-Host "    ANTHROPIC_API_KEY=sk-ant-...        (claude-* models)" -ForegroundColor Yellow
    Write-Host "    OPENROUTER_KEY=sk-or-...            (deepseek/kimi/glm models)" -ForegroundColor Yellow
    Write-Host "    BOUZECODE_GATEWAY_API_KEY=...       (OpenAI-compatible gateway)" -ForegroundColor Yellow
}

# --- 7. Launch ----------------------------------------------------------------
Write-Host ""
Write-Host "=== bouzecode ===" -ForegroundColor Green
Write-Host "Repo:  $RepoDir"
Write-Host ""

& $BouzecodeExe @args
