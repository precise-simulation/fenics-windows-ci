param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path (Split-Path $PSScriptRoot)
$output = Join-Path $root "output"
$logRoot = Join-Path $root "build-logs\phase5"
$measurementRoot = Join-Path $root "build-logs\phase6-minimization"
$script = Join-Path $PSScriptRoot "phase5-functional-validation.py"
$measurementScript = Join-Path $PSScriptRoot "report-minimization-measurements.py"
$archiveMeasurementScript = Join-Path $PSScriptRoot "report-lld-archive-usage.py"
New-Item -ItemType Directory -Force $logRoot | Out-Null
Remove-Item -Recurse -Force $measurementRoot -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $measurementRoot | Out-Null
$traceRoot = Join-Path $logRoot "closure traces"
Remove-Item -Recurse -Force $traceRoot -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $traceRoot | Out-Null
$env:FENICS_JIT_MEASURE_CLOSURE = "1"
$env:FENICS_JIT_MEASURE_DIR = $traceRoot

if (-not (Test-Path $script)) {
    throw "Phase 5 Python validation script missing: $script"
}
if (-not (Test-Path $measurementScript)) {
    throw "Minimization measurement script missing: $measurementScript"
}
if (-not (Test-Path $archiveMeasurementScript)) {
    throw "LLD archive measurement script missing: $archiveMeasurementScript"
}

$channels = @()
if (Test-Path "$output/win-64/repodata.json") {
    $localChannel = "file:///$($output -replace '\\','/')"
    $channels += $localChannel
    Write-Host "Using freshly built packages from $localChannel"
}
$channels += "precise-simulation", "conda-forge"

function Invoke-Micromamba {
    param([string[]]$Arguments)
    & micromamba @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "micromamba failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

foreach ($pythonVersion in @("3.12.*", "3.13.*", "3.14.*")) {
    $tag = ($pythonVersion -replace '[^0-9]', '')
    $prefix = Join-Path $logRoot "install prefix py$tag"
    $serialCache = Join-Path $logRoot "serial cache py$tag"
    $serialDiagnostics = Join-Path $logRoot "serial diagnostics py$tag"
    $mpiCache = Join-Path $logRoot "mpi cache py$tag"
    $mpiDiagnostics = Join-Path $logRoot "mpi diagnostics py$tag"

    Write-Host "== Phase 5 functional validation: Python $pythonVersion =="
    Remove-Item -Recurse -Force $prefix, $serialCache, $serialDiagnostics, $mpiCache, $mpiDiagnostics -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force $serialDiagnostics, $mpiDiagnostics | Out-Null

    if ($prefix -notmatch " ") { throw "Phase 5 install prefix does not contain spaces: $prefix" }
    if ($serialCache -notmatch " " -or $mpiCache -notmatch " ") { throw "Phase 5 cache paths do not contain spaces" }

    $createArgs = @("create", "-y", "-p", $prefix, "--override-channels", "--strict-channel-priority")
    foreach ($channel in $channels) {
        $createArgs += @("-c", $channel)
    }
    $createArgs += @("python=$pythonVersion", "libblas=*=*openblas", "fenics-dolfinx")

    $created = $false
    try {
        Invoke-Micromamba -Arguments $createArgs
        $created = $true

        & micromamba list -p $prefix > (Join-Path $serialDiagnostics "packages.txt") 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Could not list Phase 5 environment" }
        & micromamba list -p $prefix --explicit > (Join-Path $serialDiagnostics "packages-explicit.txt") 2>&1

        $packageList = (& micromamba list -p $prefix 2>&1 | Out-String)
        if ($LASTEXITCODE -ne 0) { throw "Could not inspect Phase 5 environment" }
        foreach ($required in @("fenics-jit-runtime", "fenics-jit-llvm-mingw", "cffi", "setuptools")) {
            if ($packageList -notmatch "(?m)^\s*$([regex]::Escape($required))\s") {
                throw "Phase 5 environment is missing required package: $required"
            }
        }
        foreach ($forbidden in @("vs2022_win-64", "vswhere")) {
            if ($packageList -match "(?m)^\s*$([regex]::Escape($forbidden))\s") {
                throw "Phase 5 runtime environment contains forbidden compiler activation package: $forbidden"
            }
        }

        $sizeReport = Join-Path $measurementRoot "retained-size-report.json"
        if (-not (Test-Path $sizeReport)) {
            $toolchainRoot = Join-Path $prefix "Library\fenics-jit\backends\llvm-mingw"
            & python $measurementScript --toolchain-root $toolchainRoot --output-dir $measurementRoot
            if ($LASTEXITCODE -ne 0) {
                throw "Retained LLVM-MinGW size measurement failed"
            }
        }

        Invoke-Micromamba -Arguments @(
            "run", "-p", $prefix, "python", $script,
            "--mode", "serial",
            "--cache-dir", $serialCache,
            "--diagnostics-dir", $serialDiagnostics
        )

        $python = Join-Path $prefix "python.exe"
        $mpiexec = Get-ChildItem $prefix -Recurse -Filter mpiexec.exe -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $mpiexec) { throw "mpiexec.exe not found in Phase 5 environment: $prefix" }

        $mpiPath = @(
            $prefix,
            (Join-Path $prefix "bin"),
            (Join-Path $prefix "Scripts"),
            (Join-Path $prefix "Library\bin"),
            "$env:SystemRoot\System32",
            $env:SystemRoot
        ) -join ";"
        $pythonPath = Join-Path $prefix "Lib\site-packages"
        $mpiArgs = @(
            "-localonly", "-n", "2",
            "-env", "PATH", $mpiPath,
            "-env", "PYTHONPATH", $pythonPath,
            "-env", "FENICS_JIT_VERBOSE", "1",
            "-env", "FENICS_JIT_MEASURE_CLOSURE", "1",
            "-env", "FENICS_JIT_MEASURE_DIR", $traceRoot,
            $python, $script,
            "--mode", "mpi",
            "--cache-dir", $mpiCache,
            "--diagnostics-dir", $mpiDiagnostics
        )
        & $mpiexec.FullName @mpiArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Phase 5 MPI JIT validation failed on Python $pythonVersion"
        }

        Write-Host "Phase 5 Python $pythonVersion passed"
    }
    finally {
        if ($created) {
            & micromamba env remove -y -p $prefix 2>$null | Out-Null
        }
    }
}

& python $measurementScript --phase5-root $logRoot --output-dir $measurementRoot
if ($LASTEXITCODE -ne 0) {
    throw "Phase 5 minimization closure aggregation failed"
}
Get-Content (Join-Path $measurementRoot "closure-summary.json")

& python $archiveMeasurementScript --phase5-root $logRoot --retained-size-report (Join-Path $measurementRoot "retained-size-report.json") --output-dir $measurementRoot
if ($LASTEXITCODE -ne 0) {
    throw "LLD archive usage measurement failed"
}
Get-Content (Join-Path $measurementRoot "library-usage-v2.json")

Write-Host "Phase 5 functional matrix passed on Python 3.12-3.14"
