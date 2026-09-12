$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$revision = "0fb54300b56512754221d80adda85ddb9815bceb"
$backendCacheId = "tinycc-0fb54300b565-aaa86e30769a96f90b37"
$sourceBase = if ($env:SRC_DIR) { $env:SRC_DIR } else { Join-Path $env:TEMP "fenics-jit-tinycc-build" }
$source = Join-Path $sourceBase "tinycc-source"
$stage = Join-Path $sourceBase "tinycc-stage"
$backend = Join-Path $env:PREFIX "Library/fenics-jit/backends/tinycc"

Remove-Item -Recurse -Force $source, $stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $source, $stage, $backend | Out-Null

Write-Host "Fetching pinned TinyCC revision $revision"
git -C $source init
if ($LASTEXITCODE -ne 0) { throw "git init failed" }
git -C $source remote add origin https://github.com/TinyCC/tinycc.git
if ($LASTEXITCODE -ne 0) { throw "git remote add failed" }
git -C $source fetch --depth 1 origin $revision
if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }
git -C $source checkout --detach FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw "git checkout failed" }
$actualRevision = (git -C $source rev-parse HEAD).Trim()
if ($actualRevision -ne $revision) { throw "TinyCC revision mismatch: $actualRevision" }

$buildScript = Join-Path $source "win32/build-tcc.bat"
$upstreamBuildHash = (Get-FileHash -Algorithm SHA256 $buildScript).Hash.ToLowerInvariant()
$buildText = [IO.File]::ReadAllText($buildScript)
$oldLine = '%CMD% -O2 -W2 -Zi -MT -GS- -nologo %DEF_GITHASH% -link -opt:ref,icf'
$newLine = '%CMD% -O2 -W2 -MT -GS- -nologo "-pathmap:%TCC_SOURCE_ROOT%=tinycc" %DEF_GITHASH% -link -Brepro -opt:ref,icf'
if (-not $buildText.Contains($oldLine)) { throw "expected TinyCC MSVC bootstrap line not found" }
$buildText = $buildText.Replace($oldLine, $newLine)
[IO.File]::WriteAllText($buildScript, $buildText, [Text.Encoding]::ASCII)
$patchedBuildHash = (Get-FileHash -Algorithm SHA256 $buildScript).Hash.ToLowerInvariant()

$cl = Get-Command cl.exe -ErrorAction Stop
$clOutput = (cmd.exe /d /c "`"$($cl.Source)`" 2>&1" | Out-String)
$clVersion = (($clOutput -split "`r?`n" | Where-Object { $_ -match "Compiler Version" } | Select-Object -First 1) -as [string]).Trim()
if (-not $clVersion) { throw "could not capture activated MSVC compiler version" }

$previousSourceRoot = $env:TCC_SOURCE_ROOT
$env:TCC_SOURCE_ROOT = $source
Push-Location (Join-Path $source "win32")
try {
    cmd.exe /d /s /c "call build-tcc.bat -c cl -t x86_64 -i `"$stage`""
    if ($LASTEXITCODE -ne 0) { throw "TinyCC bootstrap failed" }
} finally {
    Pop-Location
    $env:TCC_SOURCE_ROOT = $previousSourceRoot
}

# Bounds-checking support is debug tooling and is not used by the qualified
# direct source-to-PYD FFCx path. The objects also embed their build directory,
# so do not ship them in the minimal runtime backend payload.
Remove-Item -Force (Join-Path $stage "lib/bcheck.o"), (Join-Path $stage "lib/bcheck_run.o") -ErrorAction SilentlyContinue

foreach ($name in @("tcc.exe", "libtcc.dll")) {
    $path = Join-Path $stage $name
    if (-not (Test-Path $path)) { throw "TinyCC bootstrap did not produce $path" }
    Copy-Item $path (Join-Path $backend $name) -Force
}
Copy-Item (Join-Path $stage "include") (Join-Path $backend "include") -Recurse -Force
Copy-Item (Join-Path $stage "lib") (Join-Path $backend "lib") -Recurse -Force
Copy-Item (Join-Path $env:RECIPE_DIR "tinycc_adapter.py") (Join-Path $backend "tinycc_adapter.py") -Force
Copy-Item (Join-Path $env:RECIPE_DIR "selftest.py") (Join-Path $backend "selftest.py") -Force

$licenseDir = Join-Path $backend "licenses"
New-Item -ItemType Directory -Force $licenseDir | Out-Null
Copy-Item (Join-Path $source "COPYING") (Join-Path $licenseDir "TinyCC-COPYING") -Force

$pythonDll = @(
    (Join-Path $env:BUILD_PREFIX "python3.dll"),
    (Join-Path $env:BUILD_PREFIX "DLLs/python3.dll")
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $pythonDll) { throw "python3.dll not found in build prefix" }
$tcc = Join-Path $backend "tcc.exe"
& $tcc ("-B" + $backend) -impdef $pythonDll -o (Join-Path $backend "python3.def")
if ($LASTEXITCODE -ne 0) { throw "python3.def generation failed" }

$tccVersion = (& $tcc -v 2>&1 | Out-String).Trim()
$metadata = [ordered]@{
    schema = 1
    source_repository = "https://github.com/TinyCC/tinycc"
    source_revision = $revision
    upstream_build_script_sha256 = $upstreamBuildHash
    patched_build_script_sha256 = $patchedBuildHash
    local_build_patch = "build-tcc-msvc-repro-v2: remove -Zi, path-map source root, and add linker -Brepro"
    bootstrap_compiler = $clVersion
    bootstrap_contract = "rattler vs2022_win-64 19.44.* on GitHub windows-2022"
    runner_image = if ($env:ImageVersion) { $env:ImageVersion } else { "windows-2022" }
    tcc_version = $tccVersion
    tcc_sha256 = (Get-FileHash -Algorithm SHA256 (Join-Path $backend "tcc.exe")).Hash.ToLowerInvariant()
    libtcc_sha256 = (Get-FileHash -Algorithm SHA256 (Join-Path $backend "libtcc.dll")).Hash.ToLowerInvariant()
    adapter_sha256 = (Get-FileHash -Algorithm SHA256 (Join-Path $backend "tinycc_adapter.py")).Hash.ToLowerInvariant()
    backend_cache_id = $backendCacheId
    qualified_dependencies = [ordered]@{ cffi = "2.1.*"; setuptools = "84.*"; python = ">=3.12,<3.15" }
    policy = [ordered]@{
        adapter_schema = "tinycc-cffi-adapter-v2"
        external_config = "suppress-all-v1"
        python_link = "stable-abi-python3-def-v1"
        pe_hardening = "dynamicbase-highentropyva-nxcompat-v1"
        crt = "msvcrt-owned-allocation-boundary-v1"
        abi = "mingw32-mswin64-msbitfields-longdouble8-v1"
        system_library = "windows-system-dll-resolution-v1"
    }
}
$json = $metadata | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText((Join-Path $backend "backend-metadata.json"), $json + "`n", (New-Object Text.UTF8Encoding($false)))
Get-Content (Join-Path $backend "backend-metadata.json")
