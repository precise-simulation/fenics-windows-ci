Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $env:LIBRARY_PREFIX) { throw "LIBRARY_PREFIX is not set" }

$root = Join-Path $env:LIBRARY_PREFIX "fenics-jit"
$include = Join-Path $root "include"
if (-not (Test-Path -LiteralPath $include -PathType Container)) {
    throw "LLVM-MinGW root include directory missing: $include"
}

# Run #181 requalified Stages F-H and measured the complete uiautomation*
# family as unobserved across all 27 Phase 5 compile dependency closures.
# Keep this next family as a separate post-minimizer experiment so rollback is
# isolated while the broader 16.87 MiB Windows Runtime family remains intact.
$matches = @(
    Get-ChildItem -LiteralPath $include -File |
        Where-Object { $_.Name -like "uiautomation*" } |
        Sort-Object Name
)
if ($matches.Count -eq 0) {
    throw "Stage I found no uiautomation* headers; upstream layout may have changed"
}

$removed = foreach ($file in $matches) {
    [pscustomobject]@{
        path = $file.FullName.Substring($root.Length).TrimStart("\").Replace("\", "/")
        bytes = [int64]$file.Length
    }
}
$removedBytes = ($removed | Measure-Object bytes -Sum).Sum
if ($null -eq $removedBytes) { $removedBytes = 0 }
$removedBytes = [int64]$removedBytes

foreach ($file in $matches) {
    Remove-Item -LiteralPath $file.FullName -Force
}

$remaining = @(
    Get-ChildItem -LiteralPath $include -File |
        Where-Object { $_.Name -like "uiautomation*" }
)
if ($remaining.Count -ne 0) {
    throw "Stage I uiautomation* headers remain: $($remaining.Name -join ', ')"
}

$stageHReport = Join-Path $root "minimization-stage-h.json"
if (-not (Test-Path -LiteralPath $stageHReport -PathType Leaf)) {
    throw "Stage H minimization report missing before Stage I: $stageHReport"
}

$report = [ordered]@{
    stage = "stage-i"
    parent_stage = "stage-h"
    evidence_run = 181
    evidence_compile_trace_count = 27
    family = "ui_automation"
    patterns = @("include/uiautomation*")
    removed_file_count = $removed.Count
    removed_bytes = $removedBytes
    removed_mib = [math]::Round($removedBytes / 1MB, 3)
    removed = $removed
}
$reportPath = Join-Path $root "minimization-stage-i.json"
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

$metadataPath = Join-Path $root "metadata.json"
if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
    throw "LLVM-MinGW metadata missing before Stage I: $metadataPath"
}
$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
if ([string]$metadata.minimization_stage -ne "stage-h") {
    throw "Stage I expected Stage H metadata, got: $($metadata.minimization_stage)"
}
$metadata.minimization_stage = "stage-i"
$metadata.minimization_report = "minimization-stage-i.json"
$metadata | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $metadataPath -Encoding UTF8

# Stage H already generated these files. Recreate them after Stage I so the
# package manifest and size gate describe the actual post-pruning payload.
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
        throw "Phase 6 size gate failed after Stage I: staged payload $payloadBytes bytes exceeds 50% ceiling $phase6GateBytes bytes"
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

Write-Host "LLVM-MinGW minimization stage-i"
Write-Host "  Stage I removed files: $($removed.Count)"
Write-Host "  Stage I removed MiB: $([math]::Round($removedBytes / 1MB, 2))"
Write-Host "  payload MiB after Stage I: $([math]::Round($payloadBytes / 1MB, 2))"
