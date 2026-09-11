Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $env:LIBRARY_PREFIX) { throw "LIBRARY_PREFIX is not set" }

$root = Join-Path $env:LIBRARY_PREFIX "fenics-jit"
$targetLib = Join-Path $root "x86_64-w64-mingw32\lib"
if (-not (Test-Path -LiteralPath $targetLib -PathType Container)) {
    throw "LLVM-MinGW target library directory missing: $targetLib"
}

# Run #202 requalified Stage Y across all 27 Phase 5 link traces. The exact
# Run #204 requalified Stage Z across all 27 Phase 5 link traces. The remaining
# Nano Server/headless OneCore archives below were unobserved in every trace:
# 2 files / 4.585 MiB. Keep generic desktop Win32, MinGW/UCRT startup,
# and runtime archives intact.
$names = @(
    "libnanosrv.a",
    "libwindowscoreheadless_apiset.a"
)
$matches = @(
    foreach ($name in $names) {
        $path = Join-Path $targetLib $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Stage AA expected run #204 candidate archive missing: $name"
        }
        Get-Item -LiteralPath $path
    }
)
if ($matches.Count -ne 2) {
    throw "Stage AA expected 2 Nano Server/headless archives from run #204 evidence, found $($matches.Count)"
}

$expectedBytes = [int64]4807906
$actualBytes = [int64](($matches | Measure-Object Length -Sum).Sum)
if ($actualBytes -ne $expectedBytes) {
    throw "Stage AA expected $expectedBytes bytes from run #204 evidence, found $actualBytes; refusing changed candidate set"
}

$requiredRuntime = @(
    "libmingw32.a",
    "libmingwex.a",
    "libucrt.a",
    "libkernel32.a",
    "libunwind.a",
    "libmsvcrt.a",
    "libmsvcrt-os.a"
)
foreach ($name in $requiredRuntime) {
    if (-not (Test-Path -LiteralPath (Join-Path $targetLib $name) -PathType Leaf)) {
        throw "Stage AA runtime safety archive missing before pruning: $name"
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
    if (Test-Path -LiteralPath (Join-Path $targetLib $name)) {
        throw "Stage AA Nano Server/headless archive remains after pruning: $name"
    }
}
foreach ($name in $requiredRuntime) {
    if (-not (Test-Path -LiteralPath (Join-Path $targetLib $name) -PathType Leaf)) {
        throw "Stage AA runtime safety archive missing after pruning: $name"
    }
}

$stageYReport = Join-Path $root "minimization-stage-z.json"
if (-not (Test-Path -LiteralPath $stageYReport -PathType Leaf)) {
    throw "Stage Z minimization report missing before Stage AA: $stageYReport"
}

$report = [ordered]@{
    stage = "stage-aa"
    parent_stage = "stage-z"
    evidence_run = 204
    evidence_link_trace_count = 27
    family = "nanosrv_windowscoreheadless_target_import_libraries"
    names = $names
    removed_file_count = $removed.Count
    removed_bytes = $actualBytes
    removed_mib = [math]::Round($actualBytes / 1MB, 3)
    removed = $removed
}
$reportPath = Join-Path $root "minimization-stage-aa.json"
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

$metadataPath = Join-Path $root "metadata.json"
if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
    throw "LLVM-MinGW metadata missing before Stage AA: $metadataPath"
}
$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
if ([string]$metadata.library_minimization_stage -ne "stage-z") {
    throw "Stage AA expected Stage Z library metadata, got: $($metadata.library_minimization_stage)"
}
$metadata | Add-Member -NotePropertyName library_minimization_stage -NotePropertyValue "stage-aa" -Force
$metadata | Add-Member -NotePropertyName library_minimization_report -NotePropertyValue "minimization-stage-aa.json" -Force
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
        throw "Phase 6 size gate failed after Stage AA: staged payload $payloadBytes bytes exceeds 50% ceiling $phase6GateBytes bytes"
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

Write-Host "LLVM-MinGW minimization stage-aa"
Write-Host "  Stage AA removed files: $($removed.Count)"
Write-Host "  Stage AA removed MiB: $([math]::Round($actualBytes / 1MB, 2))"
Write-Host "  payload MiB after Stage AA: $([math]::Round($payloadBytes / 1MB, 2))"
