param(
    [Parameter(Mandatory = $true)][string]$ToolchainRoot,
    [Parameter(Mandatory = $true)][string]$PythonPrefix,
    [Parameter(Mandatory = $true)][string]$BuildEvidenceDir,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][string]$EvidenceDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$sourceRoot = [IO.Path]::GetFullPath($ToolchainRoot)
$pythonPrefixPath = [IO.Path]::GetFullPath($PythonPrefix)
$buildEvidence = [IO.Path]::GetFullPath($BuildEvidenceDir)
$output = [IO.Path]::GetFullPath($OutputRoot)
$evidence = [IO.Path]::GetFullPath($EvidenceDir)
$backend = Join-Path $output "Library\fenics-jit\backends\micro-clang"

if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
    throw "Phase-1 source toolchain root is missing: $sourceRoot"
}
if (-not (Test-Path -LiteralPath $buildEvidence -PathType Container)) {
    throw "Phase-1 build evidence directory is missing: $buildEvidence"
}

Remove-Item -Recurse -Force $output, $evidence -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $backend, $evidence | Out-Null

# Phase 2 is deliberately conservative: relocate the complete source-built
# Phase-1 payload under backend-specific package ownership before any Phase-4
# minimization. This makes the full compiler/sysroot footprint measurable.
Get-ChildItem -LiteralPath $sourceRoot -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $backend -Recurse -Force
}

foreach ($requiredLicense in @(
    "licenses\LLVM-LICENSE.TXT",
    "licenses\llvm-mingw-LICENSE.txt",
    "licenses\mingw-w64-COPYING"
)) {
    $path = Join-Path $backend $requiredLicense
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "required source license is missing from Phase-1 toolchain: $path"
    }
}

$runtimeHelper = Join-Path $repoRoot "recipes\fenics-jit-llvm-mingw\fenics_jit_runtime.py"
if (-not (Test-Path -LiteralPath $runtimeHelper -PathType Leaf)) {
    throw "qualified private runtime helper is missing: $runtimeHelper"
}
Copy-Item -LiteralPath $runtimeHelper -Destination (Join-Path $backend "fenics_jit_runtime.py") -Force

$readobj = Join-Path $backend "bin\llvm-readobj.exe"
$dlltool = Join-Path $backend "bin\llvm-dlltool.exe"
$clang = Join-Path $backend "bin\x86_64-w64-mingw32-clang.exe"
$lld = Join-Path $backend "bin\ld.lld.exe"
foreach ($tool in @($readobj, $dlltool, $clang, $lld)) {
    if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) {
        throw "required packaged tool is missing: $tool"
    }
}

$pythonCandidates = @(
    (Join-Path $pythonPrefixPath "python3.dll"),
    (Join-Path $pythonPrefixPath "DLLs\python3.dll"),
    (Join-Path $pythonPrefixPath "Library\bin\python3.dll")
)
$python3Dll = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $python3Dll) {
    throw "python3.dll not found below Phase-2 build Python prefix: $pythonPrefixPath"
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
    throw "unexpectedly few python3.dll exports: $($exportNames.Count)"
}

$pythonLibDir = Join-Path $backend "lib\python"
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
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $libraryPath -PathType Leaf)) {
        throw "failed to generate packaged Python import library: $libraryName"
    }
}

$provenanceDir = Join-Path $backend "provenance"
New-Item -ItemType Directory -Force $provenanceDir | Out-Null
foreach ($name in @(
    "build-provenance.json",
    "retained-manifest.json",
    "llvm-mingw-local-build.patch",
    "llvm-cmake-cache.txt",
    "clang-version.txt",
    "lld-version.txt",
    "target.txt",
    "driver-defaults.txt",
    "archive-wrapper-preflight.txt",
    "mingw-header-smoke.txt"
)) {
    $source = Join-Path $buildEvidence $name
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $provenanceDir $name) -Force
    }
}

$provenancePath = Join-Path $provenanceDir "build-provenance.json"
if (-not (Test-Path -LiteralPath $provenancePath -PathType Leaf)) {
    throw "Phase-1 build provenance was not retained: $provenancePath"
}
$provenance = Get-Content -LiteralPath $provenancePath -Raw | ConvertFrom-Json

$clangVersion = (& $clang --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "packaged clang --version failed" }
$clangTarget = (& $clang -dumpmachine 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "packaged clang -dumpmachine failed" }
$lldVersion = (& $lld --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "packaged ld.lld --version failed" }

$metadata = [ordered]@{
    schema = "fenics-jit-micro-clang-package-v1"
    package = "fenics-jit-micro-clang"
    phase = 2
    package_role = "conservative-private-qualification"
    production_selector_integrated = $false
    default_backend_changed = $false
    llvm_mingw_release = [string]$provenance.llvm_mingw_release
    llvm_mingw_commit = [string]$provenance.llvm_mingw_commit
    llvm_commit = [string]$provenance.llvm_commit
    compiler_rt_commit = [string]$provenance.compiler_rt_commit
    mingw_w64_commit = [string]$provenance.mingw_w64_commit
    local_build_patches = $provenance.local_build_patches
    llvm_cmake_flags = [string]$provenance.llvm_cmake_flags
    target = $clangTarget
    crt = "UCRT"
    clang_version = $clangVersion
    lld_version = $lldVersion
    python_import_library_abi = "python3.dll"
    python_import_library_aliases = @("python3", "python312", "python313", "python314")
    runtime_helper = "fenics_jit_runtime.py"
    runtime_helper_policy = "private Phase-2 proof only; production shared selector unchanged"
    source_build_provenance = "provenance/build-provenance.json"
    source_build_manifest = "provenance/retained-manifest.json"
}
$metadataPath = Join-Path $backend "metadata.json"
[IO.File]::WriteAllText(
    $metadataPath,
    ($metadata | ConvertTo-Json -Depth 10) + [Environment]::NewLine,
    (New-Object Text.UTF8Encoding($false))
)

$payloadFiles = @(Get-ChildItem -LiteralPath $backend -Recurse -File | Sort-Object FullName)
$payloadBytes = ($payloadFiles | Measure-Object Length -Sum).Sum
if ($null -eq $payloadBytes) { $payloadBytes = 0 }
$payloadBytes = [int64]$payloadBytes

$manifest = foreach ($file in $payloadFiles) {
    $relative = $file.FullName.Substring($backend.Length).TrimStart("\")
    [pscustomobject]@{
        path = $relative.Replace("\", "/")
        bytes = $file.Length
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$manifestPath = Join-Path $backend "manifest.csv"
$manifest | ConvertTo-Csv -NoTypeInformation | Set-Content $manifestPath -Encoding UTF8

$sizeLines = @(
    "payload_file_count=$($payloadFiles.Count)"
    "payload_bytes=$payloadBytes"
    "payload_mib=$([math]::Round($payloadBytes / 1MB, 4))"
    "stage_aw_reference_mib=215.19"
    "phase4_early_continuation_gate_mib=108.2"
    "phase4_size_gate_status=not-evaluated-in-phase2"
)
$sizePath = Join-Path $backend "size.txt"
$sizeLines | Set-Content $sizePath -Encoding Ascii

Copy-Item -LiteralPath $metadataPath, $manifestPath, $sizePath -Destination $evidence -Force
$summary = [ordered]@{
    schema = "fenics-jit-micro-clang-phase2-package-summary-v1"
    status = "packaged"
    backend_root = $backend
    payload_file_count = $payloadFiles.Count
    payload_bytes = $payloadBytes
    payload_mib = [math]::Round($payloadBytes / 1MB, 4)
    production_selector_integrated = $false
    phase4_size_gate_evaluated = $false
}
[IO.File]::WriteAllText(
    (Join-Path $evidence "phase2-package-summary.json"),
    ($summary | ConvertTo-Json -Depth 5) + [Environment]::NewLine,
    (New-Object Text.UTF8Encoding($false))
)

Write-Host "Conservative micro-Clang Phase-2 package staged"
Write-Host "  backend root: $backend"
Write-Host "  files: $($payloadFiles.Count)"
Write-Host "  payload MiB: $([math]::Round($payloadBytes / 1MB, 4))"
Write-Host "  target: $clangTarget"
