Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $env:LIBRARY_PREFIX) { throw "LIBRARY_PREFIX is not set" }

$root = Join-Path $env:LIBRARY_PREFIX "fenics-jit"
$include = Join-Path $root "include"
if (-not (Test-Path -LiteralPath $include -PathType Container)) {
    throw "LLVM-MinGW root include directory missing: $include"
}

# Run #197 requalified Stage V and measured every windows.management* root
# header as unobserved across all 27 Phase 5 compile dependency closures. Prune
# only this 0.187 MiB Windows Runtime subfamily.
$matches = @(
    Get-ChildItem -LiteralPath $include -File |
        Where-Object { $_.Name -like "windows.management*" } |
        Sort-Object Name
)
if ($matches.Count -eq 0) {
    throw "Stage W found no windows.management* headers; upstream layout may have changed"
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
        Where-Object { $_.Name -like "windows.management*" }
)
if ($remaining.Count -ne 0) {
    throw "Stage W windows.management* headers remain: $($remaining.Name -join ', ')"
}

$stageVReport = Join-Path $root "minimization-stage-v.json"
if (-not (Test-Path -LiteralPath $stageVReport -PathType Leaf)) {
    throw "Stage V minimization report missing before Stage W: $stageVReport"
}

$report = [ordered]@{
    stage = "stage-w"
    parent_stage = "stage-v"
    evidence_run = 197
    evidence_compile_trace_count = 27
    family = "windows_runtime_management"
    patterns = @("include/windows.management*")
    removed_file_count = $removed.Count
    removed_bytes = $removedBytes
    removed_mib = [math]::Round($removedBytes / 1MB, 3)
    removed = $removed
}
$reportPath = Join-Path $root "minimization-stage-w.json"
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

$metadataPath = Join-Path $root "metadata.json"
if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
    throw "LLVM-MinGW metadata missing before Stage W: $metadataPath"
}
$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
if ([string]$metadata.minimization_stage -ne "stage-v") {
    throw "Stage W expected Stage V metadata, got: $($metadata.minimization_stage)"
}
$metadata.minimization_stage = "stage-w"
$metadata.minimization_report = "minimization-stage-w.json"
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
        throw "Phase 6 size gate failed after Stage W: staged payload $payloadBytes bytes exceeds 50% ceiling $phase6GateBytes bytes"
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

Write-Host "LLVM-MinGW minimization stage-w"
Write-Host "  Stage W removed files: $($removed.Count)"
Write-Host "  Stage W removed MiB: $([math]::Round($removedBytes / 1MB, 2))"
Write-Host "  payload MiB after Stage W: $([math]::Round($payloadBytes / 1MB, 2))"
