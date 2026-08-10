# Publish a new bouzecode version: bump pyproject.toml, commit, tag, optional push.
# Usage:
#   .\bouzecode_publish.ps1                                  # auto-bump patch
#   .\bouzecode_publish.ps1 -Version 3.6.0
#   .\bouzecode_publish.ps1 -Message "fix stream resilience" -Push
[CmdletBinding()]
param(
    [string]$Version,
    [string]$Message = "",
    [switch]$Push
)
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
Set-Location $repo

$pyproject = Join-Path $repo "pyproject.toml"
$content = Get-Content $pyproject -Raw
if ($content -notmatch '(?m)^version\s*=\s*"([^"]+)"') {
    throw "Cannot find version line in pyproject.toml"
}
$current = $matches[1]
Write-Host "Current version: $current" -ForegroundColor Cyan

if (-not $Version) {
    if ($current -match '^(\d+)\.(\d+)\.(\d+)$') {
        $maj = [int]$matches[1]; $min = [int]$matches[2]; $patch = [int]$matches[3] + 1
        $Version = "$maj.$min.$patch"
    } else {
        throw "Current version '$current' is not X.Y.Z; pass -Version explicitly."
    }
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version '$Version' must be X.Y.Z"
}
$tag = "v$Version"

$existingTag = git tag -l $tag
if ($existingTag) {
    throw "Tag $tag already exists."
}

Write-Host "New version: $Version  (tag $tag)" -ForegroundColor Green

# Bump version line only
$newContent = [regex]::Replace(
    $content,
    '(?m)^(version\s*=\s*")([^"]+)(")',
    "`${1}$Version`${3}",
    [System.Text.RegularExpressions.RegexOptions]::None
)
Set-Content -Path $pyproject -Value $newContent -NoNewline

$msg = if ($Message) { "release: $tag - $Message" } else { "release: $tag" }

git add pyproject.toml
git commit -m $msg
if ($LASTEXITCODE -ne 0) { throw "git commit failed" }

git tag -a $tag -m $msg
if ($LASTEXITCODE -ne 0) { throw "git tag failed" }

Write-Host "Tagged $tag" -ForegroundColor Green

if ($Push) {
    Write-Host "Pushing to origin..." -ForegroundColor Cyan
    git push
    if ($LASTEXITCODE -ne 0) { throw "git push failed" }
    git push origin $tag
    if ($LASTEXITCODE -ne 0) { throw "git push tag failed" }
    Write-Host "Pushed $tag to origin" -ForegroundColor Green
} else {
    Write-Host "Not pushed (use -Push to push to origin)" -ForegroundColor Yellow
}
