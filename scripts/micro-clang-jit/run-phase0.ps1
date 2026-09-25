param(
    [Parameter(Mandatory = $true)][string]$PythonPrefix,
    [string]$WorkDir = "micro-clang-phase0-work",
    [string]$OutputDir = "micro-clang-phase0-evidence"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$work = [IO.Path]::GetFullPath($WorkDir)
$output = [IO.Path]::GetFullPath($OutputDir)
$pythonPrefixPath = [IO.Path]::GetFullPath($PythonPrefix)
$python = Join-Path $pythonPrefixPath "python.exe"
$identityPath = Join-Path $PSScriptRoot "reference-identity.json"
$stageScript = Join-Path $repoRoot "recipes\fenics-jit-llvm-mingw\stage-toolchain.ps1"
$decompose = Join-Path $PSScriptRoot "phase0-decompose.py"

foreach ($path in @($python, $identityPath, $stageScript, $decompose)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required Phase-0 input is missing: $path"
    }
}

Remove-Item -Recurse -Force $work, $output -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $work, $output | Out-Null

$identity = Get-Content -LiteralPath $identityPath -Raw | ConvertFrom-Json
$archiveName = [string]$identity.stage_aw.archive
$expectedArchiveSha = [string]$identity.stage_aw.archive_sha256
$release = [string]$identity.stage_aw.llvm_mingw_release
$archiveUrl = "https://github.com/mstorsjo/llvm-mingw/releases/download/$release/$archiveName"
$sourceDir = Join-Path $work "source"
$libraryPrefix = Join-Path $work "reference-library"
New-Item -ItemType Directory -Force $sourceDir, $libraryPrefix | Out-Null
$archive = Join-Path $sourceDir $archiveName

Write-Host "Downloading immutable Stage-AW archive $archiveName"
Invoke-WebRequest -Uri $archiveUrl -OutFile $archive
$actualArchiveSha = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualArchiveSha -ne $expectedArchiveSha) {
    throw "Stage-AW archive SHA-256 mismatch: expected $expectedArchiveSha, got $actualArchiveSha"
}

$oldSrcDir = $env:SRC_DIR
$oldLibraryPrefix = $env:LIBRARY_PREFIX
$oldPrefix = $env:PREFIX
$oldBuildPrefix = $env:BUILD_PREFIX
try {
    $env:SRC_DIR = $sourceDir
    $env:LIBRARY_PREFIX = $libraryPrefix
    $env:PREFIX = $pythonPrefixPath
    $env:BUILD_PREFIX = $pythonPrefixPath
    & $stageScript
    if ($LASTEXITCODE -ne 0) {
        throw "Stage-AW recipe staging failed"
    }
} finally {
    $env:SRC_DIR = $oldSrcDir
    $env:LIBRARY_PREFIX = $oldLibraryPrefix
    $env:PREFIX = $oldPrefix
    $env:BUILD_PREFIX = $oldBuildPrefix
}

$referenceRoot = Join-Path $libraryPrefix "fenics-jit"
$clang = Join-Path $referenceRoot "bin\x86_64-w64-mingw32-clang.exe"
$lld = Join-Path $referenceRoot "bin\ld.lld.exe"
$metadataPath = Join-Path $referenceRoot "metadata.json"
foreach ($path in @($referenceRoot, $clang, $lld, $metadataPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Phase-0 staged reference input is missing: $path"
    }
}

$driverDir = Join-Path $output "driver"
New-Item -ItemType Directory -Force $driverDir | Out-Null
$emptySource = Join-Path $driverDir "empty.c"
$emptyObject = Join-Path $driverDir "empty.obj"
"" | Set-Content -LiteralPath $emptySource -Encoding Ascii

$clangVersion = (& $clang --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Stage-AW clang --version failed" }
$target = (& $clang -dumpmachine 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Stage-AW clang -dumpmachine failed" }
$resourceDir = (& $clang --print-resource-dir 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Stage-AW clang --print-resource-dir failed" }
$lldVersion = (& $lld --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Stage-AW ld.lld --version failed" }

$driverDefaults = (& $clang -### -O2 -std=c17 -c $emptySource -o $emptyObject 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Stage-AW clang -### probe failed" }
$driverDefaults | Set-Content -LiteralPath (Join-Path $driverDir "clang-driver-defaults.txt") -Encoding UTF8

$macros = (& $clang -dM -E -x c $emptySource 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Stage-AW preprocessor macro probe failed" }
$macros | Set-Content -LiteralPath (Join-Path $driverDir "clang-predefined-macros.txt") -Encoding UTF8

$abiSource = Join-Path $driverDir "abi-sentinel.c"
$abiExe = Join-Path $driverDir "abi-sentinel.exe"
@'
#include <stddef.h>
#include <stdio.h>

struct bitfield_probe {
    char prefix;
    unsigned int a : 4;
    unsigned int b : 4;
    unsigned short tail;
};

int main(void) {
    printf(
        "{\"sizeof_long_double\":%zu,"
        "\"alignof_long_double\":%zu,"
        "\"sizeof_bitfield_probe\":%zu,"
        "\"alignof_bitfield_probe\":%zu,"
        "\"offsetof_bitfield_tail\":%zu}\n",
        sizeof(long double),
        _Alignof(long double),
        sizeof(struct bitfield_probe),
        _Alignof(struct bitfield_probe),
        offsetof(struct bitfield_probe, tail)
    );
    return 0;
}
'@ | Set-Content -LiteralPath $abiSource -Encoding Ascii

& $clang -std=c17 -O2 $abiSource -o $abiExe
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $abiExe)) {
    throw "Stage-AW ABI sentinel compile failed"
}
$abiText = (& $abiExe 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Stage-AW ABI sentinel execution failed" }
$abi = $abiText | ConvertFrom-Json

$targetCpu = $null
if ($driverDefaults -match '"-target-cpu"\s+"([^"]+)"') {
    $targetCpu = $Matches[1]
}
$targetFeatures = @(
    [regex]::Matches($driverDefaults, '"-target-feature"\s+"([^"]+)"') |
        ForEach-Object { $_.Groups[1].Value }
)

$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
$driverEvidence = [ordered]@{
    schema = "fenics-jit-micro-clang-stage-aw-driver-v1"
    archive_sha256 = $actualArchiveSha
    clang_version = $clangVersion
    lld_version = $lldVersion
    target = $target
    resource_dir = $resourceDir
    target_cpu = $targetCpu
    target_features = $targetFeatures
    abi = $abi
    reference_metadata = $metadata
    raw_driver_defaults = "driver/clang-driver-defaults.txt"
    raw_predefined_macros = "driver/clang-predefined-macros.txt"
}
$driverEvidencePath = Join-Path $output "driver-evidence.json"
$driverEvidence | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $driverEvidencePath -Encoding UTF8

& $python $decompose --root $referenceRoot --identity $identityPath --output-dir $output --driver-evidence $driverEvidencePath
if ($LASTEXITCODE -ne 0) {
    throw "Stage-AW payload decomposition failed"
}

Copy-Item -LiteralPath $identityPath -Destination (Join-Path $output "reference-identity.json") -Force

Write-Host "micro-Clang Phase 0 reference capture complete"
Write-Host "  reference root: $referenceRoot"
Write-Host "  evidence: $output"
Write-Host "  target: $target"
Write-Host "  long double: sizeof=$($abi.sizeof_long_double), align=$($abi.alignof_long_double)"
