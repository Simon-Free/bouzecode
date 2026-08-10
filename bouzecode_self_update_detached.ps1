# Spawn bouzecode_self_update.ps1 in a NEW detached PowerShell window.
# Survives the kill of bouzecode itself. Pass-through args to the inner script.
#
# Usage from bouzecode (via Bash tool):
#   powershell.exe -File ".\bouzecode_self_update_detached.ps1"
#   powershell.exe -File ".\bouzecode_self_update_detached.ps1" -Pull
#   powershell.exe -File ".\bouzecode_self_update_detached.ps1" -Version v1.2.3
[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)] $Args)

$inner = Join-Path $PSScriptRoot "bouzecode_self_update.ps1"
if (-not (Test-Path $inner)) { throw "Inner script not found: $inner" }

$argList = @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", $inner) + $Args

# Start-Process with a separate window detaches from the current process tree.
Start-Process -FilePath "powershell.exe" -ArgumentList $argList -WindowStyle Normal | Out-Null

Write-Host "Spawned detached self-update window. This terminal can be safely killed." -ForegroundColor Green
Write-Host "Watch the new window for progress; logs in ~/.bouzecode/last_update_*.log" -ForegroundColor Cyan
