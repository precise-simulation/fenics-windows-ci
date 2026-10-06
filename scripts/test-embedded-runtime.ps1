# Validate the exact FEniCS embedded-runtime ZIP against a clean non-conda CPython 3.12 runtime.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Zip,
    [Parameter(Mandatory = $true)]
    [string]$Python
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$zipPath = (Resolve-Path -LiteralPath $Zip -ErrorAction Stop).Path
$pythonPath = (Resolve-Path -LiteralPath $Python -ErrorAction Stop).Path
$pythonRoot = Split-Path -Parent $pythonPath

$workRoot = Join-Path ([IO.Path]::GetTempPath()) ("fenics embedded runtime test " + [guid]::NewGuid().ToString("N"))
$runtimeRoot = Join-Path $workRoot "runtime with spaces"
$poisonRoot = Join-Path $workRoot "ambient python poison"
$cacheRoot = Join-Path $workRoot "jit cache with spaces"
New-Item -ItemType Directory -Force -Path $runtimeRoot,$poisonRoot,$cacheRoot | Out-Null

try {
    foreach ($name in @("python.exe", "python312.dll", "python3.dll", "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt")) {
        $source = Join-Path $pythonRoot $name
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $runtimeRoot $name)
        }
    }
    foreach ($name in @("Lib", "DLLs")) {
        $source = Join-Path $pythonRoot $name
        if (-not (Test-Path -LiteralPath $source -PathType Container)) {
            throw "Reference CPython is missing required directory: $source"
        }
        Copy-Item -LiteralPath $source -Destination (Join-Path $runtimeRoot $name) -Recurse
    }

    $sitePackages = Join-Path $runtimeRoot "Lib\site-packages"
    Remove-Item -LiteralPath $sitePackages -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null

    Expand-Archive -LiteralPath $zipPath -DestinationPath $runtimeRoot

    $manifestPath = Join-Path $runtimeRoot "fenics-embed-manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Embedded-runtime manifest is missing after extraction"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.format_version -ne 1 -or $manifest.platform -ne "win-x64" -or $manifest.python_abi -ne "cp312") {
        throw "Embedded-runtime manifest identity is invalid"
    }
    if ($manifest.numpy.version -ne "2.5.2" -or $manifest.jit.backend -ne "micro-clang" -or $manifest.jit.backend_version -ne "20260826") {
        throw "Embedded-runtime manifest does not describe the qualified NumPy/micro-Clang runtime"
    }

    foreach ($entry in @($manifest.files)) {
        $path = Join-Path $runtimeRoot ([string]$entry.path -replace '/', '\')
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Manifest file is missing after extraction: $($entry.path)"
        }
        $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne [string]$entry.sha256) {
            throw "Manifest hash mismatch for $($entry.path)"
        }
    }

    Set-Content -LiteralPath (Join-Path $poisonRoot "numpy.py") -Value "raise RuntimeError('ambient numpy imported')" -Encoding utf8NoBOM
    Set-Content -LiteralPath (Join-Path $poisonRoot "dolfinx.py") -Value "raise RuntimeError('ambient dolfinx imported')" -Encoding utf8NoBOM

    $runtimePython = Join-Path $runtimeRoot "python.exe"
    if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf)) {
        throw "Relocated runtime is missing python.exe"
    }

    $saved = @{}
    $names = @(
        "PATH","PYTHONPATH","PYTHONUSERBASE","PYTHONHOME","FENICS_JIT_ROOT","FENICS_JIT_COMPILER",
        "PETSC_DIR","XDG_CACHE_HOME","FENICS_JIT_VERBOSE","CC","CXX","CPP","LD","LDSHARED","INCLUDE","LIB","LIBPATH",
        "LIBRARY_PATH","CPATH","C_INCLUDE_PATH","CPLUS_INCLUDE_PATH","COMPILER_PATH","GCC_EXEC_PREFIX",
        "VSINSTALLDIR","VCINSTALLDIR","VCToolsInstallDir","WindowsSdkDir","WindowsSDKVersion",
        "UniversalCRTSdkDir","UCRTVersion","DISTUTILS_USE_SDK","MSSdk"
    )
    foreach ($name in $names) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }

    try {
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        $env:PYTHONPATH = $poisonRoot
        $env:PYTHONUSERBASE = $poisonRoot
        Remove-Item Env:PYTHONHOME,Env:FENICS_JIT_ROOT,Env:FENICS_JIT_COMPILER,Env:PETSC_DIR -ErrorAction SilentlyContinue
        $env:XDG_CACHE_HOME = $cacheRoot
        $env:FENICS_JIT_VERBOSE = "1"
        foreach ($name in @(
            "CC","CXX","CPP","LD","LDSHARED","INCLUDE","LIB","LIBPATH","LIBRARY_PATH","CPATH",
            "C_INCLUDE_PATH","CPLUS_INCLUDE_PATH","COMPILER_PATH","GCC_EXEC_PREFIX","VSINSTALLDIR",
            "VCINSTALLDIR","VCToolsInstallDir","WindowsSdkDir","WindowsSDKVersion","UniversalCRTSdkDir",
            "UCRTVersion","DISTUTILS_USE_SDK","MSSdk"
        )) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
        Get-ChildItem Env: |
            Where-Object { $_.Name -like "VSCMD_*" } |
            ForEach-Object { Remove-Item "Env:$($_.Name)" -ErrorAction SilentlyContinue }

        $importProbe = @'
from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve()
assert Path(sys.prefix).resolve() == root, (sys.prefix, root)
import fenics_embed_runtime
assert fenics_embed_runtime.activate(root) == root
import numpy, dolfinx, petsc4py
from mpi4py import MPI
from dolfinx import mesh
assert numpy.__version__ == "2.5.2"
assert Path(numpy.__file__).resolve().is_relative_to(root / "Lib" / "site-packages")
assert Path(dolfinx.__file__).resolve().is_relative_to(root / "Lib" / "site-packages")
assert Path(petsc4py.__file__).resolve().is_relative_to(root / "Lib" / "site-packages")
assert Path(petsc4py.get_config()["PETSC_DIR"]).resolve() == root / "Library"
mesh.create_unit_square(MPI.COMM_SELF, 4, 4)
print("fenics_embed_import=pass")
'@
        & $runtimePython -I -c $importProbe $runtimeRoot
        if ($LASTEXITCODE -ne 0) {
            throw "Relocated FEniCS import/mesh probe failed"
        }

        $poisson = Join-Path $repoRoot "scripts\test-poisson.py"
        $solveProbe = @'
from pathlib import Path
import sys
import fenics_embed_runtime
fenics_embed_runtime.activate()
script = Path(sys.argv[1]).resolve()
code = compile(script.read_text(encoding="utf-8"), str(script), "exec")
exec(code, {"__name__": "__main__", "__file__": str(script)})
'@
        $solveOutput = & $runtimePython -I -c $solveProbe $poisson 2>&1
        $solveStatus = $LASTEXITCODE
        $solveOutput | ForEach-Object { Write-Host $_ }
        if ($solveStatus -ne 0) {
            throw "Fresh relocated FEniCS Poisson JIT/solve failed"
        }
        $solveText = $solveOutput -join [Environment]::NewLine
        if ($solveText -notmatch "L2 error:") {
            throw "Poisson solve did not report its numerical result"
        }
        if ($solveText -notmatch "FEniCS JIT backend:\s+micro-clang") {
            throw "Fresh JIT did not report the bundled micro-Clang backend"
        }
        $jitModules = @(Get-ChildItem -LiteralPath $cacheRoot -Filter "*.pyd" -File -Recurse -ErrorAction SilentlyContinue)
        if ($jitModules.Count -eq 0) {
            throw "Fresh FFCx JIT produced no cache .pyd modules"
        }
    }
    finally {
        foreach ($name in $names) {
            [Environment]::SetEnvironmentVariable($name, $saved[$name], "Process")
        }
    }

    Write-Host "fenics_embedded_runtime_test=pass"
}
finally {
    Remove-Item -LiteralPath $workRoot -Recurse -Force -ErrorAction SilentlyContinue
}
