Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$version = "20260826"
$archiveName = "llvm-mingw-$version-ucrt-x86_64.zip"
$archiveSha256 = "ae601f4e0f72bbdf441ad2df8bb16f037e2e9251559ea6b37b4057aef39c06c3"
$upstreamUrl = "https://github.com/mstorsjo/llvm-mingw/releases/download/$version/$archiveName"

if (-not $env:SRC_DIR) { throw "SRC_DIR is not set" }
if (-not $env:LIBRARY_PREFIX) { throw "LIBRARY_PREFIX is not set" }

$archive = Join-Path $env:SRC_DIR $archiveName
if (-not (Test-Path $archive)) {
    $matches = @(Get-ChildItem $env:SRC_DIR -Recurse -File -Filter $archiveName -ErrorAction SilentlyContinue)
    if ($matches.Count -ne 1) {
        throw "Expected exactly one $archiveName below SRC_DIR; found $($matches.Count)"
    }
    $archive = $matches[0].FullName
}

$actualSha256 = (Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSha256 -ne $archiveSha256) {
    throw "LLVM-MinGW archive checksum mismatch: expected $archiveSha256, got $actualSha256"
}

$extractRoot = Join-Path $env:SRC_DIR "_llvm-mingw-extract"
Remove-Item -Recurse -Force $extractRoot -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $extractRoot | Out-Null
$tar = Join-Path $env:SystemRoot "System32\tar.exe"
if (-not (Test-Path $tar)) { throw "Windows tar.exe not found: $tar" }
& $tar -xf $archive -C $extractRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to extract LLVM-MinGW archive with tar.exe" }

$sourceRoot = Join-Path $extractRoot "llvm-mingw-$version-ucrt-x86_64"
if (-not (Test-Path $sourceRoot)) {
    $dirs = @(Get-ChildItem $extractRoot -Directory)
    if ($dirs.Count -ne 1) {
        throw "Could not identify extracted LLVM-MinGW root below $extractRoot"
    }
    $sourceRoot = $dirs[0].FullName
}

$destination = Join-Path $env:LIBRARY_PREFIX "fenics-jit"
Remove-Item -Recurse -Force $destination -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $destination | Out-Null

function Copy-Tree {
    param(
        [Parameter(Mandatory = $true)][string]$RelativeSource,
        [Parameter(Mandatory = $true)][string]$RelativeDestination
    )

    $source = Join-Path $sourceRoot $RelativeSource
    if (-not (Test-Path $source)) {
        throw "Required LLVM-MinGW tree missing: $source"
    }

    $target = Join-Path $destination $RelativeDestination
    $parent = Split-Path $target -Parent
    if ($parent) { New-Item -ItemType Directory -Force $parent | Out-Null }
    Copy-Item -Recurse -Force $source $target
}

# Start from the conservative Phase 2 working set, then apply each Phase 6
# reduction through a deterministic recipe-local minimization script.
Copy-Tree "bin" "bin"
Copy-Tree "include" "include"
Copy-Tree "lib\clang" "lib\clang"
Copy-Tree "x86_64-w64-mingw32" "x86_64-w64-mingw32"

$minimizer = Join-Path $PSScriptRoot "minimize-toolchain.ps1"
if (-not (Test-Path $minimizer)) {
    throw "Phase 6 minimization script missing from recipe: $minimizer"
}
& $minimizer -ToolchainRoot $destination -Stage "stage-h"

$runtimeDir = Join-Path $destination "runtime"
New-Item -ItemType Directory -Force $runtimeDir | Out-Null
$runtimeHelperSource = Join-Path $PSScriptRoot "fenics_jit_runtime.py"
if (-not (Test-Path $runtimeHelperSource)) {
    throw "Runtime helper source missing from recipe: $runtimeHelperSource"
}
Copy-Item -Force $runtimeHelperSource (Join-Path $runtimeDir "fenics_jit_runtime.py")

foreach ($name in @("versions.txt", "LICENSE.TXT")) {
    $source = Join-Path $sourceRoot $name
    if (Test-Path $source) {
        Copy-Item -Force $source (Join-Path $destination $name)
    }
}

$clang = Join-Path $destination "bin\x86_64-w64-mingw32-clang.exe"
$dlltool = Join-Path $destination "bin\llvm-dlltool.exe"
$readobj = Join-Path $destination "bin\llvm-readobj.exe"
$lld = Join-Path $destination "bin\ld.lld.exe"
foreach ($path in @($clang, $dlltool, $readobj, $lld)) {
    if (-not (Test-Path $path)) { throw "Packaged tool missing: $path" }
}

$pythonCandidates = @()
foreach ($prefixName in @("PREFIX", "BUILD_PREFIX")) {
    $prefix = [Environment]::GetEnvironmentVariable($prefixName)
    if ($prefix) {
        $pythonCandidates += (Join-Path $prefix "python3.dll")
        $pythonCandidates += (Join-Path $prefix "DLLs\python3.dll")
        $pythonCandidates += (Join-Path $prefix "Library\bin\python3.dll")
    }
}
$python3Dll = $pythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python3Dll) {
    throw "Could not locate build-time CPython python3.dll"
}

$exports = & $readobj --coff-exports $python3Dll 2>&1
if ($LASTEXITCODE -ne 0) { throw "llvm-readobj failed for $python3Dll" }

$exportNames = @(
    $exports |
        ForEach-Object {
            if ($_ -match "^\s*Name:\s+(.+?)\s*$") { $Matches[1] }
        } |
        Where-Object { $_ } |
        Sort-Object -Unique
)
if ($exportNames.Count -lt 10) {
    throw "Unexpectedly few exports in python3.dll: $($exportNames.Count)"
}

$pythonLibDir = Join-Path $destination "lib\python"
New-Item -ItemType Directory -Force $pythonLibDir | Out-Null
$defPath = Join-Path $pythonLibDir "python3.def"
@("LIBRARY python3.dll", "EXPORTS") + $exportNames | Set-Content $defPath -Encoding Ascii

foreach ($libraryName in @(
    "libpython3.a",
    "libpython312.a",
    "libpython313.a",
    "libpython314.a"
)) {
    $libraryPath = Join-Path $pythonLibDir $libraryName
    & $dlltool -m i386:x86-64 -d $defPath -l $libraryPath -D python3.dll
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $libraryPath)) {
        throw "Failed to generate packaged Python import library: $libraryName"
    }
}

$clangVersion = (& $clang --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Packaged clang --version failed" }
$clangTarget = (& $clang -dumpmachine 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Packaged clang -dumpmachine failed" }
$lldVersion = (& $lld --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Packaged ld.lld --version failed" }

$metadata = [ordered]@{
    package = "fenics-jit-llvm-mingw"
    package_version = $version
    llvm_mingw_release = $version
    upstream_url = $upstreamUrl
    upstream_archive = $archiveName
    upstream_sha256 = $actualSha256
    target = "x86_64-w64-mingw32"
    clang_reported_target = $clangTarget
    crt = "UCRT"
    clang_version = $clangVersion
    lld_version = $lldVersion
    python_import_library_abi = "python3.dll"
    python_import_library_aliases = @("python3", "python312", "python313", "python314")
    minimization_stage = "stage-h"
    minimization_report = "minimization-stage-h.json"
    runtime_helper = "runtime/fenics_jit_runtime.py"
}
$metadata | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $destination "metadata.json") -Encoding UTF8

$payloadFiles = @(Get-ChildItem $destination -Recurse -File | Sort-Object FullName)
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
        throw "Phase 6 size gate failed: staged payload $payloadBytes bytes exceeds 50% ceiling $phase6GateBytes bytes"
    }
    $phase6GateStatus = "passed"
    Write-Host "Phase 6 size gate passed: staged payload $([math]::Round($payloadBytes / 1MB, 2)) MiB <= $([math]::Round($phase6GateBytes / 1MB, 2)) MiB"
}

$manifest = foreach ($file in $payloadFiles) {
    $relative = $file.FullName.Substring($destination.Length).TrimStart("\")
    [pscustomobject]@{
        path = $relative.Replace("\", "/")
        bytes = $file.Length
        sha256 = (Get-FileHash $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$manifest | ConvertTo-Csv -NoTypeInformation | Set-Content (Join-Path $destination "manifest.csv") -Encoding UTF8

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
$sizeLines | Set-Content (Join-Path $destination "size.txt") -Encoding Ascii

Write-Host "Staged fenics-jit-llvm-mingw $version"
Write-Host "  root: $destination"
Write-Host "  files: $($payloadFiles.Count)"
Write-Host "  payload MiB: $([math]::Round($payloadBytes / 1MB, 2))"
Write-Host "  target: $clangTarget"
