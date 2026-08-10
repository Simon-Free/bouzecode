# Self-update bouzecode: kill running processes, optionally pull/switch version, reinstall, smoke test.
# Auto-rollback via stash if smoke test fails.
#
# Usage:
#   .\bouzecode_self_update.ps1                  # reinstall HEAD (deps refresh)
#   .\bouzecode_self_update.ps1 -Pull            # git pull then reinstall
#   .\bouzecode_self_update.ps1 -Version v1.2.3  # checkout tag, reinstall
#   .\bouzecode_self_update.ps1 -ListVersions
#   .\bouzecode_self_update.ps1 -Current
[CmdletBinding()]
param(
    [switch]$Pull,
    [string]$Version,
    [switch]$ListVersions,
    [switch]$Current,
    [int]$KillWaitSeconds = 2
)
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
Set-Location $repo

$logDir  = Join-Path $env:USERPROFILE ".bouzecode"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$ts      = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $logDir "last_update_$ts.log"

function Log($msg, $color = "White") {
    $line = "[$(Get-Date -Format HH:mm:ss)] $msg"
    Write-Host $line -ForegroundColor $color
    Add-Content -Path $logFile -Value $line
}

# === Read-only modes ===

if ($Current) {
    $desc = git describe --tags --always --dirty 2>$null
    Write-Host "Current: $desc"
    return
}

if ($ListVersions) {
    $headDesc = git describe --tags --always --dirty 2>$null
    Write-Host "HEAD: $headDesc" -ForegroundColor Cyan
    Write-Host "Tags (newest first):" -ForegroundColor Cyan
    git tag -l "v*" --sort=-v:refname | ForEach-Object { Write-Host "  $_" }
    return
}

# === Update flow ===

Log "=== bouzecode self-update started ===" Cyan
Log "Repo:    $repo"
Log "Logfile: $logFile"

# 1. Kill running processes
Log "Step 1: killing bouzecode processes..."
$names = @("bouzecode", "bouzegui")
$killed = 0
foreach ($n in $names) {
    Get-Process -Name $n -ErrorAction SilentlyContinue | ForEach-Object {
        Log "  killing $($_.Name) pid=$($_.Id)" Yellow
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        $killed++
    }
}
# Also kill python.exe holding bouzecode in cmdline (case: launched via uv run / python -m)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'bouzecode' } |
    ForEach-Object {
        Log "  killing python.exe pid=$($_.ProcessId) (bouzecode in cmdline)" Yellow
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $killed++
    }
Log "  killed $killed process(es); waiting ${KillWaitSeconds}s for file locks to release..."
Start-Sleep -Seconds $KillWaitSeconds

# 2. Snapshot state for rollback
$originalSha    = (git rev-parse HEAD).Trim()
$originalBranch = (git rev-parse --abbrev-ref HEAD).Trim()
Log "Step 2: snapshot -- branch=$originalBranch sha=$originalSha"

$needCheckout = $Pull -or $Version
$stashRef = $null
if ($needCheckout) {
    $dirty = git status --porcelain
    if ($dirty) {
        $stashMsg = "bouzecode-self-update-$ts"
        Log "  stashing dirty tree as '$stashMsg'..."
        git stash push -u -m $stashMsg | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $stashRef = (git stash list | Select-String $stashMsg | Select-Object -First 1).ToString().Split(":")[0]
            Log "  stash saved as $stashRef"
        } else {
            Log "  WARNING: stash failed, continuing without stash" Red
        }
    }
}

# 3. Pull or checkout version
if ($Pull) {
    Log "Step 3: git pull..."
    git pull
    if ($LASTEXITCODE -ne 0) { throw "git pull failed" }
}
if ($Version) {
    if ($Version -notmatch '^v') { $Version = "v$Version" }
    Log "Step 3: git checkout $Version..."
    git checkout $Version
    if ($LASTEXITCODE -ne 0) { throw "git checkout $Version failed" }
}

# 4. Reinstall
Log "Step 4: pip install -e ."
$pip = Join-Path $repo ".venv\Scripts\pip.exe"
if (-not (Test-Path $pip)) { throw "pip not found at $pip -- venv missing?" }
& $pip install -e . 2>&1 | Tee-Object -FilePath $logFile -Append
$installExit = $LASTEXITCODE
if ($installExit -ne 0) {
    Log "pip install failed (exit $installExit)" Red
    # fall through to rollback
}

# 5. Smoke test -- via 'python -m' to bypass Scripts\*.exe shim (no file lock)
Log "Step 5: smoke test (python -m bouzecode --version)..."
$py = Join-Path $repo ".venv\Scripts\python.exe"
$smokeOk = $false
if (Test-Path $py) {
    Push-Location $repo
    $out = & $py -m bouzecode --version 2>&1
    $smokeExit = $LASTEXITCODE
    Pop-Location
    $out | ForEach-Object { Log "  $_" }
    if ($smokeExit -eq 0) { $smokeOk = $true }
} else {
    Log "  python.exe not found at $py" Red
}

if ($smokeOk -and $installExit -eq 0) {
    Log "=== UPDATE OK ===" Green
    if ($stashRef) {
        Log "Note: your previous dirty changes are in $stashRef. Run: git stash pop $stashRef" Yellow
    }
    return
}

# 6. Rollback
Log "=== SMOKE TEST FAILED -- ROLLING BACK ===" Red
Log "Resetting to $originalSha on branch $originalBranch..."
if ($originalBranch -ne "HEAD") {
    git checkout $originalBranch 2>&1 | Out-Null
}
git reset --hard $originalSha 2>&1 | Out-Null
& $pip install -e . 2>&1 | Tee-Object -FilePath $logFile -Append | Out-Null

if ($stashRef) {
    Log "Restoring stashed changes from $stashRef..."
    git stash pop $stashRef 2>&1 | Out-Null
}

# Re-smoke
Push-Location $repo
$reSmoke = & $py -m bouzecode --version 2>&1
$reSmokeExit = $LASTEXITCODE
Pop-Location
$reSmoke | ForEach-Object { Log "  $_" }
if ($reSmokeExit -eq 0) {
    Log "=== ROLLBACK OK -- back to working state ===" Green
    Log "Broken update logged to: $logFile" Yellow
} else {
    $recovery = Join-Path $logDir "RECOVERY.md"
    $lines = @(
        "# bouzecode RECOVERY needed",
        "",
        "Self-update at $ts failed AND rollback to $originalSha also fails the smoke test.",
        "",
        "Manual steps:",
        "1. Open: $logFile",
        "2. cd $repo",
        "3. Inspect: git status, git log -5",
        "4. If dirty changes are stashed, list with: git stash list",
        "5. Try: .venv\Scripts\python.exe -c 'import bouzecode'",
        "",
        "Last error output above."
    )
    Set-Content -Path $recovery -Value $lines
    Log "=== ROLLBACK FAILED -- see $recovery ===" Red
    throw "Manual recovery required."
}
