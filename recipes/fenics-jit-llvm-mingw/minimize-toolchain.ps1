param(
    [Parameter(Mandatory = $true)][string]$ToolchainRoot,
    [ValidateSet("stage-a")][string]$Stage = "stage-a"
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

$before = Get-PayloadStats
$removed = @()

if ($Stage -eq "stage-a") {
    $bin = Join-Path $root "bin"
    if (-not (Test-Path -LiteralPath $bin -PathType Container)) {
        throw "LLVM-MinGW bin directory missing: $bin"
    }

    $unsupportedAliasPattern = "^(?:aarch64|arm64ec|armv7|i686)-w64-mingw32(?:uwp)?(?:-|$)"
    foreach ($file in @(Get-ChildItem -LiteralPath $bin -File | Sort-Object Name)) {
        if ($file.Name -match $unsupportedAliasPattern) {
            $relative = $file.FullName.Substring($root.Length).TrimStart("\").Replace("\", "/")
            $removed += [pscustomobject]@{
                path = $relative
                bytes = [int64]$file.Length
            }
            Remove-Item -LiteralPath $file.FullName -Force
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
    if ($removed.Count -eq 0) {
        throw "Stage A removed no unsupported target aliases; upstream layout may have changed"
    }
}

$after = Get-PayloadStats
$removedBytes = ($removed | Measure-Object bytes -Sum).Sum
if ($null -eq $removedBytes) { $removedBytes = 0 }

$report = [ordered]@{
    stage = $Stage
    before_file_count = $before.file_count
    before_bytes = $before.bytes
    after_file_count = $after.file_count
    after_bytes = $after.bytes
    removed_file_count = $removed.Count
    removed_bytes = [int64]$removedBytes
    removed = $removed
}
$reportPath = Join-Path $root "minimization-$Stage.json"
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "LLVM-MinGW minimization $Stage"
Write-Host "  removed files: $($removed.Count)"
Write-Host "  removed MiB: $([math]::Round($removedBytes / 1MB, 2))"
Write-Host "  payload MiB before: $([math]::Round($before.bytes / 1MB, 2))"
Write-Host "  payload MiB after: $([math]::Round($after.bytes / 1MB, 2))"
