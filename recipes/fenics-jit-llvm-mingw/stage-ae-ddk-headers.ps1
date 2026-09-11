Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $env:LIBRARY_PREFIX) { throw "LIBRARY_PREFIX is not set" }

$root = Join-Path $env:LIBRARY_PREFIX "fenics-jit"
$include = Join-Path $root "include"
$ddkInclude = Join-Path $include "ddk"
if (-not (Test-Path -LiteralPath $ddkInclude -PathType Container)) {
    throw "LLVM-MinGW DDK include directory missing: $ddkInclude"
}

# Run #209 requalified Stage AD across all 27 Phase 5 compile dependency
# closures. Every retained include/ddk file below was unobserved in every
# trace: 80 files / 2.156 MiB. Use exact names and bytes so an upstream layout
# change cannot silently broaden this pruning step.
$names = @(
    "acpiioct.h",
    "afilter.h",
    "amtvuids.h",
    "ata.h",
    "atm.h",
    "bdasup.h",
    "classpnp.h",
    "csq.h",
    "d3dhal.h",
    "d3dhalex.h",
    "d4drvif.h",
    "d4iface.h",
    "dderror.h",
    "dmusicks.h",
    "drivinit.h",
    "drmk.h",
    "dxapi.h",
    "fltsafe.h",
    "hidclass.h",
    "hubbusif.h",
    "ide.h",
    "ioaccess.h",
    "kbdmou.h",
    "mcd.h",
    "mce.h",
    "miniport.h",
    "minitape.h",
    "mountdev.h",
    "mountmgr.h",
    "msports.h",
    "ndis.h",
    "ndisguid.h",
    "ndistapi.h",
    "ndiswan.h",
    "netpnp.h",
    "ntagp.h",
    "ntddk.h",
    "ntddpcm.h",
    "ntddsnd.h",
    "ntifs.h",
    "ntimage.h",
    "ntintsafe.h",
    "ntnls.h",
    "ntpoapi.h",
    "ntstrsafe.h",
    "oprghdlr.h",
    "parallel.h",
    "pfhook.h",
    "poclass.h",
    "portcls.h",
    "punknown.h",
    "scsi.h",
    "scsiscan.h",
    "scsiwmi.h",
    "smbus.h",
    "srb.h",
    "stdunk.h",
    "storport.h",
    "strmini.h",
    "swenum.h",
    "tdikrnl.h",
    "tdistat.h",
    "upssvc.h",
    "usbbusif.h",
    "usbdlib.h",
    "usbdrivr.h",
    "usbkern.h",
    "usbprint.h",
    "usbprotocoldefs.h",
    "usbscan.h",
    "usbstorioctl.h",
    "video.h",
    "videoagp.h",
    "wdm.h",
    "wdmguid.h",
    "wdmsec.h",
    "wmidata.h",
    "wmilib.h",
    "ws2san.h",
    "xfilter.h"
)

$entries = @(Get-ChildItem -LiteralPath $ddkInclude -Force)
if ($entries.Count -ne $names.Count) {
    throw "Stage AE expected exactly $($names.Count) DDK entries from run #209 evidence, found $($entries.Count)"
}
$actualNames = @($entries | ForEach-Object { $_.Name } | Sort-Object)
$expectedNames = @($names | Sort-Object)
$nameDiff = @(Compare-Object -ReferenceObject $expectedNames -DifferenceObject $actualNames)
if ($nameDiff.Count -ne 0) {
    $nameDiff | Format-Table | Out-String | Write-Host
    throw "Stage AE DDK contents differ from the exact run #209 candidate set"
}

$matches = @(
    foreach ($name in $names) {
        $path = Join-Path $ddkInclude $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Stage AE expected run #209 candidate header missing: ddk/$name"
        }
        Get-Item -LiteralPath $path
    }
)
if ($matches.Count -ne 80) {
    throw "Stage AE expected 80 DDK headers from run #209 evidence, found $($matches.Count)"
}

$expectedBytes = [int64]2260924
$actualBytes = [int64](($matches | Measure-Object Length -Sum).Sum)
if ($actualBytes -ne $expectedBytes) {
    throw "Stage AE expected $expectedBytes bytes from run #209 evidence, found $actualBytes; refusing changed candidate set"
}

# Preserve headers directly observed by the Phase 5 dependency closures and a
# small explicit Windows/MinGW safety set.
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
        throw "Stage AE safety header missing before pruning: $name"
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

$remaining = @(Get-ChildItem -LiteralPath $ddkInclude -Force)
if ($remaining.Count -ne 0) {
    $remaining.FullName | Write-Host
    throw "Stage AE DDK include directory is not empty after exact candidate removal"
}
Remove-Item -LiteralPath $ddkInclude -Force
if (Test-Path -LiteralPath $ddkInclude) {
    throw "Stage AE DDK include directory remains after pruning"
}

foreach ($name in $requiredHeaders) {
    if (-not (Test-Path -LiteralPath (Join-Path $include $name) -PathType Leaf)) {
        throw "Stage AE safety header missing after pruning: $name"
    }
}

$stageADReport = Join-Path $root "minimization-stage-ad.json"
if (-not (Test-Path -LiteralPath $stageADReport -PathType Leaf)) {
    throw "Stage AD minimization report missing before Stage AE: $stageADReport"
}

$report = [ordered]@{
    stage = "stage-ae"
    parent_stage = "stage-ad"
    evidence_run = 209
    evidence_compile_trace_count = 27
    family = "windows_driver_development_headers"
    directory = "include/ddk"
    names = $names | ForEach-Object { "include/ddk/$_" }
    removed_file_count = $removed.Count
    removed_bytes = $actualBytes
    removed_mib = [math]::Round($actualBytes / 1MB, 3)
    removed = $removed
}
$reportPath = Join-Path $root "minimization-stage-ae.json"
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

$metadataPath = Join-Path $root "metadata.json"
if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
    throw "LLVM-MinGW metadata missing before Stage AE: $metadataPath"
}
$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
if ([string]$metadata.minimization_stage -ne "stage-ad") {
    throw "Stage AE expected Stage AD header metadata, got: $($metadata.minimization_stage)"
}
if ([string]$metadata.library_minimization_stage -ne "stage-ab") {
    throw "Stage AE expected Stage AB library metadata, got: $($metadata.library_minimization_stage)"
}
$metadata.minimization_stage = "stage-ae"
$metadata.minimization_report = "minimization-stage-ae.json"
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
        throw "Phase 6 size gate failed after Stage AE: staged payload $payloadBytes bytes exceeds 50% ceiling $phase6GateBytes bytes"
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

Write-Host "LLVM-MinGW minimization stage-ae"
Write-Host "  Stage AE removed files: $($removed.Count)"
Write-Host "  Stage AE removed MiB: $([math]::Round($actualBytes / 1MB, 2))"
Write-Host "  payload MiB after Stage AE: $([math]::Round($payloadBytes / 1MB, 2))"
