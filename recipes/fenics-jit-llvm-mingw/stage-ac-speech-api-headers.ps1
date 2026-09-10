Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $env:LIBRARY_PREFIX) { throw "LIBRARY_PREFIX is not set" }

$root = Join-Path $env:LIBRARY_PREFIX "fenics-jit"
$include = Join-Path $root "include"
if (-not (Test-Path -LiteralPath $include -PathType Container)) {
    throw "LLVM-MinGW root include directory missing: $include"
}

# Run #206 requalified Stage AB across all 27 Phase 5 compile dependency
# closures. The complete root sapi* Speech API family below was unobserved in
# every trace: 7 files / 2.634 MiB. Use exact names and bytes so an upstream
# layout change cannot silently broaden this pruning step.
$names = @(
    "sapi.h",
    "sapi51.h",
    "sapi51.idl",
    "sapi53.h",
    "sapi53.idl",
    "sapi54.h",
    "sapi54.idl"
)
$matches = @(
    foreach ($name in $names) {
        $path = Join-Path $include $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Stage AC expected run #206 candidate header missing: $name"
        }
        Get-Item -LiteralPath $path
    }
)
if ($matches.Count -ne 7) {
    throw "Stage AC expected 7 Speech API headers from run #206 evidence, found $($matches.Count)"
}

$expectedBytes = [int64]2762072
$actualBytes = [int64](($matches | Measure-Object Length -Sum).Sum)
if ($actualBytes -ne $expectedBytes) {
    throw "Stage AC expected $expectedBytes bytes from run #206 evidence, found $actualBytes; refusing changed candidate set"
}

# Preserve headers directly observed by the Phase 5 dependency closures and a
# small set of explicit Windows/MinGW safety headers.
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
        throw "Stage AC safety header missing before pruning: $name"
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
        throw "Stage AC Speech API header remains after pruning: $name"
    }
}
foreach ($name in $requiredHeaders) {
    if (-not (Test-Path -LiteralPath (Join-Path $include $name) -PathType Leaf)) {
        throw "Stage AC safety header missing after pruning: $name"
    }
}

$stageABReport = Join-Path $root "minimization-stage-ab.json"
if (-not (Test-Path -LiteralPath $stageABReport -PathType Leaf)) {
    throw "Stage AB minimization report missing before Stage AC: $stageABReport"
}

$report = [ordered]@{
    stage = "stage-ac"
    parent_stage = "stage-ab"
    previous_header_stage = "stage-w"
    evidence_run = 206
    evidence_compile_trace_count = 27
    family = "speech_api_root_headers"
    names = $names | ForEach-Object { "include/$_" }
    removed_file_count = $removed.Count
    removed_bytes = $actualBytes
    removed_mib = [math]::Round($actualBytes / 1MB, 3)
    removed = $removed
}
$reportPath = Join-Path $root "minimization-stage-ac.json"
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

$metadataPath = Join-Path $root "metadata.json"
if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
    throw "LLVM-MinGW metadata missing before Stage AC: $metadataPath"
}
$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
if ([string]$metadata.minimization_stage -ne "stage-w") {
    throw "Stage AC expected Stage W header metadata, got: $($metadata.minimization_stage)"
}
if ([string]$metadata.library_minimization_stage -ne "stage-ab") {
    throw "Stage AC expected Stage AB library metadata, got: $($metadata.library_minimization_stage)"
}
$metadata.minimization_stage = "stage-ac"
$metadata.minimization_report = "minimization-stage-ac.json"
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
        throw "Phase 6 size gate failed after Stage AC: staged payload $payloadBytes bytes exceeds 50% ceiling $phase6GateBytes bytes"
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

Write-Host "LLVM-MinGW minimization stage-ac"
Write-Host "  Stage AC removed files: $($removed.Count)"
Write-Host "  Stage AC removed MiB: $([math]::Round($actualBytes / 1MB, 2))"
Write-Host "  payload MiB after Stage AC: $([math]::Round($payloadBytes / 1MB, 2))"
