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
    & $mamba run -p $envPrefix python -c `
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
# Nuitka's dependency scanner discovers these DLLs from the extension modules
# when building an existing, fully resolved prefix. Adding the same binaries as
# data files creates a fatal data-file/DLL destination conflict. Preserve the
# legacy explicit staging for the self-created environment path only.
$includeDlls = if ($ExistingPrefix) {
    @()
} else {
    @(
        foreach ($dllName in $dllNames) {
            $dllPath = Join-Path $envPrefix "Library\bin\$dllName"
            if (-not (Test-Path -LiteralPath $dllPath)) {
                throw "Missing channel-installed runtime DLL: $dllPath"
            }
            "--include-data-files=$dllPath=$dllName"
        }
    )
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
    "--include-distribution-metadata=cffi",
    "--include-distribution-metadata=setuptools",
    "--include-package-data=dolfinx",
    "--include-package-data=basix",
    "--include-package-data=petsc4py",
    "--include-package-data=ffcx",
    "--include-package-data=cffi"
) + $includeDlls

if ($JitBackend) {
    $nuitkaRuntimeConfig = Join-Path $PSScriptRoot "fenicsx-nuitka-runtime.nuitka-package.config.yml"
    if (-not (Test-Path -LiteralPath $nuitkaRuntimeConfig)) {
        throw "Nuitka runtime package configuration is missing: $nuitkaRuntimeConfig"
    }
    $nuitkaArgs += "--user-package-configuration-file=$nuitkaRuntimeConfig"

    # petsc4py/PETSc.py is only a bootstrap shim. If Nuitka freezes it under
    # the public petsc4py.PETSc name, petsc4py's dynamic extension loader
    # resolves back to the shim and stack-overflows. Exclude that shim; the
    # package config hook loads the staged native PETSc.pyd explicitly.
    $nuitkaArgs += "--nofollow-import-to=petsc4py.PETSc"

    # Runtime FFCx JIT intentionally calls cffi.FFI.compile(). Nuitka 4.1.3
    # disables the CFFI recompiler by default through its anti-bloat plugin;
    # opt this standalone JIT build back into the supported recompiler path.
    $nuitkaArgs += "--noinclude-custom-mode=cffi_recompiler:allow"

    # Nuitka 4.1.3's setuptools import hack discovers most top-level vendored
    # packages, but jaraco.functools is still omitted from the frozen module
    # graph. Put the vendor root on Python's initial search path and force this
    # one package as a root so CFFI/setuptools can import it at runtime.
    $setuptoolsVendor = Join-Path $envPrefix "Lib\site-packages\setuptools\_vendor"
    if (-not (Test-Path -LiteralPath (Join-Path $setuptoolsVendor "jaraco\functools\__init__.py"))) {
        throw "Setuptools jaraco.functools vendor package is missing: $setuptoolsVendor"
    }
    $nuitkaArgs += "--include-package=jaraco.functools"

    $jitRoot = Join-Path $envPrefix "Library\fenics-jit"
    $runtimeRoot = Join-Path $jitRoot "runtime"
    $backendRoot = Join-Path $jitRoot "backends\$JitBackend"
    if (-not (Test-Path -LiteralPath $runtimeRoot)) {
        throw "FEniCS JIT common runtime missing: $runtimeRoot"
    }
    if (-not (Test-Path -LiteralPath $backendRoot)) {
        throw "Requested FEniCS JIT backend missing: $backendRoot"
    }

    # Keep common runtime and backend ownership independent. Python source files
    # and compiler executables are intentionally copied into the finished .dist
    # tree below because Nuitka filters those file types from --include-data-dir.

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
$previousPythonPath = $env:PYTHONPATH
try {
    if ($JitBackend) {
        $env:PYTHONPATH = if ($previousPythonPath) {
            "$setuptoolsVendor$([IO.Path]::PathSeparator)$previousPythonPath"
        } else {
            $setuptoolsVendor
        }
    }

    if ($ExistingPrefix) {
        & $mamba run -p $envPrefix python -m nuitka @nuitkaArgs
    } else {
        & $conda run --name $environmentName --no-capture-output python -m nuitka @nuitkaArgs
    }
    if ($LASTEXITCODE -ne 0) { throw "Nuitka build failed" }
} finally {
    if ($null -eq $previousPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONPATH = $previousPythonPath
    }
}

$dist = Get-ChildItem -LiteralPath $output -Directory -Filter "*.dist" |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "fenicsx.exe") } |
    Select-Object -First 1
if (-not $dist) {
    throw "Nuitka standalone distribution containing fenicsx.exe was not found under $output"
}
Write-Host "== standalone distribution $($dist.FullName) =="

# DOLFINx resolves PETSc for its ctypes helpers via
# petsc4py.get_config()["PETSC_DIR"] and the Windows <PETSC_DIR>/bin layout.
# The post-load hook points PETSC_DIR at the standalone bundle root, so mirror
# the already bundled libpetsc.dll into bin without changing its bytes.
$bundledPetsc = Join-Path $dist.FullName "libpetsc.dll"
if (-not (Test-Path -LiteralPath $bundledPetsc -PathType Leaf)) {
    throw "Nuitka standalone distribution is missing libpetsc.dll"
}
$stagedPetscBin = Join-Path $dist.FullName "bin"
New-Item -ItemType Directory -Force -Path $stagedPetscBin | Out-Null
$stagedPetscDll = Join-Path $stagedPetscBin "libpetsc.dll"
$bundledPetscHash = (Get-FileHash -LiteralPath $bundledPetsc -Algorithm SHA256).Hash
if (Test-Path -LiteralPath $stagedPetscDll -PathType Leaf) {
    $stagedPetscHash = (Get-FileHash -LiteralPath $stagedPetscDll -Algorithm SHA256).Hash
    if ($stagedPetscHash -ne $bundledPetscHash) {
        throw "bundle/bin/libpetsc.dll differs from the Nuitka-staged PETSc runtime"
    }
} else {
    Copy-Item -LiteralPath $bundledPetsc -Destination $stagedPetscDll
}

if ($JitBackend) {
    # The petsc4py bootstrap hook above depends on the native extension
    # remaining a physical file so PathFinder can load it dynamically.
    $sourcePetsc4py = Get-ChildItem -LiteralPath (Join-Path $envPrefix "Lib\site-packages\petsc4py\lib") `
        -Filter "PETSc*.pyd" -File | Select-Object -First 1
    if (-not $sourcePetsc4py) {
        throw "petsc4py native PETSc extension was not found in the build prefix"
    }
    $stagedPetsc4pyDir = Join-Path $dist.FullName "petsc4py\lib"
    New-Item -ItemType Directory -Force -Path $stagedPetsc4pyDir | Out-Null
    $stagedPetsc4py = Join-Path $stagedPetsc4pyDir $sourcePetsc4py.Name
    $sourcePetsc4pyHash = (Get-FileHash -LiteralPath $sourcePetsc4py.FullName -Algorithm SHA256).Hash
    if (Test-Path -LiteralPath $stagedPetsc4py -PathType Leaf) {
        $stagedPetsc4pyHash = (Get-FileHash -LiteralPath $stagedPetsc4py -Algorithm SHA256).Hash
        if ($stagedPetsc4pyHash -ne $sourcePetsc4pyHash) {
            throw "Nuitka-staged petsc4py PETSc extension differs from the package-owned extension"
        }
    } else {
        Copy-Item -LiteralPath $sourcePetsc4py.FullName -Destination $stagedPetsc4py
    }
}

# Intel MPI loads part of its runtime dynamically, so Nuitka's PE dependency
# scan only sees impi.dll and can omit package-owned fabric/launcher binaries.
# Stage every DLL/EXE owned by the installed impi_rt package into the .dist root.
# Keep Nuitka-owned files when they are byte-identical and reject collisions.
$impiMeta = Get-ChildItem -LiteralPath (Join-Path $envPrefix "conda-meta") `
    -Filter "impi_rt-*.json" -File | Select-Object -First 1
if (-not $impiMeta) {
    throw "installed impi_rt conda metadata was not found"
}
$impiRecord = Get-Content -LiteralPath $impiMeta.FullName -Raw | ConvertFrom-Json
$impiRuntimeFiles = @(
    $impiRecord.files |
        Where-Object {
            $extension = [IO.Path]::GetExtension([string]$_).ToLowerInvariant()
            $extension -eq ".dll" -or $extension -eq ".exe"
        }
)
if (-not $impiRuntimeFiles) {
    throw "impi_rt metadata contains no runtime DLL/EXE payload"
}

$stagedImpi = @()
foreach ($relative in $impiRuntimeFiles) {
    $relativeText = [string]$relative
    $source = Join-Path $envPrefix ($relativeText -replace '/', '\\')
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "impi_rt-owned runtime file is missing from prefix: $relativeText"
    }
    $destination = Join-Path $dist.FullName ([IO.Path]::GetFileName($source))
    $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        $destinationHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($destinationHash -ne $sourceHash) {
            throw "impi_rt runtime collision for $destination"
        }
    } else {
        Copy-Item -LiteralPath $source -Destination $destination
    }
    $stagedImpi += [pscustomobject]@{
        package_path = $relativeText.Replace('\\','/')
        bundle_name = [IO.Path]::GetFileName($destination)
        bytes = (Get-Item -LiteralPath $destination).Length
        sha256 = $sourceHash
    }
}
$stagedImpi |
    Sort-Object package_path |
    ConvertTo-Json -Depth 4 |
    Set-Content -LiteralPath (Join-Path $dist.FullName "impi-runtime-files.json") -Encoding utf8

if ($JitBackend) {
    $stagedJit = Join-Path $dist.FullName "fenics-jit"
    $stagedBackends = Join-Path $stagedJit "backends"
    New-Item -ItemType Directory -Force -Path $stagedJit, $stagedBackends | Out-Null

    # Nuitka treats .py and .exe as code/binaries rather than ordinary data and
    # filters them from --include-data-dir. Stage the package-owned JIT payload
    # explicitly after the standalone tree is created so tcc.exe, the selector,
    # adapters, metadata, headers, libraries, and licenses remain byte-for-byte
    # owned by their original conda packages.
    Copy-Item -LiteralPath $runtimeRoot -Destination $stagedJit -Recurse -Force
    Copy-Item -LiteralPath $backendRoot -Destination $stagedBackends -Recurse -Force

    if (-not (Test-Path -LiteralPath (Join-Path $stagedJit "runtime\fenics_jit_selector.py"))) {
        throw "staged common JIT runtime missing from standalone distribution"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $stagedJit "backends\$JitBackend\tcc.exe")) -and $JitBackend -eq "tinycc") {
        throw "staged TinyCC executable missing from standalone distribution"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $stagedJit "backends\$JitBackend"))) {
        throw "staged JIT backend missing from standalone distribution"
    }
}

Write-Host "== bundle written to $output =="
