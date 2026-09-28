param(
    [Parameter(Mandatory = $true)][string]$ToolchainRoot,
    [Parameter(Mandatory = $true)][string]$EvidenceDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = [IO.Path]::GetFullPath($ToolchainRoot)
$evidence = [IO.Path]::GetFullPath($EvidenceDir)
$recipe = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "recipes\fenics-jit-llvm-mingw"
if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw "toolchain root missing: $root" }
if ((Split-Path -Leaf $root) -ne "fenics-jit") { throw "Stage-AW compatibility root must be named fenics-jit: $root" }
New-Item -ItemType Directory -Force $evidence | Out-Null

$include = Join-Path $root "include"
$targetLib = Join-Path $root "x86_64-w64-mingw32\lib"
$metadataPath = Join-Path $root "metadata.json"
foreach ($required in @($include, $targetLib, $metadataPath)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "required minimization input missing: $required" }
}

function Get-Stats {
    $files = @(Get-ChildItem -LiteralPath $root -Recurse -File)
    $bytes = ($files | Measure-Object Length -Sum).Sum
    if ($null -eq $bytes) { $bytes = 0 }
    [pscustomobject]@{ file_count = $files.Count; bytes = [int64]$bytes }
}

$before = Get-Stats
$removed = @()
function Remove-Family {
    param([string]$Stage, [string]$Family, [System.IO.FileInfo[]]$Files)
    foreach ($file in @($Files | Sort-Object FullName -Unique)) {
        $script:removed += [pscustomobject]@{
            stage = $Stage
            family = $Family
            path = $file.FullName.Substring($root.Length).TrimStart("\").Replace("\", "/")
            bytes = [int64]$file.Length
        }
        Remove-Item -LiteralPath $file.FullName -Force
    }
}

# Reuse the exact Stage-AW qualification evidence for the same LLVM-MinGW
# 20260826 / mingw-w64 source identity. These Phase-6 families were measured
# unobserved across 27 broad compile/link traces and subsequently requalified.
# Stage 1 already removed host-only compiler artifacts, so start with the
# measured header families that precede Stage I.
$stageF = @(Get-ChildItem -LiteralPath $include -File | Where-Object { $_.Name -like "mshtml*" })
if ($stageF.Count -eq 0) { throw "no Stage-F mshtml family found" }
Remove-Family "stage-f" "stage-aw-unobserved-mshtml" $stageF

$stageG = @(Get-ChildItem -LiteralPath $include -File | Where-Object {
    $_.Name -like "d3d*" -or $_.Name -like "dxgi*" -or $_.Name -like "dxcore*"
})
if ($stageG.Count -eq 0) { throw "no Stage-G Direct3D/DXGI family found" }
Remove-Family "stage-g" "stage-aw-unobserved-direct3d-dxgi" $stageG

$stageH = @(Get-ChildItem -LiteralPath $include -File | Where-Object {
    $_.Name -like "d2d*" -or $_.Name -like "dwrite*"
})
if ($stageH.Count -eq 0) { throw "no Stage-H Direct2D/DirectWrite family found" }
Remove-Family "stage-h" "stage-aw-unobserved-direct2d-directwrite" $stageH

$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
$metadata | Add-Member -NotePropertyName minimization_stage -NotePropertyValue "stage-h" -Force
$metadata | Add-Member -NotePropertyName minimization_report -NotePropertyValue "minimization-stage-h.json" -Force
$metadata | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $metadataPath -Encoding UTF8
$stageHRemoved = @($removed | Where-Object { $_.stage -in @("stage-f","stage-g","stage-h") })
@{
    stage = "stage-h"
    basis = "reused immutable Stage-AW compile-closure evidence, runs 176/178/179"
    removed = $stageHRemoved
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $root "minimization-stage-h.json") -Encoding UTF8

$oldLibraryPrefix = $env:LIBRARY_PREFIX
$env:LIBRARY_PREFIX = Split-Path -Parent $root
try {
    foreach ($scriptName in @(
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
        "stage-w-windows-management.ps1"
    )) {
        & (Join-Path $recipe $scriptName)
        if ($LASTEXITCODE -ne 0) { throw "qualified Stage-AW pruning script failed: $scriptName" }
    }

    # The source-built import archives are rebuilt from the pinned same-source
    # mingw-w64 tree, so archive byte counts can differ slightly from the
    # immutable binary distribution. Reuse the qualified candidate families,
    # but measure the actual source-built bytes rather than requiring archive
    # byte identity.
    $requiredRuntime = @("libmingw32.a","libmingwex.a","libucrt.a","libkernel32.a","libunwind.a","libmsvcrt.a","libmsvcrt-os.a")
    foreach ($name in $requiredRuntime) {
        if (-not (Test-Path -LiteralPath (Join-Path $targetLib $name) -PathType Leaf)) {
            throw "required C/UCRT runtime archive missing before library pruning: $name"
        }
    }

    $libraryStages = @(
        [pscustomobject]@{ stage="stage-x"; family="directx"; patterns=@("libd3d*.a","libdxgi*.a","libdxcore*.a","libd2d*.a","libdwrite*.a"); names=@() },
        [pscustomobject]@{ stage="stage-y"; family="legacy-msvc"; patterns=@("libmsvcr[0-9]*.a","libmsvcp[0-9]*.a"); names=@() },
        [pscustomobject]@{ stage="stage-z"; family="onecore-uwp"; patterns=@(); names=@("libonecore.a","libonecore_apiset.a","libonecoreuap_apiset.a","libwindowsapp.a","libwindowsappcompat.a") },
        [pscustomobject]@{ stage="stage-aa"; family="nanosrv-headless"; patterns=@(); names=@("libnanosrv.a","libwindowscoreheadless_apiset.a") },
        [pscustomobject]@{ stage="stage-ab"; family="optional-windows-api"; patterns=@(); names=@("libmfplat.a","libmfreadwrite.a","libmfuuid.a","libuiautomationcore.a") }
    )
    $previous = "stage-w"
    foreach ($entry in $libraryStages) {
        $matches = @()
        if ($entry.patterns.Count -gt 0) {
            $matches = @(Get-ChildItem -LiteralPath $targetLib -File | Where-Object {
                $candidate = $_.Name
                @($entry.patterns | Where-Object { $candidate -like $_ }).Count -gt 0
            })
        } else {
            foreach ($name in $entry.names) {
                $candidate = Join-Path $targetLib $name
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { $matches += Get-Item -LiteralPath $candidate }
            }
        }
        if ($matches.Count -eq 0) { throw "no candidates found for $($entry.stage) $($entry.family)" }
        $beforeCount = $removed.Count
        Remove-Family $entry.stage ("stage-aw-unobserved-" + $entry.family) $matches
        $stageRemoved = @($removed[$beforeCount..($removed.Count-1)])
        @{
            stage = $entry.stage
            parent_stage = $previous
            basis = "reused immutable Stage-AW 27-link-trace evidence"
            actual_source_built_archive_bytes = [int64](($stageRemoved | Measure-Object bytes -Sum).Sum)
            removed = $stageRemoved
        } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $root ("minimization-" + $entry.stage + ".json")) -Encoding UTF8
        $previous = $entry.stage
        foreach ($name in $requiredRuntime) {
            if (-not (Test-Path -LiteralPath (Join-Path $targetLib $name) -PathType Leaf)) {
                throw "required C/UCRT runtime archive removed by $($entry.stage): $name"
            }
        }
    }

    $metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
    $metadata | Add-Member -NotePropertyName library_minimization_stage -NotePropertyValue "stage-ab" -Force
    $metadata | Add-Member -NotePropertyName library_minimization_report -NotePropertyValue "minimization-stage-ab.json" -Force
    $metadata | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $metadataPath -Encoding UTF8

    foreach ($scriptName in @(
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
    )) {
        & (Join-Path $recipe $scriptName)
        if ($LASTEXITCODE -ne 0) { throw "qualified Stage-AW pruning script failed: $scriptName" }
    }
}
finally {
    $env:LIBRARY_PREFIX = $oldLibraryPrefix
}

# IDL/type-library source metadata is not a C compiler input. Remove any
# remaining files of those types after the qualified family scripts have run,
# so the family scripts still verify their expected exact candidates first.
$metadataOnly = @(Get-ChildItem -LiteralPath $include -Recurse -File | Where-Object {
    $_.Extension -ieq ".idl" -or $_.Extension -ieq ".tlb"
})
if ($metadataOnly.Count -gt 0) {
    Remove-Family "stage2-interface-metadata" "non-c-interface-definition-metadata" $metadataOnly
}

$after = Get-Stats
$removedBytes = ($removed | Measure-Object bytes -Sum).Sum
if ($null -eq $removedBytes) { $removedBytes = 0 }
$report = [ordered]@{
    schema = "fenics-jit-micro-clang-phase4-stage2-pruning-v1"
    basis = "same-revision Stage-AW measured-unobserved compile/link families plus non-C IDL/TLB metadata"
    before_files = $before.file_count
    before_bytes = $before.bytes
    after_files = $after.file_count
    after_bytes = $after.bytes
    removed_files = $removed.Count
    removed_bytes = [int64]$removedBytes
    removed_mib = [math]::Round([int64]$removedBytes / 1MB, 4)
    production_selector_integrated = $false
    removed = $removed
}
$reportPath = Join-Path $evidence "phase4-stage2-pruning.json"
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8
Copy-Item -LiteralPath $reportPath -Destination (Join-Path $root "phase4-stage2-pruning.json") -Force

Write-Host "micro-Clang Phase-4 stage-2 Stage-AW evidence pruning applied"
Write-Host "  removed MiB: $([math]::Round([int64]$removedBytes / 1MB, 2))"
Write-Host "  remaining MiB before package metadata refresh: $([math]::Round($after.bytes / 1MB, 2))"
