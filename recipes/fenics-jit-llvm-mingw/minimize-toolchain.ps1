param(
    [Parameter(Mandatory = $true)][string]$ToolchainRoot,
    [ValidateSet("stage-a", "stage-b")][string]$Stage = "stage-b"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = [System.IO.Path]::GetFullPath($ToolchainRoot)
if (-not (Test-Path -LiteralPath $root -PathType Container)) {
    throw "Toolchain root does not exist: $root"
}

function Get-PayloadStats {
    $files = @(Get-ChildItem -LiteralPath $root -Recurse -File)
    $bytes = ($files | Measure-Object Length -Sum).Sum
    if ($null -eq $bytes) { $bytes = 0 }
    [pscustomobject]@{
        file_count = $files.Count
        bytes = [int64]$bytes
    }
}

$removed = @()

function Remove-PayloadFile {
    param(
        [Parameter(Mandatory = $true)][System.IO.FileInfo]$File,
        [Parameter(Mandatory = $true)][string]$RemovalStage,
        [Parameter(Mandatory = $true)][string]$Group
    )
    $relative = $File.FullName.Substring($root.Length).TrimStart("\").Replace("\", "/")
    $script:removed += [pscustomobject]@{
        stage = $RemovalStage
        group = $Group
        path = $relative
        bytes = [int64]$File.Length
    }
    Remove-Item -LiteralPath $File.FullName -Force
}

function Remove-PayloadTree {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RemovalStage,
        [Parameter(Mandatory = $true)][string]$Group
    )
    if (-not (Test-Path -LiteralPath $Path)) { return }
    foreach ($file in @(Get-ChildItem -LiteralPath $Path -Recurse -File | Sort-Object FullName)) {
        Remove-PayloadFile -File $file -RemovalStage $RemovalStage -Group $Group
    }
    Remove-Item -LiteralPath $Path -Recurse -Force
}

function Invoke-StageA {
    $bin = Join-Path $root "bin"
    if (-not (Test-Path -LiteralPath $bin -PathType Container)) {
        throw "LLVM-MinGW bin directory missing: $bin"
    }

    $unsupportedAliasPattern = "^(?:aarch64|arm64ec|armv7|i686)-w64-mingw32(?:uwp)?(?:-|$)"
    foreach ($file in @(Get-ChildItem -LiteralPath $bin -File | Sort-Object Name)) {
        if ($file.Name -match $unsupportedAliasPattern) {
            Remove-PayloadFile -File $file -RemovalStage "stage-a" -Group "unsupported-target-alias"
        }
    }

    foreach ($target in @(
        "aarch64-w64-mingw32",
        "arm64ec-w64-mingw32",
        "armv7-w64-mingw32",
        "i686-w64-mingw32"
    )) {
        $targetRoot = Join-Path $root $target
        if (Test-Path -LiteralPath $targetRoot) {
            throw "Unsupported target sysroot was staged: $targetRoot"
        }
    }

    $leftovers = @(
        Get-ChildItem -LiteralPath $bin -File |
            Where-Object { $_.Name -match $unsupportedAliasPattern }
    )
    if ($leftovers.Count -ne 0) {
        throw "Unsupported target aliases remain after Stage A: $($leftovers.Name -join ', ')"
    }
}

function Invoke-StageB {
    $bin = Join-Path $root "bin"
    $targetRoot = Join-Path $root "x86_64-w64-mingw32"
    $targetBin = Join-Path $targetRoot "bin"
    $targetLib = Join-Path $targetRoot "lib"

    Remove-PayloadTree -Path (Join-Path $root "include\c++") -RemovalStage "stage-b" -Group "cxx-headers"

    foreach ($name in @("libunwind.h", "libunwind.modulemap")) {
        $path = Join-Path $root "include\$name"
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            Remove-PayloadFile -File (Get-Item -LiteralPath $path) -RemovalStage "stage-b" -Group "libunwind-headers"
        }
    }

    $cxxDriverPattern = "^(?:(?:c|g|clang)\+\+|x86_64-w64-mingw32(?:uwp)?-(?:c|g|clang)\+\+)(?:\.exe)?$"
    foreach ($file in @(Get-ChildItem -LiteralPath $bin -File | Sort-Object Name)) {
        if ($file.Name -match $cxxDriverPattern) {
            Remove-PayloadFile -File $file -RemovalStage "stage-b" -Group "cxx-driver-alias"
        }
    }

    if (Test-Path -LiteralPath $targetBin -PathType Container) {
        foreach ($file in @(Get-ChildItem -LiteralPath $targetBin -File | Sort-Object Name)) {
            if ($file.Name -match "^(?:libc\+\+|libunwind)") {
                Remove-PayloadFile -File $file -RemovalStage "stage-b" -Group "cxx-runtime-dll"
            }
        }
    }

    if (Test-Path -LiteralPath $targetLib -PathType Container) {
        foreach ($file in @(Get-ChildItem -LiteralPath $targetLib -File | Sort-Object Name)) {
            if ($file.Name -match "^(?:libc\+\+|libunwind)") {
                Remove-PayloadFile -File $file -RemovalStage "stage-b" -Group "cxx-runtime-library"
            }
        }
    }

    $forbiddenPaths = @(
        (Join-Path $root "include\c++"),
        (Join-Path $root "include\libunwind.h"),
        (Join-Path $root "include\libunwind.modulemap")
    )
    $remainingPaths = @($forbiddenPaths | Where-Object { Test-Path -LiteralPath $_ })
    if ($remainingPaths.Count -ne 0) {
        throw "C++/libunwind headers remain after Stage B: $($remainingPaths -join ', ')"
    }

    $remainingDrivers = @(
        Get-ChildItem -LiteralPath $bin -File |
            Where-Object { $_.Name -match $cxxDriverPattern }
    )
    if ($remainingDrivers.Count -ne 0) {
        throw "C++ driver aliases remain after Stage B: $($remainingDrivers.Name -join ', ')"
    }

    $remainingRuntime = @()
    foreach ($dir in @($targetBin, $targetLib)) {
        if (Test-Path -LiteralPath $dir -PathType Container) {
            $remainingRuntime += @(
                Get-ChildItem -LiteralPath $dir -File |
                    Where-Object { $_.Name -match "^(?:libc\+\+|libunwind)" }
            )
        }
    }
    if ($remainingRuntime.Count -ne 0) {
        throw "C++ runtime files remain after Stage B: $($remainingRuntime.Name -join ', ')"
    }
}

$before = Get-PayloadStats
Invoke-StageA
$afterStageA = Get-PayloadStats

if ($Stage -eq "stage-b") {
    Invoke-StageB
}
$after = Get-PayloadStats

$removedBytes = ($removed | Measure-Object bytes -Sum).Sum
if ($null -eq $removedBytes) { $removedBytes = 0 }
$stageARemoved = @($removed | Where-Object { $_.stage -eq "stage-a" })
$stageBRemoved = @($removed | Where-Object { $_.stage -eq "stage-b" })
$stageARemovedBytes = ($stageARemoved | Measure-Object bytes -Sum).Sum
$stageBRemovedBytes = ($stageBRemoved | Measure-Object bytes -Sum).Sum
if ($null -eq $stageARemovedBytes) { $stageARemovedBytes = 0 }
if ($null -eq $stageBRemovedBytes) { $stageBRemovedBytes = 0 }

if ($stageARemoved.Count -eq 0) {
    throw "Stage A removed no unsupported target aliases; upstream layout may have changed"
}
if ($Stage -eq "stage-b" -and $stageBRemoved.Count -eq 0) {
    throw "Stage B removed no C++ payload; upstream layout may have changed"
}

$report = [ordered]@{
    stage = $Stage
    before_file_count = $before.file_count
    before_bytes = $before.bytes
    after_stage_a_file_count = $afterStageA.file_count
    after_stage_a_bytes = $afterStageA.bytes
    after_file_count = $after.file_count
    after_bytes = $after.bytes
    removed_file_count = $removed.Count
    removed_bytes = [int64]$removedBytes
    stage_a_removed_file_count = $stageARemoved.Count
    stage_a_removed_bytes = [int64]$stageARemovedBytes
    stage_b_removed_file_count = $stageBRemoved.Count
    stage_b_removed_bytes = [int64]$stageBRemovedBytes
    removed = $removed
}
$reportPath = Join-Path $root "minimization-$Stage.json"
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "LLVM-MinGW minimization $Stage"
Write-Host "  Stage A removed files: $($stageARemoved.Count)"
Write-Host "  Stage A removed MiB: $([math]::Round($stageARemovedBytes / 1MB, 2))"
if ($Stage -eq "stage-b") {
    Write-Host "  Stage B removed files: $($stageBRemoved.Count)"
    Write-Host "  Stage B removed MiB: $([math]::Round($stageBRemovedBytes / 1MB, 2))"
}
Write-Host "  cumulative removed files: $($removed.Count)"
Write-Host "  cumulative removed MiB: $([math]::Round($removedBytes / 1MB, 2))"
Write-Host "  payload MiB before: $([math]::Round($before.bytes / 1MB, 2))"
Write-Host "  payload MiB after Stage A: $([math]::Round($afterStageA.bytes / 1MB, 2))"
Write-Host "  payload MiB after: $([math]::Round($after.bytes / 1MB, 2))"
