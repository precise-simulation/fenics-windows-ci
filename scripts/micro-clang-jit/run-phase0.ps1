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
$decompose = Join-Path $PSScriptRoot "phase0-decompose.py"

foreach ($path in @($python, $identityPath, $decompose)) {
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
$referenceCommit = [string]$identity.stage_aw.repository_reference.qualification_head_commit
$expectedStagedMiB = [double]$identity.stage_aw.staged_payload_mib
$archiveUrl = "https://github.com/mstorsjo/llvm-mingw/releases/download/$release/$archiveName"

if (-not $referenceCommit) {
    throw "Stage-AW repository recipe commit is not pinned"
}

$sourceDir = Join-Path $work "source"
$libraryPrefix = Join-Path $work "reference-library"
$referenceCheckout = Join-Path $work "stage-aw-repository"
New-Item -ItemType Directory -Force $sourceDir, $libraryPrefix | Out-Null
$archive = Join-Path $sourceDir $archiveName

Write-Host "Downloading immutable Stage-AW archive $archiveName"
Invoke-WebRequest -Uri $archiveUrl -OutFile $archive
$actualArchiveSha = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualArchiveSha -ne $expectedArchiveSha) {
    throw "Stage-AW archive SHA-256 mismatch: expected $expectedArchiveSha, got $actualArchiveSha"
}

Write-Host "Checking out immutable Stage-AW recipe revision $referenceCommit"
& git -C $repoRoot fetch --no-tags --depth=1 origin $referenceCommit
if ($LASTEXITCODE -ne 0) {
    throw "Could not fetch immutable Stage-AW recipe revision $referenceCommit"
}
& git -C $repoRoot worktree add --detach $referenceCheckout $referenceCommit
if ($LASTEXITCODE -ne 0) {
    throw "Could not create immutable Stage-AW recipe worktree"
}

$referenceRecipeDir = Join-Path $referenceCheckout "recipes\fenics-jit-llvm-mingw"
$stageScripts = @(
    "stage-toolchain.ps1",
    "stage-i-ui-automation.ps1",
    "stage-j-windows-ui.ps1",
    "stage-k-windows-devices.ps1",
    "stage-l-windows-applicationmodel.ps1",
    "stage-m-windows-media.ps1",
    "stage-n-windows-storage.ps1",
    "stage-o-windows-graphics.ps1",
    "stage-p-windows-gaming.ps1",
    "stage-q-windows-foundation.ps1",
    "stage-r-windows-security.ps1",
    "stage-s-windows-networking.ps1",
    "stage-t-windows-data.ps1",
    "stage-u-windows-system.ps1",
    "stage-v-windows-globalization.ps1",
    "stage-w-windows-management.ps1",
    "stage-x-directx-libraries.ps1",
    "stage-y-legacy-msvc-libraries.ps1",
    "stage-z-onecore-uwp-libraries.ps1",
    "stage-aa-nanosrv-headless-libraries.ps1",
    "stage-ab-optional-windows-api-libraries.ps1",
    "stage-ac-speech-api-headers.ps1",
    "stage-ad-opengl-headers.ps1",
    "stage-ae-ddk-headers.ps1",
    "stage-af-msxml-headers.ps1",
    "stage-ag-media-foundation-headers.ps1",
    "stage-ah-windows-media-sdk-headers.ps1",
    "stage-ai-windows-media-player-headers.ps1",
    "stage-aj-windows-perception-headers.ps1",
    "stage-ak-directshow-strmif-headers.ps1",
    "stage-al-broadcast-tuner-headers.ps1",
    "stage-am-xps-headers.ps1",
    "stage-an-gdiplus-headers.ps1",
    "stage-ao-directshow-qedit-headers.ps1",
    "stage-ap-directshow-amstream-headers.ps1",
    "stage-aq-enhanced-video-renderer-headers.ps1",
    "stage-ar-task-scheduler-headers.ps1",
    "stage-as-windows-update-agent-headers.ps1",
    "stage-at-directshow-dvd-headers.ps1",
    "stage-au-directshow-vmr9-headers.ps1",
    "stage-av-directshow-amvideo-headers.ps1",
    "stage-aw-bda-interface-headers.ps1"
)
foreach ($name in $stageScripts) {
    $path = Join-Path $referenceRecipeDir $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Pinned Stage-AW recipe script is missing: $path"
    }
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

    foreach ($name in $stageScripts) {
        $path = Join-Path $referenceRecipeDir $name
        Write-Host "Running immutable Stage-AW recipe step: $name"
        & $path
        if ($LASTEXITCODE -ne 0) {
            throw "Immutable Stage-AW recipe step failed: $name"
        }
    }
} finally {
    $env:SRC_DIR = $oldSrcDir
    $env:LIBRARY_PREFIX = $oldLibraryPrefix
    $env:PREFIX = $oldPrefix
    $env:BUILD_PREFIX = $oldBuildPrefix
    & git -C $repoRoot worktree remove --force $referenceCheckout 2>$null
}

$referenceRoot = Join-Path $libraryPrefix "fenics-jit"
$clang = Join-Path $referenceRoot "bin\x86_64-w64-mingw32-clang.exe"
$lld = Join-Path $referenceRoot "bin\ld.lld.exe"
$metadataPath = Join-Path $referenceRoot "metadata.json"
$stageAWReport = Join-Path $referenceRoot "minimization-stage-aw.json"
$sizePath = Join-Path $referenceRoot "size.txt"
foreach ($path in @($referenceRoot, $clang, $lld, $metadataPath, $stageAWReport, $sizePath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Phase-0 immutable reference input is missing: $path"
    }
}

$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
if ([string]$metadata.minimization_stage -ne "stage-aw") {
    throw "Immutable reference did not reach Stage AW: $($metadata.minimization_stage)"
}
if ([string]$metadata.library_minimization_stage -ne "stage-ab") {
    throw "Immutable Stage-AW library minimization mismatch: $($metadata.library_minimization_stage)"
}

$payloadFiles = @(Get-ChildItem -LiteralPath $referenceRoot -Recurse -File)
$payloadBytes = [int64](($payloadFiles | Measure-Object Length -Sum).Sum)
$payloadMiB = $payloadBytes / 1MB
if ([math]::Abs($payloadMiB - $expectedStagedMiB) -gt 0.25) {
    throw "Immutable Stage-AW staged size mismatch: expected approximately $expectedStagedMiB MiB, got $([math]::Round($payloadMiB, 3)) MiB"
}
Write-Host "Immutable Stage-AW staged payload verified: $([math]::Round($payloadMiB, 3)) MiB"

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

$driverEvidence = [ordered]@{
    schema = "fenics-jit-micro-clang-stage-aw-driver-v1"
    archive_sha256 = $actualArchiveSha
    repository_recipe_commit = $referenceCommit
    staged_payload_bytes = $payloadBytes
    staged_payload_mib = [math]::Round($payloadMiB, 4)
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

Write-Host "micro-Clang Phase 0 immutable reference capture complete"
Write-Host "  recipe commit: $referenceCommit"
Write-Host "  reference root: $referenceRoot"
Write-Host "  staged payload MiB: $([math]::Round($payloadMiB, 3))"
Write-Host "  evidence: $output"
Write-Host "  target: $target"
Write-Host "  long double: sizeof=$($abi.sizeof_long_double), align=$($abi.alignof_long_double)"
