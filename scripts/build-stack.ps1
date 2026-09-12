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
New-Item -ItemType Directory -Force $logOutput | Out-Null

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

$rattlerVersion = (& $rattler --version 2>&1 | Out-String).Trim()
Write-Host "rattler-build: $rattlerVersion"
Set-Content (Join-Path $logOutput "tooling.txt") "rattler-build: $rattlerVersion"
Copy-Item (Resolve-Path $PlanFile) (Join-Path $logOutput "plan.json")

function Add-NoarchStub {
    param([string]$Dir)
    $na = Join-Path $Dir "noarch"
    New-Item -ItemType Directory -Force $na | Out-Null
    Set-Content (Join-Path $na "repodata.json") '{"info":{"subdir":"noarch"},"packages":{},"packages.conda":{}}'
}

function Get-RepodataRecords {
    param([string]$RepodataPath)

    $repo = Get-Content $RepodataPath -Raw | ConvertFrom-Json
    $records = @()
    foreach ($sectionName in @("packages", "packages.conda")) {
        $property = $repo.PSObject.Properties[$sectionName]
        if ($null -ne $property -and $null -ne $property.Value) {
            $records += @($property.Value.PSObject.Properties | ForEach-Object { $_.Value })
        }
    }
    return $records
}

function Assert-LocalPackageVersion {
    param(
        [string]$Stage,
        [string]$PackageName,
        [string]$Version
    )

    $repodataPath = Join-Path $output "win-64/repodata.json"
    if (-not (Test-Path $repodataPath)) {
        throw "Local output channel has no win-64/repodata.json after building $Stage"
    }

    $records = @(Get-RepodataRecords $repodataPath)
    $matches = @($records | Where-Object { $_.name -eq $PackageName -and $_.version -eq $Version })
    if ($matches.Count -eq 0) {
        $available = @(
            $records |
                Where-Object { $_.name -eq $PackageName } |
                ForEach-Object { "$($_.version) $($_.build)" }
        ) -join "; "
        if (-not $available) { $available = "<none>" }
        throw "Expected local package $PackageName==$Version after building $Stage; available: $available"
    }

    $selected = @($matches | ForEach-Object { "$($_.name)-$($_.version)-$($_.build)" })
    Write-Host "local channel verified for ${Stage}: $($selected -join ', ')"

    Copy-Item $repodataPath (Join-Path $logOutput "$Stage-repodata.json") -Force
    [ordered]@{
        stage = $Stage
        expected_name = $PackageName
        expected_version = $Version
        matching_packages = $matches
    } | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $logOutput "$Stage-package-manifest.json")
}

$plan = (Get-Content $PlanFile | ConvertFrom-Json)

$stages = @(
    @{ name = "hdf5";      package = "hdf5";                    recipe = "$root/recipes/hdf5/recipe.yaml";                    variants = "$root/recipes/hdf5/variants-win64.yaml";     plan = "hdf5" },
    @{ name = "petsc";     package = "petsc";                   recipe = "$root/recipes/petsc/recipe.yaml";                   variants = "$root/recipes/petsc/variants-win64.yaml";    plan = "petsc" },
    @{ name = "petsc4py";  package = "petsc4py";                recipe = "$root/recipes/petsc4py/recipe.yaml";                variants = "$root/recipes/petsc4py/variants-win64.yaml"; plan = "petsc4py" },
    # Phase 4B gives the common Windows JIT helper its own package/file owner.
    # Build it before the default LLVM-MinGW backend so the latter's runtime
    # dependency and package test resolve against the exact candidate artifact.
    @{ name = "jit-runtime"; package = "fenics-jit-runtime"; recipe = "$root/recipes/fenics-jit-runtime/recipe.yaml"; variants = $null; plan = "dolfinx"; version = "0.1.0" },
    @{ name = "jit-llvm-mingw"; package = "fenics-jit-llvm-mingw"; recipe = "$root/recipes/fenics-jit-llvm-mingw/recipe.yaml"; variants = $null; plan = "dolfinx"; version = "20260826" },
    @{ name = "dolfinx";   package = "fenics-dolfinx";          recipe = "$root/recipes/dolfinx/recipe.yaml";                 variants = "$root/recipes/dolfinx/variants-win64.yaml";  plan = "dolfinx" }
)

foreach ($s in $stages) {
    $planKey = [string]$s.plan
    if (-not $plan.$planKey.rebuild) {
        Write-Host "== skip $($s.name) (unchanged) =="
        continue
    }
    $expectedVersion = if ($s.version) { [string]$s.version } else { [string]$plan.$planKey.version }
    Write-Host "== building $($s.name) $expectedVersion =="

    $channels = @()
    if (Test-Path "$output/win-64/repodata.json") { $channels += "file:///$($output -replace '\\','/')" }
    $channels += "precise-simulation", "conda-forge"
    Write-Host "channels (strict priority): $($channels -join ' -> ')"

    Copy-Item $s.recipe (Join-Path $logOutput "$($s.name)-recipe.yaml") -Force
    $variantArgs = @()
    if ($s.variants) {
        Copy-Item $s.variants (Join-Path $logOutput "$($s.name)-variants-win64.yaml") -Force
        $variantArgs = @("--variant-config", $s.variants)
    }
    Set-Content (Join-Path $logOutput "$($s.name)-channels.txt") ($channels -join [Environment]::NewLine)

    $stageStart = Get-Date
    $stageLog = Join-Path $logOutput "$($s.name)-rattler.log"
    & $rattler build `
        --recipe $s.recipe `
        @variantArgs `
        --output-dir $output `
        --channel-priority strict `
        @($channels | ForEach-Object { "-c"; $_ }) 2>&1 | Tee-Object -FilePath $stageLog
    $buildExitCode = $LASTEXITCODE

    if ($buildExitCode -ne 0) {
        # Only inspect logs touched by this stage. Previous stages can leave
        # configure/CMake logs under output/bld, and selecting the globally
        # newest file has produced misleading diagnostics in the past.
        $stageFloor = $stageStart.AddSeconds(-2)
        $clog = Get-ChildItem "$output/bld" -Recurse -Filter "configure.log" -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -ge $stageFloor } |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        $cmakeLog = Get-ChildItem "$output/bld" -Recurse -Filter "CMakeConfigureLog.yaml" -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -ge $stageFloor } |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        $repodataPath = Join-Path $output "win-64/repodata.json"
        if (Test-Path $repodataPath) {
            Copy-Item $repodataPath (Join-Path $logOutput "$($s.name)-failure-repodata.json") -Force
        }
        if ($clog) {
            Write-Host "===== tail of $($clog.FullName) ====="
            Get-Content $clog.FullName -Tail 60 | Write-Host
            Copy-Item $clog.FullName (Join-Path $logOutput "$($s.name)-configure.log")
        }
        if ($cmakeLog) {
            Copy-Item $cmakeLog.FullName (Join-Path $logOutput "$($s.name)-CMakeConfigureLog.yaml")
        }
        Write-Host "===== tail of $stageLog ====="
        Get-Content $stageLog -Tail 100 | Write-Host
        throw "rattler-build failed for $($s.name) (exit code $buildExitCode)"
    }

    Add-NoarchStub $output
    Assert-LocalPackageVersion -Stage $s.name -PackageName $s.package -Version $expectedVersion
}

Write-Host "== stack build complete =="
