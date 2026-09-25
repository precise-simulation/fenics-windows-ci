param(
    [string]$WorkDir = "micro-clang-work",
    [string]$StageDir = "micro-clang-stage",
    [string]$DiagnosticsDir = "micro-clang-diagnostics/build"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$reference = Get-Content (Join-Path $PSScriptRoot "reference.json") -Raw | ConvertFrom-Json
$work = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $WorkDir))
$stage = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $StageDir))
$diagnostics = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $DiagnosticsDir))
Remove-Item -Recurse -Force $work, $stage, $diagnostics -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $work, $stage, $diagnostics | Out-Null

$source = Join-Path $work "llvm-project"
$buildDir = Join-Path $work "llvm-build"
$llvmCommit = [string]$reference.source_identity.llvm_project_commit

& git init $source
if ($LASTEXITCODE -ne 0) { throw "git init failed" }
& git -C $source remote add origin https://github.com/llvm/llvm-project.git
if ($LASTEXITCODE -ne 0) { throw "git remote add failed" }
& git -C $source fetch --depth 1 origin $llvmCommit
if ($LASTEXITCODE -ne 0) { throw "LLVM source fetch failed" }
& git -C $source checkout --detach FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw "LLVM source checkout failed" }

$actualCommit = (& git -C $source rev-parse HEAD).Trim()
if ($actualCommit -ne $llvmCommit) { throw "LLVM source identity mismatch: expected $llvmCommit, got $actualCommit" }
$sourceTree = (& git -C $source rev-parse "HEAD^{tree}").Trim()

$vswhere = Join-Path \${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) { throw "vswhere.exe not found" }
$vsInstall = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1).Trim()
if (-not $vsInstall) { throw "Visual Studio C++ build tools not found" }
$devShell = Join-Path $vsInstall "Common7\Tools\Launch-VsDevShell.ps1"
if (-not (Test-Path $devShell)) { throw "Visual Studio developer shell not found: $devShell" }
& $devShell -Arch amd64 -HostArch amd64
if ($LASTEXITCODE -ne 0) { throw "Visual Studio developer shell activation failed" }

$cl = (Get-Command cl.exe -ErrorAction Stop).Source
$cmake = (Get-Command cmake.exe -ErrorAction Stop).Source
$ninja = (Get-Command ninja.exe -ErrorAction Stop).Source
$clVersion = (& $cl 2>&1 | Select-Object -First 1 | Out-String).Trim()
$cmakeVersion = (& $cmake --version | Select-Object -First 1 | Out-String).Trim()
$ninjaVersion = (& $ninja --version | Out-String).Trim()

$cmakeArgs = @(
    "-S", (Join-Path $source "llvm"),
    "-B", $buildDir,
    "-G", "Ninja",
    "-DCMAKE_BUILD_TYPE=Release",
    "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded",
    "-DLLVM_ENABLE_PROJECTS=clang;lld",
    "-DLLVM_TARGETS_TO_BUILD=X86",
    "-DLLVM_DEFAULT_TARGET_TRIPLE=x86_64-w64-windows-gnu",
    "-DLLVM_ENABLE_ASSERTIONS=OFF",
    "-DLLVM_ENABLE_BINDINGS=OFF",
    "-DLLVM_INCLUDE_TESTS=OFF",
    "-DLLVM_INCLUDE_EXAMPLES=OFF",
    "-DLLVM_INCLUDE_BENCHMARKS=OFF",
    "-DLLVM_INCLUDE_DOCS=OFF",
    "-DLLVM_BUILD_EXAMPLES=OFF",
    "-DLLVM_BUILD_TESTS=OFF",
    "-DLLVM_BUILD_BENCHMARKS=OFF",
    "-DLLVM_LINK_LLVM_DYLIB=OFF",
    "-DLLVM_BUILD_LLVM_DYLIB=OFF",
    "-DCLANG_LINK_CLANG_DYLIB=OFF",
    "-DCLANG_INCLUDE_TESTS=OFF",
    "-DLLD_INCLUDE_TESTS=OFF",
    "-DLLVM_ENABLE_ZLIB=OFF",
    "-DLLVM_ENABLE_ZSTD=OFF",
    "-DLLVM_ENABLE_LIBXML2=OFF",
    "-DLLVM_ENABLE_TERMINFO=OFF",
    "-DLLVM_ENABLE_RTTI=OFF"
)
& $cmake @cmakeArgs
if ($LASTEXITCODE -ne 0) { throw "micro-Clang CMake configure failed" }
& $cmake --build $buildDir --target clang lld llvm-dlltool llvm-readobj -- -j2
if ($LASTEXITCODE -ne 0) { throw "micro-Clang source build failed" }

$builtBin = Join-Path $buildDir "bin"
foreach ($name in @("clang.exe", "ld.lld.exe", "llvm-dlltool.exe", "llvm-readobj.exe")) {
    $path = Join-Path $builtBin $name
    if (-not (Test-Path $path)) { throw "Required source-built host tool missing: $path" }
}

$archivePath = Join-Path $work ([string]$reference.upstream_archive.name)
Invoke-WebRequest -Uri ([string]$reference.upstream_archive.url) -OutFile $archivePath
$archiveSha = (Get-FileHash $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($archiveSha -ne ([string]$reference.upstream_archive.sha256).ToLowerInvariant()) { throw "Reference archive checksum mismatch: $archiveSha" }

$referenceExtract = Join-Path $work "reference-extract"
Expand-Archive -LiteralPath $archivePath -DestinationPath $referenceExtract
$referenceRootItem = Get-ChildItem $referenceExtract -Directory | Select-Object -First 1
if (-not $referenceRootItem) { throw "Could not identify extracted LLVM-MinGW reference root" }
$referenceRoot = $referenceRootItem.FullName

$bin = Join-Path $stage "bin"
New-Item -ItemType Directory -Force $bin | Out-Null
Copy-Item (Join-Path $builtBin "clang.exe") (Join-Path $bin "clang-23.exe")
Copy-Item (Join-Path $builtBin "ld.lld.exe") (Join-Path $bin "ld.lld.exe")
Copy-Item (Join-Path $builtBin "llvm-dlltool.exe") (Join-Path $bin "llvm-dlltool.exe")
Copy-Item (Join-Path $builtBin "llvm-readobj.exe") (Join-Path $bin "llvm-readobj.exe")
foreach ($name in @("x86_64-w64-mingw32-clang.exe", "mingw32-common.cfg", "x86_64-w64-windows-gnu.cfg")) {
    $src = Join-Path (Join-Path $referenceRoot "bin") $name
    if (-not (Test-Path $src)) { throw "Reference target launcher/config missing: $src" }
    Copy-Item $src (Join-Path $bin $name)
}

# Phase 1 holds the target side constant. Phase 2 will construct/package the
# conservative sysroot from the same exact source revisions.
foreach ($relative in @("include", "x86_64-w64-mingw32")) {
    $src = Join-Path $referenceRoot $relative
    if (-not (Test-Path $src)) { throw "Reference target tree missing: $src" }
    Copy-Item -Recurse $src (Join-Path $stage $relative)
}
$resourceRoot = Join-Path $referenceRoot "lib\clang"
$resourceDirs = @(Get-ChildItem $resourceRoot -Directory)
if ($resourceDirs.Count -ne 1) { throw "Expected one Clang resource version, found $($resourceDirs.Count)" }
$stageResourceParent = Join-Path $stage "lib\clang"
New-Item -ItemType Directory -Force $stageResourceParent | Out-Null
Copy-Item -Recurse $resourceDirs[0].FullName (Join-Path $stageResourceParent $resourceDirs[0].Name)

$runtimeDir = Join-Path $stage "runtime"
New-Item -ItemType Directory -Force $runtimeDir | Out-Null
Copy-Item (Join-Path $repoRoot "recipes\fenics-jit-llvm-mingw\fenics_jit_runtime.py") (Join-Path $runtimeDir "fenics_jit_runtime.py")
$licenseDir = Join-Path $stage "licenses"
New-Item -ItemType Directory -Force $licenseDir | Out-Null
Copy-Item (Join-Path $source "llvm\LICENSE.TXT") (Join-Path $licenseDir "LLVM-LICENSE.TXT")
if (Test-Path (Join-Path $referenceRoot "LICENSE.TXT")) { Copy-Item (Join-Path $referenceRoot "LICENSE.TXT") (Join-Path $licenseDir "llvm-mingw-LICENSE.TXT") }

$clang = Join-Path $bin "x86_64-w64-mingw32-clang.exe"
$clangVersion = (& $clang --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "staged micro-Clang --version failed" }
$clangTarget = (& $clang -dumpmachine 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "staged micro-Clang -dumpmachine failed" }
if ($clangTarget -notmatch "(?i)^x86_64-w64-(mingw32|windows-gnu)$") { throw "micro-Clang target drifted away from MinGW x86-64: $clangTarget" }

foreach ($name in @("libLLVM-23.dll", "libclang-cpp.dll", "libc++.dll", "libunwind.dll", "libwinpthread-1.dll")) {
    if (Test-Path (Join-Path $bin $name)) { throw "Source-built host unexpectedly staged shared compiler runtime: $name" }
}

Copy-Item (Join-Path $buildDir "CMakeCache.txt") (Join-Path $diagnostics "CMakeCache.txt")
$metadata = [ordered]@{
    schema = "fenics-micro-clang-phase1-build-v1"
    llvm_project_commit = $actualCommit
    llvm_project_tree = $sourceTree
    compiler_rt_commit = [string]$reference.source_identity.compiler_rt_commit
    mingw_w64_commit = [string]$reference.source_identity.mingw_w64_commit
    llvm_mingw_commit = [string]$reference.source_identity.llvm_mingw_commit
    reference_archive_sha256 = $archiveSha
    target = $clangTarget
    crt = "UCRT"
    source_build = [ordered]@{
        projects = @("clang", "lld")
        llvm_targets = @("X86")
        llvm_link_dylib = $false
        clang_link_dylib = $false
        msvc_runtime = "MultiThreaded"
        cmake_arguments = $cmakeArgs
    }
    bootstrap = [ordered]@{
        cl = $clVersion
        cmake = $cmakeVersion
        ninja = $ninjaVersion
        vs_install = $vsInstall
    }
    staged_clang_version = $clangVersion
    target_sysroot_control = "immutable llvm-mingw 20260826 x86_64 UCRT archive"
    target_wrapper_control = "immutable llvm-mingw 20260826 x86_64 target launcher"
}
$metadata | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $stage "phase1-metadata.json") -Encoding UTF8
$metadata | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $diagnostics "phase1-metadata.json") -Encoding UTF8

$files = @(Get-ChildItem $stage -Recurse -File | Sort-Object FullName)
$manifest = foreach ($file in $files) {
    [ordered]@{
        path = $file.FullName.Substring($stage.Length).TrimStart("\").Replace("\", "/")
        bytes = [int64]$file.Length
        sha256 = (Get-FileHash $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $stage "manifest.json") -Encoding UTF8
$payloadBytes = [int64](($files | Measure-Object Length -Sum).Sum)
[ordered]@{
    payload_bytes = $payloadBytes
    payload_mib = $payloadBytes / 1MB
    file_count = $files.Count
    stage_aw_installed_mib = [double]$reference.stage_aw.installed_package_mib
    ratio_to_stage_aw = ($payloadBytes / 1MB) / [double]$reference.stage_aw.installed_package_mib
} | ConvertTo-Json | Set-Content (Join-Path $diagnostics "phase1-size.json") -Encoding UTF8

Write-Host "Phase-1 source-built micro-Clang staged at $stage"
Write-Host "  LLVM commit: $actualCommit"
Write-Host "  target: $clangTarget"
Write-Host "  payload: $([math]::Round($payloadBytes / 1MB, 2)) MiB"
