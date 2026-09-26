param(
    [Parameter(Mandatory = $true)][string]$PythonPrefix,
    [Parameter(Mandatory = $true)][string]$ToolchainRoot,
    [Parameter(Mandatory = $true)][string]$ReferenceDriver,
    [string]$WorkDir = "micro clang phase1 work with spaces",
    [string]$DiagnosticsDir = "micro-clang-phase1-evidence"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$pythonPrefixPath = [IO.Path]::GetFullPath($PythonPrefix)
$toolchain = [IO.Path]::GetFullPath($ToolchainRoot)
$reference = [IO.Path]::GetFullPath($ReferenceDriver)
$work = [IO.Path]::GetFullPath($WorkDir)
$diagnostics = [IO.Path]::GetFullPath($DiagnosticsDir)
$python = Join-Path $pythonPrefixPath "python.exe"
$runtimeHelper = Join-Path $repoRoot "recipes\fenics-jit-llvm-mingw\fenics_jit_runtime.py"
$minimalProof = Join-Path $repoRoot "scripts\llvm-mingw-jit\minimal-cffi-proof.py"
$poissonProof = Join-Path $PSScriptRoot "phase1-poisson-proof.py"
$contract = Join-Path $PSScriptRoot "phase1-contract.py"
$poissonScript = Join-Path $repoRoot "scripts\test-poisson.py"

foreach ($path in @(
    $python,
    $toolchain,
    $reference,
    $runtimeHelper,
    $minimalProof,
    $poissonProof,
    $contract,
    $poissonScript
)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required Phase-1 input missing: $path"
    }
}

Remove-Item -Recurse -Force $work, $diagnostics -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $work, $diagnostics | Out-Null

& $python $contract prepare --toolchain-root $toolchain --python-prefix $pythonPrefixPath --runtime-helper $runtimeHelper --reference-driver $reference --output-dir (Join-Path $diagnostics "contract")
if ($LASTEXITCODE -ne 0) {
    throw "micro-Clang ABI/driver contract preparation failed"
}

$normalBackend = Join-Path $pythonPrefixPath "Library\fenics-jit\backends\llvm-mingw"
$disabledBackend = "$normalBackend.disabled-for-micro-clang-phase1"
$normalBackendMoved = $false
if (Test-Path -LiteralPath $normalBackend) {
    if (Test-Path -LiteralPath $disabledBackend) {
        Remove-Item -Recurse -Force $disabledBackend
    }
    Move-Item -LiteralPath $normalBackend -Destination $disabledBackend
    $normalBackendMoved = $true
}

$poisonRoot = Join-Path $work "ambient poison"
$environmentKeys = @(
    "VSINSTALLDIR", "VCINSTALLDIR", "VCToolsInstallDir",
    "INCLUDE", "LIB", "LIBPATH", "LIBRARY_PATH",
    "WindowsSdkDir", "WindowsSDKVersion",
    "UniversalCRTSdkDir", "UCRTVersion",
    "DISTUTILS_USE_SDK", "MSSdk",
    "CC", "CXX", "CPP", "LD", "LDSHARED",
    "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH",
    "COMPILER_PATH", "GCC_EXEC_PREFIX", "VSCMD_ARG_TGT_ARCH"
)
$savedEnvironment = @{}
foreach ($key in $environmentKeys) {
    $savedEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
}

try {
    $env:VSINSTALLDIR = Join-Path $poisonRoot "Microsoft Visual Studio"
    $env:VCINSTALLDIR = Join-Path $poisonRoot "Microsoft Visual Studio\VC"
    $env:VCToolsInstallDir = Join-Path $poisonRoot "Microsoft Visual Studio\VC\Tools"
    $env:INCLUDE = Join-Path $poisonRoot "Windows Kits\Include"
    $env:LIB = Join-Path $poisonRoot "Windows Kits\Lib"
    $env:LIBPATH = Join-Path $poisonRoot "Windows Kits\LibPath"
    $env:LIBRARY_PATH = Join-Path $poisonRoot "fake-library-path"
    $env:WindowsSdkDir = Join-Path $poisonRoot "Windows Kits"
    $env:WindowsSDKVersion = "poison"
    $env:UniversalCRTSdkDir = Join-Path $poisonRoot "Windows Kits\UCRT"
    $env:UCRTVersion = "poison"
    $env:DISTUTILS_USE_SDK = "1"
    $env:MSSdk = "1"
    $env:CC = "cl.exe"
    $env:CXX = "cl.exe"
    $env:CPP = "cl.exe /E"
    $env:LD = "link.exe"
    $env:LDSHARED = "link.exe /DLL"
    $env:CPATH = Join-Path $poisonRoot "cp"
    $env:C_INCLUDE_PATH = Join-Path $poisonRoot "c-include"
    $env:CPLUS_INCLUDE_PATH = Join-Path $poisonRoot "cxx-include"
    $env:COMPILER_PATH = Join-Path $poisonRoot "compiler-path"
    $env:GCC_EXEC_PREFIX = Join-Path $poisonRoot "gcc-prefix"
    $env:VSCMD_ARG_TGT_ARCH = "x64"

    $minimalWork = Join-Path $work "minimal cffi with spaces"
    $minimalDiagnostics = Join-Path $diagnostics "minimal"
    & $python $minimalProof --work-dir $minimalWork --diagnostics-dir $minimalDiagnostics --toolchain-root $toolchain --python-prefix $pythonPrefixPath
    if ($LASTEXITCODE -ne 0) {
        throw "private micro-Clang minimal CFFI proof failed"
    }

    $poissonCacheHome = Join-Path $work "poisson cache with spaces"
    $poissonCache = Join-Path $poissonCacheHome "fenics"
    $poissonDiagnostics = Join-Path $diagnostics "poisson"
    New-Item -ItemType Directory -Force $poissonCache, $poissonDiagnostics | Out-Null
    & $python $poissonProof --poisson-script $poissonScript --cache-dir $poissonCache --diagnostics-dir $poissonDiagnostics --toolchain-root $toolchain --python-prefix $pythonPrefixPath
    if ($LASTEXITCODE -ne 0) {
        throw "private micro-Clang fresh Poisson proof failed"
    }

    & $python $contract verify --toolchain-root $toolchain --diagnostics-dir $diagnostics --output-dir (Join-Path $diagnostics "verification")
    if ($LASTEXITCODE -ne 0) {
        throw "micro-Clang PE/hermeticity verification failed"
    }
} finally {
    foreach ($key in $environmentKeys) {
        [Environment]::SetEnvironmentVariable($key, [string]$savedEnvironment[$key], "Process")
    }
    if ($normalBackendMoved) {
        if (Test-Path -LiteralPath $normalBackend) {
            Remove-Item -Recurse -Force $normalBackend
        }
        Move-Item -LiteralPath $disabledBackend -Destination $normalBackend
    }
}

Write-Host "micro-Clang Phase-1 private qualification passed"
