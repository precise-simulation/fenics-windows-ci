param(
    [Parameter(Mandatory = $true)][string]$TinyCCRoot,
    [Parameter(Mandatory = $true)][string]$PythonPrefix,
    [string]$WorkDir = "tinycc phase2 work",
    [string]$DiagnosticsDir = "tinycc-phase2-diagnostics"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = [System.IO.Path]::GetFullPath($TinyCCRoot)
$prefix = [System.IO.Path]::GetFullPath($PythonPrefix)
$work = [System.IO.Path]::GetFullPath($WorkDir)
$diagnostics = [System.IO.Path]::GetFullPath($DiagnosticsDir)
$python = Join-Path $prefix "python.exe"
$tcc = Join-Path $root "tcc.exe"

foreach ($path in @($python, $tcc)) {
    if (-not (Test-Path $path)) { throw "required Phase-2 input missing: $path" }
}

Remove-Item -Recurse -Force $work, $diagnostics -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $work, $diagnostics | Out-Null

# Match the Phase-1 hermetic runtime boundary. The GitHub image contains
# VS2022/Windows SDK development tools, but runtime JIT activation must not.
$clearVars = @(
    "VSINSTALLDIR", "VCINSTALLDIR", "VCToolsInstallDir", "VCToolsRedistDir",
    "WindowsSdkDir", "WindowsSDKVersion", "WindowsSDKLibVersion", "UniversalCRTSdkDir",
    "UCRTVersion", "INCLUDE", "LIB", "LIBPATH", "CC", "CXX", "LD", "AR",
    "CFLAGS", "CPPFLAGS", "LDFLAGS", "DISTUTILS_USE_SDK", "MSSdk"
)
foreach ($name in $clearVars) {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}

$pathEntries = @(
    $root,
    $prefix,
    (Join-Path $prefix "DLLs"),
    (Join-Path $prefix "Library/bin"),
    (Join-Path $env:SystemRoot "System32"),
    $env:SystemRoot
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique
$env:PATH = $pathEntries -join [System.IO.Path]::PathSeparator
$env:PYTHONNOUSERSITE = "1"
$env:PIP_CONFIG_FILE = [System.IO.Path]::GetFullPath((Join-Path $work "no-pip-config.ini"))

& $python scripts/tinycc-jit/phase2-proof.py `
    --tinycc-root $root `
    --python-prefix $prefix `
    --work-dir $work `
    --diagnostics-dir $diagnostics
if ($LASTEXITCODE -ne 0) { throw "TinyCC Phase-2 adapter qualification failed" }

Get-Content (Join-Path $diagnostics "phase2-summary.json")
