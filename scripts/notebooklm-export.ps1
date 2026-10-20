<#
.SYNOPSIS
    Copies every tracked .md and .csv file into notebooklm-export/ with unique,
    folder-prefixed names so they are easy to tell apart in NotebookLM.

.DESCRIPTION
    The repo has several same-named docs (requirements.md, design.md,
    tasks.md across .kiro/specs/*, and README.md in many folders). Those
    names MUST stay as-is on disk because Kiro spec tooling and repo
    convention depend on them. This script leaves originals untouched and
    writes renamed COPIES into notebooklm-export/.

    Naming rule: <path-with-slashes-as-double-underscores>.md
      .kiro/specs/calculable-churn-model/requirements.md
        -> kiro__specs__calculable-churn-model__requirements.md
      backend/README.md
        -> backend__README.md
      README.md (root)
        -> README.md

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/notebooklm-export.ps1
#>

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$outDir   = Join-Path $repoRoot "notebooklm-export"

# Collect tracked .md files, excluding tooling noise.
Push-Location $repoRoot
try {
    $files = @(git ls-files "*.md" "*.csv") |
        Where-Object { $_ -notmatch "pytest_cache" -and $_ -notmatch "node_modules" }
}
finally {
    Pop-Location
}

if (-not $files) {
    Write-Error "No tracked .md/.csv files found."
    exit 1
}

# Fresh output folder each run.
if (Test-Path $outDir) {
    Remove-Item $outDir -Recurse -Force
}
New-Item -ItemType Directory -Path $outDir | Out-Null

$count = 0
foreach ($rel in $files) {
    $src = Join-Path $repoRoot $rel
    if (-not (Test-Path $src)) { continue }

    # Build a unique, readable name from the relative path.
    $flat = ($rel -replace "/", "__") -replace "\\", "__"
    # Drop a leading dot on dot-folders so NotebookLM shows them cleanly.
    $flat = $flat -replace "^\.", ""
    $flat = $flat.TrimStart("_")

    $dest = Join-Path $outDir $flat
    Copy-Item -LiteralPath $src -Destination $dest -Force
    $count++
    Write-Host ("  {0,-55} <- {1}" -f $flat, $rel)
}

Write-Host ""
Write-Host "Exported $count file(s) to: $outDir"
Write-Host "Upload the contents of that folder to NotebookLM."