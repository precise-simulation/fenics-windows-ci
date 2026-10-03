param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path (Split-Path $PSScriptRoot)
$output = Join-Path $root "output"
$logRoot = Join-Path $root "build-logs\micro-clang-default-standalone"
$prefix = Join-Path $env:RUNNER_TEMP "default micro clang standalone prefix with spaces"
$bundleOutput = Join-Path $env:RUNNER_TEMP "default micro clang standalone output with spaces"
Remove-Item -Recurse -Force $prefix, $bundleOutput, $logRoot -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $logRoot | Out-Null

$channels = @()
if (Test-Path "$output/win-64/repodata.json") {
    $channels += "file:///$($output -replace '\\','/')"
}
$channels += "precise-simulation", "conda-forge"
$args = @("create", "-y", "-p", $prefix, "--override-channels", "--strict-channel-priority")
foreach ($channel in $channels) { $args += @("-c", $channel) }
$args += @(
    "python=3.12.*",
    "libblas=*=*openblas",
    "fenics-dolfinx",
    "pefile",
    "nuitka=4.1.3",
    "ordered-set",
    "zstandard",
    "c-compiler"
)
& micromamba @args | Out-Host
if ($LASTEXITCODE -ne 0) { throw "default standalone environment installation failed" }

$packages = (& micromamba list -p $prefix --json | ConvertFrom-Json)
$micro = @($packages | Where-Object { $_.name -eq "fenics-jit-micro-clang" })
if ($micro.Count -ne 1) { throw "normal standalone environment does not contain exactly one micro-Clang package" }
if ([string]$micro[0].version -ne "20260826" -or [string]$micro[0].build_string -ne "h9490d1a_1") {
    throw "standalone environment did not select the qualified Full-LTO package: $($micro | ConvertTo-Json -Compress)"
}
foreach ($forbidden in @("fenics-jit-llvm-mingw", "fenics-jit-tinycc")) {
    if (@($packages | Where-Object { $_.name -eq $forbidden }).Count) {
        throw "normal standalone environment unexpectedly contains $forbidden"
    }
}

./scripts/fenicsx-nuitka.ps1 `
    -EntryPoint "scripts/micro-clang-jit/phase6-standalone.py" `
    -OutputDir $bundleOutput `
    -ExistingPrefix $prefix `
    -JitBackend micro-clang

$dist = Get-ChildItem -LiteralPath $bundleOutput -Directory -Filter "*.dist" |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "fenicsx.exe") } |
    Select-Object -First 1
if (-not $dist) { throw "default micro-Clang standalone distribution not found" }

$jit = Join-Path $dist.FullName "fenics-jit"
foreach ($forbidden in @("llvm-mingw", "tinycc")) {
    if (Test-Path -LiteralPath (Join-Path $jit "backends/$forbidden")) {
        throw "$forbidden was staged into the default micro-Clang-only bundle"
    }
}

$hidden = "$prefix-hidden"
if (Test-Path -LiteralPath $hidden) { Remove-Item -Recurse -Force $hidden }
Move-Item -LiteralPath $prefix -Destination $hidden
try {
    $env:FENICS_PHASE6_BUNDLE_ROOT = $dist.FullName
    $env:FENICS_PHASE6_ORIGINAL_PREFIX = $prefix
    $env:FENICS_JIT_ROOT = $jit
    $env:FENICS_JIT_FFCX_INCLUDE = Join-Path $dist.FullName "ffcx/codegeneration"
    $env:FENICS_JIT_VERBOSE = "1"
    Remove-Item Env:FENICS_JIT_COMPILER -ErrorAction SilentlyContinue

    foreach ($name in @(
        "CC","CXX","CPP","LD","LDSHARED","INCLUDE","LIB","LIBPATH","LIBRARY_PATH",
        "CPATH","C_INCLUDE_PATH","CPLUS_INCLUDE_PATH","COMPILER_PATH","GCC_EXEC_PREFIX",
        "VSINSTALLDIR","VCINSTALLDIR","VCToolsInstallDir","WindowsSdkDir",
        "WindowsSDKVersion","UniversalCRTSdkDir","UCRTVersion","DISTUTILS_USE_SDK","MSSdk"
    )) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
    Get-ChildItem Env: |
        Where-Object { $_.Name -like "VSCMD_*" } |
        ForEach-Object { Remove-Item "Env:$($_.Name)" -ErrorAction SilentlyContinue }

    $env:PATH = "$($dist.FullName);$env:SystemRoot\System32;$env:SystemRoot"
    $exe = Join-Path $dist.FullName "fenicsx.exe"
    & $exe --expect-default `
        --work-dir (Join-Path $logRoot "serial work with spaces") `
        --output (Join-Path $logRoot "standalone-summary.json")
    if ($LASTEXITCODE -ne 0) { throw "default standalone serial proof failed" }

    $mpiexec = Join-Path $dist.FullName "mpiexec.exe"
    & $mpiexec -localonly -n 2 `
        -env PATH $env:PATH `
        -env FENICS_PHASE6_BUNDLE_ROOT $dist.FullName `
        -env FENICS_PHASE6_ORIGINAL_PREFIX $prefix `
        -env FENICS_JIT_ROOT $jit `
        -env FENICS_JIT_FFCX_INCLUDE $env:FENICS_JIT_FFCX_INCLUDE `
        $exe --expect-default --mpi-child `
        --work-dir (Join-Path $logRoot "mpi work with spaces") `
        --output (Join-Path $logRoot "standalone-mpi-summary.json")
    if ($LASTEXITCODE -ne 0) { throw "default standalone MPI proof failed" }
}
finally {
    Move-Item -LiteralPath $hidden -Destination $prefix
}

Write-Host "Default micro-Clang standalone serial/MPI proof passed"
