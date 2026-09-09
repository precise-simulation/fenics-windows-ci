Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $env:LIBRARY_PREFIX) { throw "LIBRARY_PREFIX is not set" }

$root = Join-Path $env:LIBRARY_PREFIX "fenics-jit"
$targetLib = Join-Path $root "x86_64-w64-mingw32\lib"
if (-not (Test-Path -LiteralPath $targetLib -PathType Container)) {
    throw "LLVM-MinGW target library directory missing: $targetLib"
}

# Run #199 repaired LLD archive measurement and requalified Stage W across all
# 27 Phase 5 link traces. The matching Direct3D/DXGI/Direct2D/DirectWrite
# archives were unobserved in every trace: 63 files / 2.327 MiB. Their matching
# root header families were already removed and requalified in Stages G/H.
# Keep MinGW/UCRT/startup libraries outside this stage entirely.
$patterns = @("libd3d*.a", "libdxgi*.a", "libdxcore*.a", "libd2d*.a", "libdwrite*.a")
$matches = @(
    Get-ChildItem -LiteralPath $targetLib -File |
        Where-Object {
            $name = $_.Name
            ($patterns | Where-Object { $name -like $_ }).Count -gt 0
        } |
        Sort-Object Name
)
if ($matches.Count -ne 63) {
    throw "Stage X expected 63 DirectX-family archives from run #199 evidence, found $($matches.Count); refusing changed candidate set"
}

$requiredRuntime = @("libmingw32.a", "libmingwex.a", "libucrt.a", "libkernel32.a", "libunwind.a")
foreach ($name in $requiredRuntime) {
    if (-not (Test-Path -LiteralPath (Join-Path $targetLib $name) -PathType Leaf)) {
        throw "Stage X runtime safety archive missing before pruning: $name"
    }
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
    Get-ChildItem -LiteralPath $targetLib -File |
        Where-Object {
            $name = $_.Name
            ($patterns | Where-Object { $name -like $_ }).Count -gt 0
        }
)
if ($remaining.Count -ne 0) {
    throw "Stage X DirectX-family archives remain: $($remaining.Name -join ', ')"
}
foreach ($name in $requiredRuntime) {
    if (-not (Test-Path -LiteralPath (Join-Path $targetLib $name) -PathType Leaf)) {
        throw "Stage X runtime safety archive missing after pruning: $name"
    }
}

$stageWReport = Join-Path $root "minimization-stage-w.json"
if (-not (Test-Path -LiteralPath $stageWReport -PathType Leaf)) {
    throw "Stage W minimization report missing before Stage X: $stageWReport"
}

$report = [ordered]@{
    stage = "stage-x"
    parent_stage = "stage-w"
    evidence_run = 199
    evidence_link_trace_count = 27
    family = "directx_target_import_libraries"
    patterns = $patterns | ForEach-Object { "x86_64-w64-mingw32/lib/$_" }
    removed_file_count = $removed.Count
    removed_bytes = $removedBytes
    removed_mib = [math]::Round($removedBytes / 1MB, 3)
    removed = $removed
}
$reportPath = Join-Path $root "minimization-stage-x.json"
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

# Preserve the header-stage metadata contract used by existing package tests,
# while recording the independent library-pruning stage explicitly.
$metadataPath = Join-Path $root "metadata.json"
if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
    throw "LLVM-MinGW metadata missing before Stage X: $metadataPath"
}
$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
if ([string]$metadata.minimization_stage -ne "stage-w") {
    throw "Stage X expected Stage W header metadata, got: $($metadata.minimization_stage)"
}
$metadata | Add-Member -NotePropertyName library_minimization_stage -NotePropertyValue "stage-x" -Force
$metadata | Add-Member -NotePropertyName library_minimization_report -NotePropertyValue "minimization-stage-x.json" -Force
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
        throw "Phase 6 size gate failed after Stage X: staged payload $payloadBytes bytes exceeds 50% ceiling $phase6GateBytes bytes"
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

Write-Host "LLVM-MinGW minimization stage-x"
Write-Host "  Stage X removed files: $($removed.Count)"
Write-Host "  Stage X removed MiB: $([math]::Round($removedBytes / 1MB, 2))"
Write-Host "  payload MiB after Stage X: $([math]::Round($payloadBytes / 1MB, 2))"
