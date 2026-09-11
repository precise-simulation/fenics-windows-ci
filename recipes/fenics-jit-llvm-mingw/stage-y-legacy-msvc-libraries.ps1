Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $env:LIBRARY_PREFIX) { throw "LIBRARY_PREFIX is not set" }

$root = Join-Path $env:LIBRARY_PREFIX "fenics-jit"
$targetLib = Join-Path $root "x86_64-w64-mingw32\lib"
if (-not (Test-Path -LiteralPath $targetLib -PathType Container)) {
    throw "LLVM-MinGW target library directory missing: $targetLib"
}

# Run #201 requalified Stage X across all 27 Phase 5 link traces. The versioned
# legacy MSVC import-library family below was unobserved in every trace:
# 13 files / 11.943 MiB. Deliberately exclude generic libmsvcrt.a and
# libmsvcrt-os.a as well as all MinGW/UCRT/startup libraries from this stage.
$patterns = @("libmsvcr[0-9]*.a", "libmsvcp[0-9]*.a")
$matches = @(
    Get-ChildItem -LiteralPath $targetLib -File |
        Where-Object {
            $name = $_.Name
            @($patterns | Where-Object { $name -like $_ }).Count -gt 0
        } |
        Sort-Object Name
)
if ($matches.Count -ne 13) {
    throw "Stage Y expected 13 versioned legacy MSVC archives from run #201 evidence, found $($matches.Count); refusing changed candidate set"
}

$expectedBytes = [int64]12523012
$actualBytes = [int64](($matches | Measure-Object Length -Sum).Sum)
if ($actualBytes -ne $expectedBytes) {
    throw "Stage Y expected $expectedBytes bytes from run #201 evidence, found $actualBytes; refusing changed candidate set"
}

$requiredRuntime = @("libmingw32.a", "libmingwex.a", "libucrt.a", "libkernel32.a", "libunwind.a", "libmsvcrt.a", "libmsvcrt-os.a")
foreach ($name in $requiredRuntime) {
    if (-not (Test-Path -LiteralPath (Join-Path $targetLib $name) -PathType Leaf)) {
        throw "Stage Y runtime safety archive missing before pruning: $name"
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

$remaining = @(
    Get-ChildItem -LiteralPath $targetLib -File |
        Where-Object {
            $name = $_.Name
            @($patterns | Where-Object { $name -like $_ }).Count -gt 0
        }
)
if ($remaining.Count -ne 0) {
    throw "Stage Y versioned legacy MSVC archives remain: $($remaining.Name -join ', ')"
}
foreach ($name in $requiredRuntime) {
    if (-not (Test-Path -LiteralPath (Join-Path $targetLib $name) -PathType Leaf)) {
        throw "Stage Y runtime safety archive missing after pruning: $name"
    }
}

$stageXReport = Join-Path $root "minimization-stage-x.json"
if (-not (Test-Path -LiteralPath $stageXReport -PathType Leaf)) {
    throw "Stage X minimization report missing before Stage Y: $stageXReport"
}

$report = [ordered]@{
    stage = "stage-y"
    parent_stage = "stage-x"
    evidence_run = 201
    evidence_link_trace_count = 27
    family = "versioned_legacy_msvc_target_import_libraries"
    patterns = $patterns | ForEach-Object { "x86_64-w64-mingw32/lib/$_" }
    removed_file_count = $removed.Count
    removed_bytes = $actualBytes
    removed_mib = [math]::Round($actualBytes / 1MB, 3)
    removed = $removed
}
$reportPath = Join-Path $root "minimization-stage-y.json"
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

$metadataPath = Join-Path $root "metadata.json"
if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
    throw "LLVM-MinGW metadata missing before Stage Y: $metadataPath"
}
$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
if ([string]$metadata.library_minimization_stage -ne "stage-x") {
    throw "Stage Y expected Stage X library metadata, got: $($metadata.library_minimization_stage)"
}
$metadata | Add-Member -NotePropertyName library_minimization_stage -NotePropertyValue "stage-y" -Force
$metadata | Add-Member -NotePropertyName library_minimization_report -NotePropertyValue "minimization-stage-y.json" -Force
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
        throw "Phase 6 size gate failed after Stage Y: staged payload $payloadBytes bytes exceeds 50% ceiling $phase6GateBytes bytes"
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

Write-Host "LLVM-MinGW minimization stage-y"
Write-Host "  Stage Y removed files: $($removed.Count)"
Write-Host "  Stage Y removed MiB: $([math]::Round($actualBytes / 1MB, 2))"
Write-Host "  payload MiB after Stage Y: $([math]::Round($payloadBytes / 1MB, 2))"
