# Build the win-64 fenics stack in dependency order.
# Assumes: rattler-build on PATH and plan.json in CWD.
param(
    [string]$PlanFile = "plan.json"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot | Split-Path
$output = Join-Path $root "output"
$logOutput = Join-Path $root "build-logs"
Remove-Item $output -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $logOutput -Recurse -Force -ErrorAction SilentlyContinue

# Locate the micromamba ci env wherever setup-micromamba put it
$rattler = Get-ChildItem "$env:MAMBA_ROOT_PREFIX/envs" -Recurse -Filter rattler-build.exe `
    -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
if (-not $rattler) { throw "rattler-build.exe not found under $env:MAMBA_ROOT_PREFIX/envs" }
$envBin = Split-Path $rattler
$envPrefix = Split-Path $envBin
Write-Host "ci env prefix: $envPrefix"
$env:PATH = "$envPrefix;$envBin;$envPrefix/Library/bin;$envPrefix/Scripts;$env:PATH"
if ($env:GITHUB_PATH) {
    Add-Content $env:GITHUB_PATH $envPrefix
    Add-Content $env:GITHUB_PATH "$envPrefix/Scripts"
}

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
    @{ name = "petsc";     recipe = "$root/recipes/petsc/recipe.yaml";     variants = "$root/recipes/petsc/variants-win64.yaml" },
    @{ name = "petsc4py";  recipe = "$root/recipes/petsc4py/recipe.yaml";  variants = "$root/recipes/petsc4py/variants-win64.yaml" },
    @{ name = "dolfinx";   recipe = "$root/recipes/dolfinx/recipe.yaml";   variants = "$root/recipes/dolfinx/variants-win64.yaml" }
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
        --variant-config $s.variants `
        --output-dir $output `
        @($channels | ForEach-Object { "-c"; $_ })
    if ($LASTEXITCODE -ne 0) {
        # surface the deepest configure/make log we can find
        $clog = Get-ChildItem "$output/bld" -Recurse -Filter "configure.log" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        $cmakeLog = Get-ChildItem "$output/bld" -Recurse -Filter "CMakeConfigureLog.yaml" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        New-Item -ItemType Directory -Force $logOutput | Out-Null
        if ($clog) {
            Write-Host "===== tail of $($clog.FullName) ====="
            Get-Content $clog.FullName -Tail 60 | Write-Host
            Copy-Item $clog.FullName (Join-Path $logOutput "$($s.name)-configure.log")
        }
        if ($cmakeLog) {
            Copy-Item $cmakeLog.FullName (Join-Path $logOutput "$($s.name)-CMakeConfigureLog.yaml")
        }
        throw "rattler-build failed for $($s.name)"
    }

    Add-NoarchStub $output
}

Write-Host "== stack build complete =="
