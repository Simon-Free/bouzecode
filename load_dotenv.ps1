# ============================================================
# load_dotenv.ps1 - dot-source this to get Import-DotEnv.
# The four launchers each carried the same 12-line .env parser; they now share
# this one, so "load .env before installing" can never drift between them again.
#
# ASCII ONLY (Windows PowerShell 5.1 reads a BOM-less .ps1 as ANSI).
# ============================================================

function Import-DotEnv {
    <#
    .SYNOPSIS
    Load KEY=VALUE lines from a .env file into this process's environment.

    .DESCRIPTION
    The file wins over the ambient environment (unchanged from the per-launcher
    copies this replaces). Blank lines and lines starting with # are ignored.
    Missing file = silent no-op, so a fresh clone with no .env still launches.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$Label = "bouzecode"
    )
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $eqIdx = $line.IndexOf("=")
            $key   = $line.Substring(0, $eqIdx).Trim()
            $val   = $line.Substring($eqIdx + 1).Trim('"')
            [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
        }
    }
    Write-Host "[$Label] loaded .env ($Path)" -ForegroundColor DarkGray
}
