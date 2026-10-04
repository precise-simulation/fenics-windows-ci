param(
    [switch]$Preview
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot | Split-Path
$output = Join-Path $root "output"
$logOutput = Join-Path $root "build-logs"
New-Item -ItemType Directory -Force $logOutput | Out-Null

$channels = @()
if (Test-Path "$output/win-64/repodata.json") {
    $localChannel = "file:///$($output -replace '\\','/')"
    $channels += $localChannel
    Write-Host "Using freshly built packages from $localChannel"
} else {
    Write-Host "No local build output found; testing published packages only."
}
$channels += "precise-simulation"

if ($Preview) {
    $pythonVersions = @("3.15.*")
    $channels += "conda-forge/label/python_dev", "conda-forge/label/python_rc", "conda-forge"
} else {
    # Phase 4 runtime metadata/JIT gate covers every supported interpreter.
    $pythonVersions = @("3.12.*", "3.13.*", "3.14.*")
    $channels += "conda-forge"
}

function Invoke-Micromamba {
    param([string[]]$Arguments)
    & micromamba @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "micromamba failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

function Save-EnvironmentProvenance {
    param(
        [string]$EnvironmentName,
        [string]$Tag
    )

    & micromamba list -n $EnvironmentName > (Join-Path $logOutput "abi3-$Tag-list.txt") 2>&1
    if ($LASTEXITCODE -eq 0) {
        & micromamba list -n $EnvironmentName --explicit > (Join-Path $logOutput "abi3-$Tag-explicit.txt") 2>&1
    }
}

foreach ($pythonVersion in $pythonVersions) {
    $tag = ($pythonVersion -replace '[^0-9]', '')
    $modeTag = if ($Preview) { "py${tag}-preview" } else { "py${tag}" }
    $envName = "fenics-abi3-$tag"
    if ($Preview) { $envName += "-preview" }

    Write-Host "== ABI3 consumer test: Python $pythonVersion =="
    & micromamba env remove -y -n $envName 2>$null | Out-Null

    $createArgs = @(
        "create", "-y", "-n", $envName,
        "--override-channels",
        "--strict-channel-priority"
    )
    foreach ($channel in $channels) {
        $createArgs += @("-c", $channel)
    }
    $createArgs += @(
        "python=$pythonVersion",
        "libblas=*=*openblas",
        "fenics-dolfinx"
    )

    $environmentCreated = $false
    try {
        try {
            Invoke-Micromamba -Arguments $createArgs
            $environmentCreated = $true
        }
        catch {
            if ($Preview) {
                Write-Warning "Python 3.15 ecosystem not solvable yet — preview skipped"
                Write-Warning $_.Exception.Message
                continue
            }
            throw
        }

        Save-EnvironmentProvenance -EnvironmentName $envName -Tag $modeTag

        if (-not $Preview) {
            $packageList = (& micromamba list -n $envName 2>&1 | Out-String)
            if ($LASTEXITCODE -ne 0) {
                throw "Could not inspect Phase 4 consumer environment"
            }
            foreach ($required in @("fenics-jit-runtime", "fenics-jit-micro-clang", "cffi", "setuptools")) {
                if ($packageList -notmatch "(?m)^\s*$([regex]::Escape($required))\s") {
                    throw "Phase 4 runtime environment is missing required package: $required"
                }
            }
            foreach ($forbidden in @("fenics-jit-llvm-mingw", "fenics-jit-tinycc", "vs2022_win-64", "vswhere")) {
                if ($packageList -match "(?m)^\s*$([regex]::Escape($forbidden))\s") {
                    throw "Phase 4 runtime environment still contains compiler activation package: $forbidden"
                }
            }
        }

        Invoke-Micromamba -Arguments @(
            "run", "-n", $envName,
            "python", "-c",
            "import sys, dolfinx, petsc4py; print(sys.version); print('DOLFINx', dolfinx.__version__); print('petsc4py', petsc4py.__version__)"
        )

        Invoke-Micromamba -Arguments @(
            "run", "-n", $envName,
            "python", "-c",
            "from mpi4py import MPI; from dolfinx import mesh; mesh.create_unit_square(MPI.COMM_SELF, 4, 4); print('serial ABI3 smoke test OK')"
        )

        if (-not $Preview) {
            # Exercise the ordinary user path: no explicit helper activation and
            # no CI patching of FFCx. DOLFINx must enter the packaged runtime
            # helper automatically and perform a fresh JIT.
            $jitCache = Join-Path $logOutput "phase4-jit-$modeTag-cache"
            $jitLog = Join-Path $logOutput "phase4-jit-$modeTag.txt"
            Remove-Item -Recurse -Force $jitCache -ErrorAction SilentlyContinue
            New-Item -ItemType Directory -Force $jitCache | Out-Null

            $savedXdgCache = $env:XDG_CACHE_HOME
            $savedJitVerbose = $env:FENICS_JIT_VERBOSE
            $hadCompiler = Test-Path Env:FENICS_JIT_COMPILER
            $savedCompiler = $env:FENICS_JIT_COMPILER
            try {
                Remove-Item Env:FENICS_JIT_COMPILER -ErrorAction SilentlyContinue
                $env:XDG_CACHE_HOME = $jitCache
                $env:FENICS_JIT_VERBOSE = "1"
                $jitStopwatch = [Diagnostics.Stopwatch]::StartNew()
                & micromamba run -n $envName python (Join-Path $root "scripts/test-poisson.py") 2>&1 |
                    Tee-Object -FilePath $jitLog
                if ($LASTEXITCODE -ne 0) {
                    throw "Phase 4 fresh Poisson JIT failed on Python $pythonVersion"
                }
                $jitStopwatch.Stop()
                if ($jitStopwatch.Elapsed.TotalSeconds -gt 20.0) {
                    throw "Default micro-Clang Poisson JIT sanity bound exceeded on Python ${pythonVersion}: $($jitStopwatch.Elapsed.TotalSeconds)s"
                }
            }
            finally {
                $env:XDG_CACHE_HOME = $savedXdgCache
                $env:FENICS_JIT_VERBOSE = $savedJitVerbose
                if ($hadCompiler) {
                    $env:FENICS_JIT_COMPILER = $savedCompiler
                } else {
                    Remove-Item Env:FENICS_JIT_COMPILER -ErrorAction SilentlyContinue
                }
            }

            $jitText = Get-Content $jitLog -Raw
            if ($jitText -notmatch "FEniCS JIT backend:\s+micro-clang") {
                throw "Direct DOLFINx JIT did not report automatic micro-Clang default activation"
            }
            $jitModules = @(Get-ChildItem (Join-Path $jitCache "fenics") -Filter "*.pyd" -File -Recurse -ErrorAction SilentlyContinue)
            if ($jitModules.Count -eq 0) {
                throw "Phase 4 fresh Poisson solve produced no JIT modules"
            }

            # Prove the same implicit default under two-rank MPI. Rank 0 must
            # compile while rank 1 consumes the shared cache.
            $prefix = Join-Path $env:MAMBA_ROOT_PREFIX "envs\$envName"
            $python = Join-Path $prefix "python.exe"
            $mpiexec = Get-ChildItem $prefix -Recurse -Filter mpiexec.exe -File -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if (-not $mpiexec) {
                throw "mpiexec.exe not found in default micro-Clang environment"
            }
            $mpiCache = Join-Path $logOutput "phase4-mpi-$modeTag-cache"
            $mpiLog = Join-Path $logOutput "phase4-mpi-$modeTag.txt"
            Remove-Item -Recurse -Force $mpiCache -ErrorAction SilentlyContinue

            $hadMpiCompiler = Test-Path Env:FENICS_JIT_COMPILER
            $savedMpiCompiler = $env:FENICS_JIT_COMPILER
            try {
                Remove-Item Env:FENICS_JIT_COMPILER -ErrorAction SilentlyContinue
                $mpiPath = @(
                    $prefix,
                    (Join-Path $prefix "Scripts"),
                    (Join-Path $prefix "Library\bin"),
                    "$env:SystemRoot\System32",
                    $env:SystemRoot
                ) -join ";"
                $pythonPath = Join-Path $prefix "Lib\site-packages"
                & $mpiexec.FullName -localonly -n 2 `
                    -env PATH $mpiPath `
                    -env PYTHONPATH $pythonPath `
                    -env FENICS_JIT_VERBOSE 1 `
                    $python (Join-Path $root "scripts/micro-clang-jit/default-mpi-proof.py") $mpiCache 2>&1 |
                    Tee-Object -FilePath $mpiLog
                if ($LASTEXITCODE -ne 0) {
                    throw "Default micro-Clang MPI proof failed on Python $pythonVersion"
                }
            }
            finally {
                if ($hadMpiCompiler) {
                    $env:FENICS_JIT_COMPILER = $savedMpiCompiler
                } else {
                    Remove-Item Env:FENICS_JIT_COMPILER -ErrorAction SilentlyContinue
                }
            }
        }
    }
    catch {
        # If creation succeeded, any failure below this point is a real
        # consumer/import/runtime failure rather than preview-channel lag.
        if ($environmentCreated) {
            Save-EnvironmentProvenance -EnvironmentName $envName -Tag "$modeTag-failure"
        }
        throw
    }
    finally {
        # A failed preview solve never created an environment. Avoid running a
        # failing cleanup command in that case, since its native exit code can
        # otherwise make an intentionally skipped preview step fail.
        if ($environmentCreated) {
            & micromamba env remove -y -n $envName 2>$null | Out-Null
        }
    }
}

# A preview solve failure is intentionally non-fatal. Native-command failures
# leave $LASTEXITCODE nonzero even after they are caught, so explicitly return
# success after all preview iterations. Real import/runtime failures throw
# above and therefore never reach this point.
if ($Preview) {
    exit 0
}
