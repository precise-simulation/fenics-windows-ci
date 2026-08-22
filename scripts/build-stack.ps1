# Build (and optionally upload) the win-64 fenics stack in dependency order.
# Assumes: rattler-build + anaconda-client on PATH, plan.json in CWD,
#          ANACONDA_API_TOKEN in the environment when -Upload is set.
param(
    [string]$PlanFile = "plan.json",
    [switch]$Upload
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot | Split-Path
$output = Join-Path $root "output"
Remove-Item $output -Recurse -Force -ErrorAction SilentlyContinue

# rattler-build's output dir doubles as a channel for downstream stages;
# it only writes win-64/, so give solvers an empty noarch too.
function Add-NoarchStub {
    param([string]$Dir)
    $na = Join-Path $Dir "noarch"
    New-Item -ItemType Directory -Force $na | Out-Null
    Set-Content (Join-Path $na "repodata.json") '{"info":{"subdir":"noarch"},"packages":{},"packages.conda":{}}'
}

$plan = (Get-Content $PlanFile | ConvertFrom-Json)

$stages = @(
    @{ name = "petsc";     recipe = "$root/recipes/petsc/recipe.yaml" },
    @{ name = "petsc4py";  recipe = "$root/recipes/petsc4py/recipe.yaml" },
    @{ name = "dolfinx";   recipe = "$root/recipes/dolfinx/recipe.yaml" }
)

foreach ($s in $stages) {
    if (-not $plan.$($s.name).rebuild) {
        Write-Host "== skip $($s.name) (unchanged) =="
        continue
    }
    Write-Host "== building $($s.name) $($plan.$($s.name).version) =="

    $channels = @()
    # upstream stages first (strict priority), then public fallbacks
    if (Test-Path "$output/win-64/repodata.json") { $channels += "file:///$($output -replace '\\','/')" }
    $channels += "precise-simulation", "conda-forge"

    & rattler-build build `
        --recipe $s.recipe `
        --output-dir $output `
        @($channels | ForEach-Object { "-c"; $_ })
    if ($LASTEXITCODE -ne 0) { throw "rattler-build failed for $($s.name)" }

    Add-NoarchStub $output
}

if ($Upload) {
    foreach ($f in (Get-ChildItem "$output/win-64" -Filter *.conda)) {
        Write-Host "== uploading $($f.Name) =="
        & anaconda upload --user precise-simulation $f.FullName
        if ($LASTEXITCODE -ne 0) { throw "upload failed for $($f.Name)" }
    }
}

Write-Host "== stack build complete =="
