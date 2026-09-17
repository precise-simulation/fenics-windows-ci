# Build a Nuitka standalone bundle from the published FEniCSx packages.
# Run from an x64 VS2022 Native Tools PowerShell.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$EntryPoint,
    [string]$OutputDir = "output-nuitka",
    [string]$ExistingPrefix = "",
    [ValidateSet("", "tinycc", "llvm-mingw")]
    [string]$JitBackend = ""
)

$ErrorActionPreference = "Stop"
$environmentName = "fenicsx-nuitka"
$repoRoot = Split-Path -Parent $PSScriptRoot

$entry = Resolve-Path -LiteralPath $EntryPoint -ErrorAction Stop
$output = if ([IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir
} else {
    Join-Path $repoRoot $OutputDir
}
New-Item -ItemType Directory -Force -Path $output | Out-Null

if ($ExistingPrefix) {
    $envPrefix = (Resolve-Path -LiteralPath $ExistingPrefix -ErrorAction Stop).Path
    $mamba = if ($env:MAMBA_EXE) {
        $env:MAMBA_EXE
    } else {
        (Get-Command micromamba.exe -ErrorAction Stop).Source
    }
    Write-Host "== using existing FEniCSx prefix $envPrefix =="
} else {
    $conda = (Get-Command conda.exe -ErrorAction Stop).Source
    $channels = @(
        "--override-channels",
        "--strict-channel-priority",
        "-c", "precise-simulation",
        "-c", "conda-forge"
    )

    # Let the published FEniCSx packages and the solver select the current coherent
    # patch/build set. Keep only the Windows ABI/variant choices that this bundle
    # relies on explicitly; do not freeze PETSc/DOLFINx/HDF5 patch releases here.
    $packages = @(
        "python=3.12.*",
        "fenics-dolfinx",
        "fenics-libdolfinx",
        "hdf5=*=mpi_impi_*",
        "petsc=*=real_*",
        "petsc4py",
        "mpi4py",
        "metis",
        "libblas=*=*openblas",
        "nuitka=4.1.3",
        "c-compiler",
        "ordered-set"
    )

    $envInfo = & $conda env list --json | ConvertFrom-Json
    $envPrefix = $envInfo.envs |
        Where-Object { (Split-Path -Leaf $_) -eq $environmentName } |
        Select-Object -First 1

    $condaAction = if ($envPrefix) { "install" } else { "create" }
    Write-Host "== $condaAction $environmentName from public channels =="
    & $conda $condaAction --yes --name $environmentName @channels @packages
    if ($LASTEXITCODE -ne 0) { throw "Conda $condaAction failed" }

    $envPrefix = (& $conda run --name $environmentName python -c "import sys; print(sys.prefix)" |
        Select-Object -Last 1).Trim()
    if (-not (Test-Path -LiteralPath $envPrefix)) {
        throw "Could not resolve the $environmentName environment prefix"
    }

    Write-Host "== selected packages =="
    & $conda list --name $environmentName --show-channel-urls
    if ($LASTEXITCODE -ne 0) { throw "Could not list the $environmentName packages" }
}

$python = Join-Path $envPrefix "python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python executable missing from FEniCSx prefix: $python"
}

# Run Python through the environment runner rather than invoking python.exe
# directly. Windows FEniCSx runtime packages rely on activation-provided DLL and
# MPI environment state even while Nuitka is inspecting/importing modules.
if ($ExistingPrefix) {
    & $mamba run -p $envPrefix --no-capture-output python -c `
        "import nuitka, ffcx, cffi; print('Nuitka/FEniCSx standalone inputs available')"
} else {
    & $conda run --name $environmentName --no-capture-output python -c `
        "import nuitka, ffcx, cffi; print('Nuitka/FEniCSx standalone inputs available')"
}
if ($LASTEXITCODE -ne 0) {
    throw "FEniCSx prefix does not contain the required Nuitka build inputs"
}

$dllNames = @(
    "dolfinx.dll",
    "basix.dll",
    "hdf5.dll",
    "libpetsc.dll",
    "impi.dll",
    "spdlog.dll",
    "fmt.dll",
    "pugixml.dll",
    "openblas.dll",
    "metis.dll",
    "ffi-8.dll",
    "libexpat.dll",
    "szip.dll"
)
$includeDlls = foreach ($dllName in $dllNames) {
    $dllPath = Join-Path $envPrefix "Library\bin\$dllName"
    if (-not (Test-Path -LiteralPath $dllPath)) {
        throw "Missing channel-installed runtime DLL: $dllPath"
    }
    "--include-data-files=$dllPath=$dllName"
}

$nuitkaArgs = @(
    "--standalone",
    "--assume-yes-for-downloads",
    "--remove-output",
    "--output-dir=$output",
    "--output-filename=fenicsx.exe",
    "--include-package=dolfinx",
    "--include-package=basix",
    "--include-package=mpi4py",
    "--include-package=petsc4py",
    "--include-package=ufl",
    "--include-package=ffcx",
    "--include-package=cffi",
    "--include-package=setuptools",
    "--include-package-data=dolfinx",
    "--include-package-data=basix",
    "--include-package-data=petsc4py",
    "--include-package-data=ffcx"
) + $includeDlls

if ($JitBackend) {
    $jitRoot = Join-Path $envPrefix "Library\fenics-jit"
    $runtimeRoot = Join-Path $jitRoot "runtime"
    $backendRoot = Join-Path $jitRoot "backends\$JitBackend"
    if (-not (Test-Path -LiteralPath $runtimeRoot)) {
        throw "FEniCS JIT common runtime missing: $runtimeRoot"
    }
    if (-not (Test-Path -LiteralPath $backendRoot)) {
        throw "Requested FEniCS JIT backend missing: $backendRoot"
    }

    # Stage common runtime and exactly one backend. This keeps backend ownership
    # independent and permits TinyCC-only bundles even when the build prefix also
    # contains LLVM-MinGW because of the normal fenics-dolfinx dependency.
    $nuitkaArgs += "--include-data-dir=$runtimeRoot=fenics-jit/runtime"
    $nuitkaArgs += "--include-data-dir=$backendRoot=fenics-jit/backends/$JitBackend"

    # CFFI-generated modules require CPython development headers at runtime.
    # Put them at the standalone prefix include location so sysconfig can resolve
    # them from the bundle rather than from the build environment.
    $pythonInclude = Join-Path $envPrefix "Include"
    if (-not (Test-Path -LiteralPath (Join-Path $pythonInclude "Python.h"))) {
        throw "CPython development headers missing from build prefix: $pythonInclude"
    }
    $nuitkaArgs += "--include-data-dir=$pythonInclude=include"

    # FFCx passes its package-owned UFCx include directory into CFFI. Make the
    # header explicit in the standalone bundle even if package-data discovery
    # changes in a future Nuitka release.
    if ($ExistingPrefix) {
        $ffcxRoot = (& $mamba run -p $envPrefix python -c `
            "from pathlib import Path; import ffcx; print(Path(ffcx.__file__).resolve().parent)" |
            Select-Object -Last 1).Trim()
    } else {
        $ffcxRoot = (& $conda run --name $environmentName python -c `
            "from pathlib import Path; import ffcx; print(Path(ffcx.__file__).resolve().parent)" |
            Select-Object -Last 1).Trim()
    }
    if ($LASTEXITCODE -ne 0 -or -not $ffcxRoot) {
        throw "Could not resolve the FFCx package root"
    }
    $ufcxHeader = Join-Path $ffcxRoot "codegeneration\ufcx.h"
    if (-not (Test-Path -LiteralPath $ufcxHeader)) {
        throw "UFCx header missing from build prefix: $ufcxHeader"
    }
    $nuitkaArgs += "--include-data-files=$ufcxHeader=ffcx/codegeneration/ufcx.h"
}

$nuitkaArgs += @(
    "--report=$(Join-Path $output 'nuitka-report.xml')",
    $entry.Path
)

Write-Host "== Nuitka build =="
if ($ExistingPrefix) {
    & $mamba run -p $envPrefix --no-capture-output python -m nuitka @nuitkaArgs
} else {
    & $conda run --name $environmentName --no-capture-output python -m nuitka @nuitkaArgs
}
if ($LASTEXITCODE -ne 0) { throw "Nuitka build failed" }

$dist = Get-ChildItem -LiteralPath $output -Directory -Filter "*.dist" |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "fenicsx.exe") } |
    Select-Object -First 1
if (-not $dist) {
    throw "Nuitka standalone distribution containing fenicsx.exe was not found under $output"
}
Write-Host "== standalone distribution $($dist.FullName) =="

if ($JitBackend) {
    $stagedJit = Join-Path $dist.FullName "fenics-jit"
    if (-not (Test-Path -LiteralPath (Join-Path $stagedJit "runtime\fenics_jit_selector.py"))) {
        throw "staged common JIT runtime missing from standalone distribution"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $stagedJit "backends\$JitBackend"))) {
        throw "staged JIT backend missing from standalone distribution"
    }
}

Write-Host "== bundle written to $output =="
