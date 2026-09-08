param(
    [Parameter(Mandatory = $true)][string]$ToolchainRoot,
    [ValidateSet("stage-a", "stage-b", "stage-c", "stage-d", "stage-e", "stage-f")][string]$Stage = "stage-f"
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
            $removeCxx = $file.Name -match "^libc\+\+"
            $removeUnwind = $file.Name -match "^libunwind" -and $file.Name -ne "libunwind.a"
            if ($removeCxx -or $removeUnwind) {
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

    $staticUnwind = Join-Path $targetLib "libunwind.a"
    if (-not (Test-Path -LiteralPath $staticUnwind -PathType Leaf)) {
        throw "Required Clang C link runtime missing after Stage B: $staticUnwind"
    }

    $remainingRuntime = @()
    if (Test-Path -LiteralPath $targetBin -PathType Container) {
        $remainingRuntime += @(
            Get-ChildItem -LiteralPath $targetBin -File |
                Where-Object { $_.Name -match "^(?:libc\+\+|libunwind)" }
        )
    }
    if (Test-Path -LiteralPath $targetLib -PathType Container) {
        $remainingRuntime += @(
            Get-ChildItem -LiteralPath $targetLib -File |
                Where-Object {
                    $_.Name -match "^libc\+\+" -or
                    ($_.Name -match "^libunwind" -and $_.Name -ne "libunwind.a")
                }
        )
    }
    if ($remainingRuntime.Count -ne 0) {
        throw "Unneeded target C++ runtime files remain after Stage B: $($remainingRuntime.Name -join ', ')"
    }
}


function Invoke-StageC {
    $bin = Join-Path $root "bin"
    if (-not (Test-Path -LiteralPath $bin -PathType Container)) {
        throw "LLVM-MinGW bin directory missing: $bin"
    }

    # Retain only executables observed or required by package construction and
    # Phase 5: the target Clang driver/front-end, LLD, PE inspection, and GNU
    # import-library generation. Clang uses its integrated assembler.
    $keepExecutables = @(
        "x86_64-w64-mingw32-clang.exe",
        "clang-23.exe",
        "ld.lld.exe",
        "llvm-readobj.exe",
        "llvm-dlltool.exe"
    )
    if ($Stage -in @("stage-e", "stage-f")) {
        # Build-only: Stage E uses llvm-strip and removes it before packaging.
        $keepExecutables += "llvm-strip.exe"
    }
    $keepSet = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($name in $keepExecutables) { [void]$keepSet.Add($name) }

    foreach ($file in @(Get-ChildItem -LiteralPath $bin -File | Sort-Object Name)) {
        if ($file.Extension -ieq ".exe" -and -not $keepSet.Contains($file.Name)) {
            Remove-PayloadFile -File $file -RemovalStage "stage-c" -Group "unused-executable"
        }
    }

    # These DLLs are only required by tools removed above. The retained Clang,
    # LLD, readobj, and dlltool dependency graph does not reference them.
    foreach ($name in @(
        "liblldb.dll",
        "libpython3.14.dll",
        "libpython3.dll",
        "libffi-8.dll",
        "libomp.dll"
    )) {
        $path = Join-Path $bin $name
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            Remove-PayloadFile -File (Get-Item -LiteralPath $path) -RemovalStage "stage-c" -Group "unused-tool-runtime"
        }
    }

    foreach ($name in $keepExecutables) {
        $path = Join-Path $bin $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required Stage C executable missing: $path"
        }
    }
    foreach ($name in @("libLLVM-23.dll", "libclang-cpp.dll", "libc++.dll", "libunwind.dll")) {
        $path = Join-Path $bin $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required LLVM tool runtime missing after Stage C: $path"
        }
    }

    $unexpectedExecutables = @(
        Get-ChildItem -LiteralPath $bin -File |
            Where-Object { $_.Extension -ieq ".exe" -and -not $keepSet.Contains($_.Name) }
    )
    if ($unexpectedExecutables.Count -ne 0) {
        throw "Unexpected executables remain after Stage C: $($unexpectedExecutables.Name -join ', ')"
    }
}


function Invoke-StageD {
    $clangRuntimeRoot = Join-Path $root "lib\clang\23\lib"
    $linuxRuntime = Join-Path $clangRuntimeRoot "linux"
    $windowsRuntime = Join-Path $clangRuntimeRoot "windows"

    # This package targets x86-64 Windows only. Linux compiler runtimes and
    # Windows sanitizer/profiling/fuzzer/unsupported-architecture runtimes are
    # not part of ordinary FFCx C compilation. Keep only the compiler-rt
    # builtins archive used by the x86-64 Windows Clang driver.
    Remove-PayloadTree -Path $linuxRuntime -RemovalStage "stage-d" -Group "non-windows-clang-runtime"

    if (-not (Test-Path -LiteralPath $windowsRuntime -PathType Container)) {
        throw "Clang Windows runtime directory missing: $windowsRuntime"
    }

    $requiredBuiltins = "libclang_rt.builtins-x86_64.a"
    foreach ($file in @(Get-ChildItem -LiteralPath $windowsRuntime -Recurse -File | Sort-Object FullName)) {
        if ($file.Name -ne $requiredBuiltins) {
            Remove-PayloadFile -File $file -RemovalStage "stage-d" -Group "unused-clang-runtime"
        }
    }

    if (Test-Path -LiteralPath $linuxRuntime) {
        throw "Linux Clang runtime tree remains after Stage D: $linuxRuntime"
    }

    $builtins = Join-Path $windowsRuntime $requiredBuiltins
    if (-not (Test-Path -LiteralPath $builtins -PathType Leaf)) {
        throw "Required x86-64 compiler-rt builtins missing after Stage D: $builtins"
    }

    $remaining = @(Get-ChildItem -LiteralPath $windowsRuntime -Recurse -File)
    if ($remaining.Count -ne 1 -or $remaining[0].Name -ne $requiredBuiltins) {
        throw "Unexpected Clang Windows runtimes remain after Stage D: $($remaining.FullName -join ', ')"
    }
}


$stripped = @()

function Invoke-StageE {
    $bin = Join-Path $root "bin"
    $targetBin = Join-Path $root "x86_64-w64-mingw32\bin"
    $strip = Join-Path $bin "llvm-strip.exe"
    if (-not (Test-Path -LiteralPath $strip -PathType Leaf)) {
        throw "Build-only llvm-strip missing before Stage E: $strip"
    }

    # llvm-strip links against DLLs in the same bin directory. Running it in
    # place locks those DLLs on Windows, which prevents llvm-strip from
    # rewriting them. Copy the tool and its complete local DLL set outside the
    # staged payload so every staged PE file remains writable.
    $stripRunnerRoot = Join-Path ([IO.Path]::GetTempPath()) ("fenics-jit-llvm-strip-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $stripRunnerRoot | Out-Null
    $stripRunner = Join-Path $stripRunnerRoot "llvm-strip.exe"
    Copy-Item -LiteralPath $strip -Destination $stripRunner
    foreach ($dll in @(Get-ChildItem -LiteralPath $bin -File | Where-Object { $_.Extension -ieq ".dll" })) {
        Copy-Item -LiteralPath $dll.FullName -Destination (Join-Path $stripRunnerRoot $dll.Name)
    }

    try {
        & $stripRunner --version | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Temporary llvm-strip runner failed to start from $stripRunnerRoot"
        }

        $targets = @()
        foreach ($dir in @($bin, $targetBin)) {
            if (Test-Path -LiteralPath $dir -PathType Container) {
                $targets += @(
                    Get-ChildItem -LiteralPath $dir -File |
                        Where-Object {
                            ($_.Extension -ieq ".exe" -or $_.Extension -ieq ".dll") -and
                            $_.FullName -ne $strip
                        }
                )
            }
        }

        foreach ($file in @($targets | Sort-Object FullName -Unique)) {
            $beforeBytes = [int64]$file.Length
            & $stripRunner --strip-debug $file.FullName
            if ($LASTEXITCODE -ne 0) {
                throw "llvm-strip --strip-debug failed for $($file.FullName)"
            }
            $afterFile = Get-Item -LiteralPath $file.FullName
            $afterBytes = [int64]$afterFile.Length
            if ($afterBytes -gt $beforeBytes) {
                throw "Stripping increased file size for $($file.FullName): $beforeBytes -> $afterBytes"
            }
            $relative = $file.FullName.Substring($root.Length).TrimStart("\").Replace("\", "/")
            $script:stripped += [pscustomobject]@{
                path = $relative
                before_bytes = $beforeBytes
                after_bytes = $afterBytes
                saved_bytes = [int64]($beforeBytes - $afterBytes)
            }
        }
    }
    finally {
        Remove-Item -LiteralPath $stripRunnerRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    # llvm-strip is required only while constructing Stage E.
    Remove-PayloadFile -File (Get-Item -LiteralPath $strip) -RemovalStage "stage-e" -Group "build-only-strip-tool"

    if (Test-Path -LiteralPath $strip) {
        throw "Build-only llvm-strip remains after Stage E: $strip"
    }
}

function Invoke-StageF {
    $include = Join-Path $root "include"
    if (-not (Test-Path -LiteralPath $include -PathType Container)) {
        throw "LLVM-MinGW root include directory missing: $include"
    }

    # Run #176 measured 27 full Phase 5 dependency closures and observed no
    # mshtml* header. These are legacy HTML/Trident COM API declarations and
    # are unrelated to FFCx-generated numerical C. Prune only this coherent
    # measured-unobserved family; broader Windows headers remain conservative.
    $matches = @(
        Get-ChildItem -LiteralPath $include -File |
            Where-Object { $_.Name.StartsWith("mshtml", [System.StringComparison]::OrdinalIgnoreCase) } |
            Sort-Object Name
    )
    if ($matches.Count -eq 0) {
        throw "Stage F found no mshtml* headers; upstream layout may have changed"
    }

    foreach ($file in $matches) {
        Remove-PayloadFile -File $file -RemovalStage "stage-f" -Group "unobserved-mshtml-headers"
    }

    $remaining = @(
        Get-ChildItem -LiteralPath $include -File |
            Where-Object { $_.Name.StartsWith("mshtml", [System.StringComparison]::OrdinalIgnoreCase) }
    )
    if ($remaining.Count -ne 0) {
        throw "Stage F mshtml* headers remain: $($remaining.Name -join ', ')"
    }
}

$before = Get-PayloadStats

Invoke-StageA
$afterStageA = Get-PayloadStats

if ($Stage -in @("stage-b", "stage-c", "stage-d", "stage-e", "stage-f")) {
    Invoke-StageB
}
$afterStageB = Get-PayloadStats

if ($Stage -in @("stage-c", "stage-d", "stage-e", "stage-f")) {
    Invoke-StageC
}
$afterStageC = Get-PayloadStats

if ($Stage -in @("stage-d", "stage-e", "stage-f")) {
    Invoke-StageD
}
$afterStageD = Get-PayloadStats

if ($Stage -in @("stage-e", "stage-f")) {
    Invoke-StageE
}
$afterStageE = Get-PayloadStats

if ($Stage -eq "stage-f") {
    Invoke-StageF
}
$after = Get-PayloadStats

$stageARemoved = @($removed | Where-Object { $_.stage -eq "stage-a" })
$stageBRemoved = @($removed | Where-Object { $_.stage -eq "stage-b" })
$stageCRemoved = @($removed | Where-Object { $_.stage -eq "stage-c" })
$stageDRemoved = @($removed | Where-Object { $_.stage -eq "stage-d" })
$stageERemoved = @($removed | Where-Object { $_.stage -eq "stage-e" })
$stageFRemoved = @($removed | Where-Object { $_.stage -eq "stage-f" })

function Get-RemovedBytes {
    param([object[]]$Items)
    $value = ($Items | Measure-Object bytes -Sum).Sum
    if ($null -eq $value) { return [int64]0 }
    return [int64]$value
}

$stageARemovedBytes = Get-RemovedBytes $stageARemoved
$stageBRemovedBytes = Get-RemovedBytes $stageBRemoved
$stageCRemovedBytes = Get-RemovedBytes $stageCRemoved
$stageDRemovedBytes = Get-RemovedBytes $stageDRemoved
$stageERemovedBytes = Get-RemovedBytes $stageERemoved
$stageFRemovedBytes = Get-RemovedBytes $stageFRemoved
$removedBytes = Get-RemovedBytes $removed
$strippedBytesSaved = Get-RemovedBytes @(
    $stripped | ForEach-Object {
        [pscustomobject]@{ bytes = [int64]$_.saved_bytes }
    }
)

if ($stageARemoved.Count -eq 0) {
    throw "Stage A removed no unsupported target aliases; upstream layout may have changed"
}
if ($Stage -in @("stage-b", "stage-c", "stage-d", "stage-e", "stage-f") -and $stageBRemoved.Count -eq 0) {
    throw "Stage B removed no C++ payload; upstream layout may have changed"
}
if ($Stage -in @("stage-c", "stage-d", "stage-e", "stage-f") -and $stageCRemoved.Count -eq 0) {
    throw "Stage C removed no unused LLVM tools; upstream layout may have changed"
}
if ($Stage -in @("stage-d", "stage-e", "stage-f") -and $stageDRemoved.Count -eq 0) {
    throw "Stage D removed no unused Clang runtimes; upstream layout may have changed"
}
if ($Stage -in @("stage-e", "stage-f") -and $stageERemoved.Count -eq 0) {
    throw "Stage E did not remove its build-only stripping tool"
}
if ($Stage -eq "stage-f" -and $stageFRemoved.Count -eq 0) {
    throw "Stage F removed no measured-unobserved mshtml* headers"
}

$report = [ordered]@{
    stage = $Stage
    before_file_count = $before.file_count
    before_bytes = $before.bytes
    after_stage_a_file_count = $afterStageA.file_count
    after_stage_a_bytes = $afterStageA.bytes
    after_stage_b_file_count = $afterStageB.file_count
    after_stage_b_bytes = $afterStageB.bytes
    after_stage_c_file_count = $afterStageC.file_count
    after_stage_c_bytes = $afterStageC.bytes
    after_stage_d_file_count = $afterStageD.file_count
    after_stage_d_bytes = $afterStageD.bytes
    after_stage_e_file_count = $afterStageE.file_count
    after_stage_e_bytes = $afterStageE.bytes
    after_file_count = $after.file_count
    after_bytes = $after.bytes
    removed_file_count = $removed.Count
    removed_bytes = [int64]$removedBytes
    stage_a_removed_file_count = $stageARemoved.Count
    stage_a_removed_bytes = [int64]$stageARemovedBytes
    stage_b_removed_file_count = $stageBRemoved.Count
    stage_b_removed_bytes = [int64]$stageBRemovedBytes
    stage_c_removed_file_count = $stageCRemoved.Count
    stage_c_removed_bytes = [int64]$stageCRemovedBytes
    stage_d_removed_file_count = $stageDRemoved.Count
    stage_d_removed_bytes = [int64]$stageDRemovedBytes
    stage_e_removed_file_count = $stageERemoved.Count
    stage_e_removed_bytes = [int64]$stageERemovedBytes
    stage_e_stripped_file_count = $stripped.Count
    stage_e_stripped_bytes_saved = [int64]$strippedBytesSaved
    stage_f_removed_file_count = $stageFRemoved.Count
    stage_f_removed_bytes = [int64]$stageFRemovedBytes
    stripped = $stripped
    removed = $removed
}
$reportPath = Join-Path $root "minimization-$Stage.json"
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "LLVM-MinGW minimization $Stage"
Write-Host "  Stage A removed files: $($stageARemoved.Count)"
Write-Host "  Stage A removed MiB: $([math]::Round($stageARemovedBytes / 1MB, 2))"
if ($Stage -in @("stage-b", "stage-c", "stage-d", "stage-e", "stage-f")) {
    Write-Host "  Stage B removed files: $($stageBRemoved.Count)"
    Write-Host "  Stage B removed MiB: $([math]::Round($stageBRemovedBytes / 1MB, 2))"
}
if ($Stage -in @("stage-c", "stage-d", "stage-e", "stage-f")) {
    Write-Host "  Stage C removed files: $($stageCRemoved.Count)"
    Write-Host "  Stage C removed MiB: $([math]::Round($stageCRemovedBytes / 1MB, 2))"
}
if ($Stage -in @("stage-d", "stage-e", "stage-f")) {
    Write-Host "  Stage D removed files: $($stageDRemoved.Count)"
    Write-Host "  Stage D removed MiB: $([math]::Round($stageDRemovedBytes / 1MB, 2))"
}
if ($Stage -in @("stage-e", "stage-f")) {
    Write-Host "  Stage E stripped files: $($stripped.Count)"
    Write-Host "  Stage E stripped MiB saved: $([math]::Round($strippedBytesSaved / 1MB, 2))"
    Write-Host "  Stage E removed build-only MiB: $([math]::Round($stageERemovedBytes / 1MB, 2))"
}
if ($Stage -eq "stage-f") {
    Write-Host "  Stage F removed files: $($stageFRemoved.Count)"
    Write-Host "  Stage F removed MiB: $([math]::Round($stageFRemovedBytes / 1MB, 2))"
}
Write-Host "  cumulative removed files: $($removed.Count)"
Write-Host "  cumulative removed MiB: $([math]::Round($removedBytes / 1MB, 2))"
Write-Host "  payload MiB before: $([math]::Round($before.bytes / 1MB, 2))"
Write-Host "  payload MiB after Stage A: $([math]::Round($afterStageA.bytes / 1MB, 2))"
if ($Stage -in @("stage-b", "stage-c", "stage-d", "stage-e", "stage-f")) {
    Write-Host "  payload MiB after Stage B: $([math]::Round($afterStageB.bytes / 1MB, 2))"
}
if ($Stage -in @("stage-c", "stage-d", "stage-e", "stage-f")) {
    Write-Host "  payload MiB after Stage C: $([math]::Round($afterStageC.bytes / 1MB, 2))"
}
if ($Stage -in @("stage-d", "stage-e", "stage-f")) {
    Write-Host "  payload MiB after Stage D: $([math]::Round($afterStageD.bytes / 1MB, 2))"
}
Write-Host "  payload MiB after: $([math]::Round($after.bytes / 1MB, 2))"
