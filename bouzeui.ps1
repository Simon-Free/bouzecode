# bouzeui.ps1 - launch the bouzeui web server (bouzecode.web_v2).
#
# ASCII ONLY, saved WITH a UTF-8 BOM. PowerShell 5.1 reads a BOM-less .ps1 as ANSI,
# so a single accented character or em dash breaks the parser ("missing terminator).
# Keep every line in this file pure ASCII.
#
# Usage: .\bouzeui.ps1 [port]
#
# Test hooks (used by tests/test_bouzeui_launcher.py, never in normal use):
#   BOUZEUI_VENV          - use this venv directory instead of <repo>\.venv
#   BOUZEUI_PREPARE_ONLY  - do the whole preparation, then exit 0 without launching

$ErrorActionPreference = "Stop"

# --- 0. Paths ----------------------------------------------------------------
$RepoDir   = $PSScriptRoot
$ParentDir = Split-Path -Parent $RepoDir
if ($env:BOUZEUI_VENV) { $VenvDir = $env:BOUZEUI_VENV } else { $VenvDir = Join-Path $RepoDir ".venv" }
$ScriptsDir     = Join-Path $VenvDir "Scripts"
$PythonExe      = Join-Path $ScriptsDir "python.exe"
$BouzeuiModule  = "bouzecode.web_v2"
$PyProject      = Join-Path $RepoDir "pyproject.toml"
$Stamp          = Join-Path $VenvDir ".bouzeui_installed"

$PortArg = $null
foreach ($a in $args) { if ($a -match '^\d+$') { $PortArg = $a; break } }

# --- 1. Logging: console AND ~/.bouzecode/bouzeui.log ------------------------
$HomeDir = $env:USERPROFILE
if (-not $HomeDir) { $HomeDir = $HOME }
$LogDir  = Join-Path $HomeDir ".bouzecode"
$LogFile = Join-Path $LogDir "bouzeui.log"

function Initialize-Log {
    try {
        if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
        if (Test-Path $LogFile) {
            $size = (Get-Item $LogFile).Length
            if ($size -gt 1048576) {
                $tail = Get-Content $LogFile -Tail 2000
                Set-Content -Path $LogFile -Value $tail -Encoding UTF8
            }
        }
    } catch { }
}

function Log {
    param([string]$Message, [string]$Color = "DarkGray")
    $stampedLine = "[" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + "] " + $Message
    Write-Host ("[bouzeui] " + $Message) -ForegroundColor $Color
    try { Add-Content -Path $LogFile -Value $stampedLine -Encoding UTF8 } catch { }
}

Initialize-Log
Log ("launch: repo=" + $RepoDir + " venv=" + $VenvDir)

# A venv python must find ITS OWN stdlib. The uv-managed python of another venv
# exports PYTHONHOME to every child process; inherited here, it makes the venv
# python load a foreign stdlib ("SRE module mismatch") and fail every health check.
foreach ($inherited in @("PYTHONHOME", "__PYVENV_LAUNCHER__")) {
    $value = [Environment]::GetEnvironmentVariable($inherited, "Process")
    if ($value) {
        Log ("ignoring inherited " + $inherited + "=" + $value)
        [Environment]::SetEnvironmentVariable($inherited, $null, "Process")
    }
}

# --- 2. Locate uv ------------------------------------------------------------
function Find-Uv {
    $candidates = @(
        (Join-Path $ParentDir "uv.exe"),
        (Join-Path $RepoDir "uv.exe"),
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
        (Join-Path $env:LOCALAPPDATA "uv\uv.exe")
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$UvExe = Find-Uv
if (-not $UvExe) {
    Log "uv.exe not found (looked next to the repo, in ~/.local/bin, in LOCALAPPDATA, and on PATH)" "Red"
    Write-Error "bouzeui: uv.exe not found. Install uv, then run this script again."
    exit 1
}

# --- 3. Helpers: pyproject version + venv health -----------------------------
function Get-PyProjectVersion {
    if (-not (Test-Path $PyProject)) { return $null }
    foreach ($line in Get-Content $PyProject) {
        if ($line -match '^\s*version\s*=\s*"([^"]+)"') { return $Matches[1] }
    }
    return $null
}

$SrcDir = Join-Path $RepoDir "src"
$ImportProbe = "import os, bouzecode, importlib.metadata as m; " +
    "print('BZ_SRC=' + os.path.dirname(os.path.dirname(os.path.abspath(bouzecode.__file__)))); " +
    "print('BZ_VER=' + next((d.version for d in m.distributions(name='bouzecode')), 'none'))"

function Get-NormalizedPath {
    param([string]$Path)
    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\').ToLowerInvariant()
}

# Runs the venv python with the given PYTHONPATH and reports where bouzecode is
# imported from and what its metadata says. $null when the import fails.
function Invoke-ImportProbe {
    param([string]$PythonPath)
    if (-not (Test-Path $PythonExe)) { return $null }
    $savedPyPath = $env:PYTHONPATH
    $env:PYTHONPATH = $PythonPath
    try {
        $out = & $PythonExe -c $ImportProbe 2>&1
        $ok = ($LASTEXITCODE -eq 0)
    } catch {
        $out = $_.Exception.Message
        $ok = $false
    } finally {
        $env:PYTHONPATH = $savedPyPath
    }
    if (-not $ok) {
        Log ("import probe failed (PYTHONPATH=" + $PythonPath + "): " + (($out | Select-Object -Last 1) -as [string]))
        return $null
    }
    $lines = @($out | ForEach-Object { $_.ToString().Trim() })
    $src = ($lines | Where-Object { $_.StartsWith("BZ_SRC=") } | Select-Object -Last 1).Substring(7)
    $ver = ($lines | Where-Object { $_.StartsWith("BZ_VER=") } | Select-Object -Last 1).Substring(7)
    return @{ SourceRoot = $src; Version = $ver }
}

# The verifiable state the whole decision rests on, PYTHONPATH cleared so that a
# src/ fallback cannot fake success:
#   "current"  - bouzecode imports and its metadata matches pyproject.toml
#   "editable" - bouzecode imports from <repo>\src (editable install) but only the
#                METADATA lags behind: the code served is the right one
#   "broken"   - no importable bouzecode, or one imported from somewhere else
function Get-VenvState {
    param([string]$ExpectedVersion)
    $probe = Invoke-ImportProbe -PythonPath ""
    if ($null -eq $probe) { return "broken" }
    if (-not $ExpectedVersion -or $probe.Version -eq $ExpectedVersion) { return "current" }
    if ((Get-NormalizedPath $probe.SourceRoot) -eq (Get-NormalizedPath $SrcDir)) {
        Log ("editable install: metadata says bouzecode " + $probe.Version + ", pyproject says " +
             $ExpectedVersion + "; code is served from " + $probe.SourceRoot + " (metadata drift only)") "Yellow"
        return "editable"
    }
    Log ("venv reports bouzecode " + $probe.Version + " from " + $probe.SourceRoot + " but pyproject says " + $ExpectedVersion)
    return "broken"
}

# Windows cannot DELETE the image of a running process, but it CAN RENAME it
# (the loader opens it with FILE_SHARE_DELETE). Renaming the console shims frees
# their paths so uv can write fresh ones instead of failing with os error 5.
function Unblock-Shims {
    if (-not (Test-Path $ScriptsDir)) { return }
    $ts = Get-Date -Format "yyyyMMddHHmmss"
    foreach ($exe in Get-ChildItem -Path $ScriptsDir -Filter "bouzecode*.exe" -ErrorAction SilentlyContinue) {
        try {
            Rename-Item -Path $exe.FullName -NewName ($exe.Name + ".locked-" + $ts) -ErrorAction Stop
            Log ("shim moved aside: " + $exe.Name)
        } catch {
            Log ("shim could not be moved aside (hard lock): " + $exe.Name)
        }
    }
}

# A shim moved aside that the install did NOT rewrite is put back in place: the
# console command must never vanish. A moved-aside copy whose original was
# rewritten is a leftover; it is deleted unless a running process still holds it.
function Restore-Shims {
    if (-not (Test-Path $ScriptsDir)) { return }
    foreach ($old in Get-ChildItem -Path $ScriptsDir -Filter "*.locked-*" -ErrorAction SilentlyContinue) {
        $originalName = $old.Name -replace '\.locked-\d+$', ''
        if (-not (Test-Path (Join-Path $ScriptsDir $originalName))) {
            Rename-Item -Path $old.FullName -NewName $originalName
            Log ("shim restored (install did not rewrite it): " + $originalName) "Yellow"
            continue
        }
        try {
            Remove-Item -Path $old.FullName -Force -ErrorAction Stop
        } catch {
            Log ("leftover shim still held by a running process, kept: " + $old.Name)
        }
    }
}

function Invoke-UvInstall {
    param([switch]$NoDeps)
    $savedVenv = $env:VIRTUAL_ENV
    $env:VIRTUAL_ENV = $VenvDir
    Push-Location $RepoDir
    try {
        if ($NoDeps) { & $UvExe pip install -e "." --no-deps }
        else         { & $UvExe pip install -e "." }
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
        $env:VIRTUAL_ENV = $savedVenv
    }
    return $code
}

# --- 4. Create the venv if needed -------------------------------------------
if (-not (Test-Path $PythonExe)) {
    Log ("creating venv (" + $VenvDir + ")")
    & $UvExe venv $VenvDir --python 3.13
    if ($LASTEXITCODE -ne 0) {
        Log "venv creation failed" "Red"
        Write-Error "bouzeui: could not create the venv at $VenvDir. Run: uv venv `"$VenvDir`" --python 3.13"
        exit 1
    }
}

# --- 5. Install only when the observable state requires it -------------------
Restore-Shims
$Expected = Get-PyProjectVersion
$State    = Get-VenvState -ExpectedVersion $Expected

$stampFresh = $false
if (Test-Path $Stamp) {
    if (Test-Path $PyProject) {
        $stampFresh = ((Get-Item $Stamp).LastWriteTime -ge (Get-Item $PyProject).LastWriteTime)
    } else {
        $stampFresh = $true
    }
}

if ($State -eq "current" -and $stampFresh) {
    Log ("venv is up to date (bouzecode " + $Expected + "), nothing to install")
} else {
    if ($State -eq "current") { Log "stamp missing or older than pyproject.toml" }
    else { Log ("venv state is '" + $State + "' (expected bouzecode " + $Expected + ")") }

    Unblock-Shims
    Log "installing package (uv pip install -e .)"
    $code = Invoke-UvInstall
    $State = Get-VenvState -ExpectedVersion $Expected

    if ($State -ne "current") {
        Log ("install returned " + $code + " and the venv is not current; retrying with --no-deps") "Yellow"
        $code = Invoke-UvInstall -NoDeps
        $State = Get-VenvState -ExpectedVersion $Expected
    }
    Restore-Shims

    if ($State -eq "current") {
        if ($code -ne 0) {
            Log ("package installed OK; console shim not rewritten (locked by a running process) - skipped") "Yellow"
        }
        # The stamp records that the PACKAGE is in place, not that every shim was
        # rewritten: otherwise a locked exe would replay this install forever.
        Set-Content -Path $Stamp -Value ((Get-Date -Format "s") + " " + $Expected) -Encoding ASCII
        Log ("stamp written (" + $Stamp + ")")
    } elseif ($null -ne (Invoke-ImportProbe -PythonPath $SrcDir)) {
        # A locked shim (an interactive bouzecode session) made the install fail, but
        # the code lives in src/: the server runs from there. No stamp: the install
        # is retried on the next launch, once the lock is gone.
        Log ("FALLBACK: install returned " + $code + " (venv state '" + $State + "'); " +
             "starting from src with PYTHONPATH=" + $SrcDir + " - stamp NOT written") "Yellow"
    } else {
        Log "venv is unusable after install and retry: bouzecode cannot be imported even with PYTHONPATH=src" "Red"
        $msg = @(
            "bouzeui: the venv at $VenvDir cannot import bouzecode.",
            "Refusing to start the server on a broken venv.",
            "What to do:",
            "  1. Close the running bouzecode agents / consoles that hold $ScriptsDir\bouzecode*.exe",
            "  2. Reinstall: uv pip install -e `"$RepoDir`"",
            "  3. If it still fails, rebuild the venv: uv venv `"$VenvDir`" --python 3.13 --clear",
            "See the log: $LogFile"
        ) -join [Environment]::NewLine
        Write-Error $msg
        exit 1
    }
}

$env:PYTHONPATH = Join-Path $RepoDir "src"

# --- 6. Load .env from demo_application (proxy, index, credentials) -------
$EnvFile = Join-Path $ParentDir "demo_application\.env"
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
    Log ("loaded .env (" + $EnvFile + ")")
}

# --- 7. corporate env (proxy + API) - overrides ----------------------------------
$env:HTTP_PROXY        = "http://proxy.example.com:8080"
$env:HTTPS_PROXY       = "http://proxy.example.com:8080"
$env:NO_PROXY          = "localhost,127.0.0.1,.example.com"
# TLS : la verification des certificats reste ACTIVE (plus de PYTHONHTTPSVERIFY=0).
# Certificat interne du proxy corporate : SSL_CERT_FILE / REQUESTS_CA_BUNDLE, ou BOUZECODE_CA_BUNDLE
# (dans .env) recopie ici. Poste de dev seulement : BOUZECODE_TLS_INSECURE=1 (journalise).
if ($env:BOUZECODE_CA_BUNDLE -and (Test-Path $env:BOUZECODE_CA_BUNDLE)) {
    if (-not $env:REQUESTS_CA_BUNDLE) { $env:REQUESTS_CA_BUNDLE = $env:BOUZECODE_CA_BUNDLE }
    if (-not $env:SSL_CERT_FILE) { $env:SSL_CERT_FILE = $env:BOUZECODE_CA_BUNDLE }
}
$env:PYTHONIOENCODING  = "utf-8"
# ANTHROPIC_API_KEY must come from .env / the environment (never hardcoded).
if (-not $env:ANTHROPIC_API_KEY -and $env:ANTHROPIC_AUTH_TOKEN) { $env:ANTHROPIC_API_KEY = $env:ANTHROPIC_AUTH_TOKEN }
$env:ANTHROPIC_BASE_URL = "https://llm-gateway.example.com"

# --- 7b. Chrome DevTools MCP (browser automation for the frontend agent) -----
# Poses the env var the chrome_devtools launcher reads at tool registration.
# Enables the mcp__chrome-devtools__* tools for agents spawned from the web UI
# (the CLI flag --enable-chrome-devtools does the same for `bouzecode`).
$env:BOUZECODE_ENABLE_CHROME_DEVTOOLS = "1"

# --- 8. Launch ---------------------------------------------------------------
$port = if ($PortArg) { $PortArg } else { "5056" }

if ($env:BOUZEUI_PREPARE_ONLY) {
    Log "prepare-only: skipping server launch"
    exit 0
}

Write-Host ""
Write-Host "=== bouzeui ===" -ForegroundColor Green
Write-Host "Repo: $RepoDir"
Write-Host "URL : http://127.0.0.1:$port"
Write-Host ""
Log ("starting server on port " + $port)

Push-Location $RepoDir
& $PythonExe -m $BouzeuiModule --port $port
Pop-Location
