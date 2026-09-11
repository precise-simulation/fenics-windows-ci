Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $env:LIBRARY_PREFIX) { throw "LIBRARY_PREFIX is not set" }

$root = Join-Path $env:LIBRARY_PREFIX "fenics-jit"
$include = Join-Path $root "include"
$gdiplusInclude = Join-Path $include "gdiplus"
if (-not (Test-Path -LiteralPath $gdiplusInclude -PathType Container)) {
    throw "Stage AN GDI+ include directory missing: $gdiplusInclude"
}

# Run #219 requalified Stage AM across all 27 Phase 5 compile dependency
# closures. The complete retained GDI+ header family below was unobserved in
# every trace: 27 files / 0.323 MiB. Use exact names and bytes so an upstream
# layout change cannot silently broaden pruning.
$rootNames = @(
    "gdiplus.h"
)
$directoryNames = @(
    "gdiplus.h",
    "gdiplusbase.h",
    "gdiplusbrush.h",
    "gdipluscolor.h",
    "gdipluscolormatrix.h",
    "gdipluseffects.h",
    "gdiplusenums.h",
    "gdiplusflat.h",
    "gdiplusgpstubs.h",
    "gdiplusgraphics.h",
    "gdiplusheaders.h",
    "gdiplusimageattributes.h",
    "gdiplusimagecodec.h",
    "gdiplusimaging.h",
    "gdiplusimpl.h",
    "gdiplusinit.h",
    "gdipluslinecaps.h",
    "gdiplusmatrix.h",
    "gdiplusmem.h",
    "gdiplusmetafile.h",
    "gdiplusmetaheader.h",
    "gdipluspath.h",
    "gdipluspen.h",
    "gdipluspixelformats.h",
    "gdiplusstringformat.h",
    "gdiplustypes.h"
)

$entries = @(Get-ChildItem -LiteralPath $gdiplusInclude -Force)
if ($entries.Count -ne $directoryNames.Count) {
    throw "Stage AN expected exactly $($directoryNames.Count) GDI+ directory entries from run #219 evidence, found $($entries.Count)"
}
$actualNames = @($entries | ForEach-Object { $_.Name } | Sort-Object)
$expectedNames = @($directoryNames | Sort-Object)
$nameDiff = @(Compare-Object -ReferenceObject $expectedNames -DifferenceObject $actualNames)
if ($nameDiff.Count -ne 0) {
    $nameDiff | Format-Table | Out-String | Write-Host
    throw "Stage AN GDI+ directory contents differ from the exact run #219 candidate set"
}

$matches = @()
foreach ($name in $rootNames) {
    $path = Join-Path $include $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Stage AN expected run #219 candidate header missing: $name"
    }
    $matches += Get-Item -LiteralPath $path
}
foreach ($name in $directoryNames) {
    $path = Join-Path $gdiplusInclude $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Stage AN expected run #219 candidate header missing: gdiplus/$name"
    }
    $matches += Get-Item -LiteralPath $path
}
if ($matches.Count -ne 27) {
    throw "Stage AN expected 27 GDI+ files from run #219 evidence, found $($matches.Count)"
}

$expectedBytes = [int64]339141
$actualBytes = [int64](($matches | Measure-Object Length -Sum).Sum)
if ($actualBytes -ne $expectedBytes) {
    throw "Stage AN expected $expectedBytes bytes from run #219 evidence, found $actualBytes; refusing changed candidate set"
}

$requiredHeaders = @(
    "_mingw.h",
    "io.h",
    "stddef.h",
    "stdint.h",
    "stdio.h",
    "stdlib.h",
    "string.h",
    "windows.h",
    "winnt.h"
)
foreach ($name in $requiredHeaders) {
    if (-not (Test-Path -LiteralPath (Join-Path $include $name) -PathType Leaf)) {
        throw "Stage AN safety header missing before pruning: $name"
    }
}

$removed = foreach ($file in $matches) {
    [pscustomobject]@{
        path = $file.FullName.Substring($root.Length).TrimStart("\").Replace("\", "/")
        bytes = [int64]$file.Length
    }
}
foreach ($file in $matches) {
    Remove-Item -LiteralPath $file.FullName -Force
}

$remaining = @(Get-ChildItem -LiteralPath $gdiplusInclude -Force)
if ($remaining.Count -ne 0) {
    $remaining.FullName | Write-Host
    throw "Stage AN GDI+ include directory is not empty after exact candidate removal"
}
Remove-Item -LiteralPath $gdiplusInclude -Force
if (Test-Path -LiteralPath $gdiplusInclude) {
    throw "Stage AN GDI+ include directory remains after pruning"
}
foreach ($name in $rootNames) {
    if (Test-Path -LiteralPath (Join-Path $include $name)) {
        throw "Stage AN GDI+ root header remains after pruning: $name"
    }
}
foreach ($name in $requiredHeaders) {
    if (-not (Test-Path -LiteralPath (Join-Path $include $name) -PathType Leaf)) {
        throw "Stage AN safety header missing after pruning: $name"
    }
}

$stageAMReport = Join-Path $root "minimization-stage-am.json"
if (-not (Test-Path -LiteralPath $stageAMReport -PathType Leaf)) {
    throw "Stage AM minimization report missing before Stage AN: $stageAMReport"
}

$relativeNames = @("include/gdiplus.h") + @($directoryNames | ForEach-Object { "include/gdiplus/$_" })
$report = [ordered]@{
    stage = "stage-an"
    parent_stage = "stage-am"
    evidence_run = 219
    evidence_compile_trace_count = 27
    family = "gdiplus_headers"
    names = $relativeNames
    removed_file_count = $removed.Count
    removed_bytes = $actualBytes
    removed_mib = [math]::Round($actualBytes / 1MB, 3)
    removed = $removed
}
$reportPath = Join-Path $root "minimization-stage-an.json"
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

$metadataPath = Join-Path $root "metadata.json"
if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
    throw "LLVM-MinGW metadata missing before Stage AN: $metadataPath"
}
$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
if ([string]$metadata.minimization_stage -ne "stage-am") {
    throw "Stage AN expected Stage AM header metadata, got: $($metadata.minimization_stage)"
}
if ([string]$metadata.library_minimization_stage -ne "stage-ab") {
    throw "Stage AN expected Stage AB library metadata, got: $($metadata.library_minimization_stage)"
}
$metadata.minimization_stage = "stage-an"
$metadata.minimization_report = "minimization-stage-an.json"
$metadata | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $metadataPath -Encoding UTF8

$manifestPath = Join-Path $root "manifest.csv"
$sizePath = Join-Path $root "size.txt"
Remove-Item -LiteralPath $manifestPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $sizePath -Force -ErrorAction SilentlyContinue

$payloadFiles = @(Get-ChildItem -LiteralPath $root -Recurse -File | Sort-Object FullName)
$payloadBytes = ($payloadFiles | Measure-Object Length -Sum).Sum
if ($null -eq $payloadBytes) { $payloadBytes = 0 }
$payloadBytes = [int64]$payloadBytes

$phase6GateBytes = $null
$phase6GateStatus = "not-evaluated"
if ($env:PHASE6_VS2022_JIT_GATE_BYTES) {
    try {
        $phase6GateBytes = [int64]$env:PHASE6_VS2022_JIT_GATE_BYTES
    } catch {
        throw "Invalid PHASE6_VS2022_JIT_GATE_BYTES: $($env:PHASE6_VS2022_JIT_GATE_BYTES)"
    }
    if ($phase6GateBytes -le 0) {
        throw "PHASE6_VS2022_JIT_GATE_BYTES must be positive"
    }
    if ($payloadBytes -gt $phase6GateBytes) {
        throw "Phase 6 size gate failed after Stage AN: staged payload $payloadBytes bytes exceeds 50% ceiling $phase6GateBytes bytes"
    }
    $phase6GateStatus = "passed"
}

$manifest = foreach ($file in $payloadFiles) {
    $relative = $file.FullName.Substring($root.Length).TrimStart("\")
    [pscustomobject]@{
        path = $relative.Replace("\", "/")
        bytes = $file.Length
        sha256 = (Get-FileHash $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$manifest | ConvertTo-Csv -NoTypeInformation | Set-Content -LiteralPath $manifestPath -Encoding UTF8

$sizeLines = @(
    "payload_file_count=$($payloadFiles.Count)"
    "payload_bytes=$payloadBytes"
    "payload_mib=$([math]::Round($payloadBytes / 1MB, 2))"
    "phase6_size_gate_status=$phase6GateStatus"
)
if ($null -ne $phase6GateBytes) {
    $sizeLines += "phase6_size_gate_bytes=$phase6GateBytes"
    $sizeLines += "phase6_size_gate_mib=$([math]::Round($phase6GateBytes / 1MB, 2))"
}
$sizeLines | Set-Content -LiteralPath $sizePath -Encoding Ascii

Write-Host "LLVM-MinGW minimization stage-an"
Write-Host "  Stage AN removed files: $($removed.Count)"
Write-Host "  Stage AN removed MiB: $([math]::Round($actualBytes / 1MB, 2))"
Write-Host "  payload MiB after Stage AN: $([math]::Round($payloadBytes / 1MB, 2))"
