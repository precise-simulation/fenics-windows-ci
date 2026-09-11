Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $env:LIBRARY_PREFIX) { throw "LIBRARY_PREFIX is not set" }

$root = Join-Path $env:LIBRARY_PREFIX "fenics-jit"
$include = Join-Path $root "include"

# Run #216 requalified Stage AJ across all 27 Phase 5 compile dependency
# closures. The retained DirectShow strmif root header/IDL pair below was
# unobserved in every trace: 2 files / 1.096 MiB. Use exact names and bytes so
# an upstream layout change cannot silently broaden this pruning step.
$names = @(
    "strmif.h",
    "strmif.idl"
)

$matches = @(
    foreach ($name in $names) {
        $path = Join-Path $include $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Stage AK expected run #216 candidate header missing: $name"
        }
        Get-Item -LiteralPath $path
    }
)
if ($matches.Count -ne 2) {
    throw "Stage AK expected 2 DirectShow strmif files from run #216 evidence, found $($matches.Count)"
}

$expectedBytes = [int64]1149498
$actualBytes = [int64](($matches | Measure-Object Length -Sum).Sum)
if ($actualBytes -ne $expectedBytes) {
    throw "Stage AK expected $expectedBytes bytes from run #216 evidence, found $actualBytes; refusing changed candidate set"
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
        throw "Stage AK safety header missing before pruning: $name"
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

foreach ($name in $names) {
    if (Test-Path -LiteralPath (Join-Path $include $name)) {
        throw "Stage AK DirectShow strmif file remains after pruning: $name"
    }
}
foreach ($name in $requiredHeaders) {
    if (-not (Test-Path -LiteralPath (Join-Path $include $name) -PathType Leaf)) {
        throw "Stage AK safety header missing after pruning: $name"
    }
}

$stageAJReport = Join-Path $root "minimization-stage-aj.json"
if (-not (Test-Path -LiteralPath $stageAJReport -PathType Leaf)) {
    throw "Stage AJ minimization report missing before Stage AK: $stageAJReport"
}

$report = [ordered]@{
    stage = "stage-ak"
    parent_stage = "stage-aj"
    evidence_run = 216
    evidence_compile_trace_count = 27
    family = "directshow_strmif_root_headers"
    names = $names | ForEach-Object { "include/$_" }
    removed_file_count = $removed.Count
    removed_bytes = $actualBytes
    removed_mib = [math]::Round($actualBytes / 1MB, 3)
    removed = $removed
}
$reportPath = Join-Path $root "minimization-stage-ak.json"
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

$metadataPath = Join-Path $root "metadata.json"
if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
    throw "LLVM-MinGW metadata missing before Stage AK: $metadataPath"
}
$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
if ([string]$metadata.minimization_stage -ne "stage-aj") {
    throw "Stage AK expected Stage AJ header metadata, got: $($metadata.minimization_stage)"
}
if ([string]$metadata.library_minimization_stage -ne "stage-ab") {
    throw "Stage AK expected Stage AB library metadata, got: $($metadata.library_minimization_stage)"
}
$metadata.minimization_stage = "stage-ak"
$metadata.minimization_report = "minimization-stage-ak.json"
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
        throw "Phase 6 size gate failed after Stage AK: staged payload $payloadBytes bytes exceeds 50% ceiling $phase6GateBytes bytes"
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

Write-Host "LLVM-MinGW minimization stage-ak"
Write-Host "  Stage AK removed files: $($removed.Count)"
Write-Host "  Stage AK removed MiB: $([math]::Round($actualBytes / 1MB, 2))"
Write-Host "  payload MiB after Stage AK: $([math]::Round($payloadBytes / 1MB, 2))"
