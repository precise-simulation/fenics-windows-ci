param(
    [Parameter(Mandatory = $true)]
    [string]$PythonPrefix,

    [Parameter(Mandatory = $true)]
    [string]$ToolchainRoot,

    [string]$WorkDir = "jit-work",
    [string]$DiagnosticsDir = "jit-diagnostics/proof"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$pythonPrefixPath = [System.IO.Path]::GetFullPath($PythonPrefix)
$toolchainRootPath = [System.IO.Path]::GetFullPath($ToolchainRoot)
$workPath = [System.IO.Path]::GetFullPath($WorkDir)
$diagnosticsPath = [System.IO.Path]::GetFullPath($DiagnosticsDir)
$jitBin = Join-Path $toolchainRootPath "bin"
$python = Join-Path $pythonPrefixPath "python.exe"
$clang = Join-Path $jitBin "x86_64-w64-mingw32-clang.exe"
$clangxx = Join-Path $jitBin "x86_64-w64-mingw32-clang++.exe"
$dlltool = Join-Path $jitBin "llvm-dlltool.exe"
$readobj = Join-Path $jitBin "llvm-readobj.exe"

foreach ($path in @($python, $clang, $clangxx, $dlltool, $readobj)) {
    if (-not (Test-Path $path)) {
        throw "Required executable missing: $path"
    }
}

Remove-Item -Recurse -Force $workPath -ErrorAction Ignore
New-Item -ItemType Directory -Force $workPath, $diagnosticsPath | Out-Null

# The GitHub runner has Visual Studio and Windows SDKs installed. Replace,
# rather than extend, PATH and clear activation state before the JIT process.
$systemRoot = $env:SystemRoot
$env:PATH = @(
    $jitBin,
    $pythonPrefixPath,
    (Join-Path $pythonPrefixPath "Library/bin"),
    (Join-Path $pythonPrefixPath "Scripts"),
    (Join-Path $systemRoot "System32"),
    $systemRoot
) -join ";"

$remove = @(
    "VSINSTALLDIR", "VCINSTALLDIR", "VCToolsInstallDir",
    "INCLUDE", "LIB", "LIBPATH",
    "WindowsSdkDir", "WindowsSDKVersion",
    "UniversalCRTSdkDir", "UCRTVersion",
    "DISTUTILS_USE_SDK", "MSSdk",
    "CC", "CXX", "CPP", "LD", "LDSHARED"
)
foreach ($name in $remove) {
    Remove-Item "Env:$name" -ErrorAction Ignore
}
Get-ChildItem Env: |
    Where-Object Name -Like "VSCMD_*" |
    ForEach-Object { Remove-Item "Env:$($_.Name)" -ErrorAction Ignore }

$env:CC = $clang
$env:CXX = $clangxx
$env:SETUPTOOLS_USE_DISTUTILS = "local"

$forbiddenCommands = @("cl.exe", "link.exe", "vswhere.exe", "vcvarsall.bat")
foreach ($command in $forbiddenCommands) {
    $resolved = Get-Command $command -ErrorAction SilentlyContinue
    if ($resolved) {
        throw "Forbidden host tool is resolvable in sanitized JIT PATH: $command -> $($resolved.Source)"
    }
}

@(
    "PATH=$env:PATH"
    "CC=$env:CC"
    "CXX=$env:CXX"
    "python=$python"
    "toolchain_root=$toolchainRootPath"
) | Set-Content (Join-Path $diagnosticsPath "environment.txt")

& $python -c "import sys,sysconfig; print(sys.version); print('prefix=' + sys.prefix); print('include=' + sysconfig.get_path('include')); print('ext_suffix=' + str(sysconfig.get_config_var('EXT_SUFFIX')))" 2>&1 |
    Set-Content (Join-Path $diagnosticsPath "python-runtime.txt")
if ($LASTEXITCODE -ne 0) { throw "Python runtime diagnostics failed" }

& $clang --version 2>&1 | Set-Content (Join-Path $diagnosticsPath "clang-version.txt")
if ($LASTEXITCODE -ne 0) { throw "clang --version failed" }

& $clang -dumpmachine 2>&1 | Set-Content (Join-Path $diagnosticsPath "clang-target.txt")
if ($LASTEXITCODE -ne 0) { throw "clang -dumpmachine failed" }

& $clang -print-search-dirs 2>&1 | Set-Content (Join-Path $diagnosticsPath "clang-search-dirs.txt")
if ($LASTEXITCODE -ne 0) { throw "clang -print-search-dirs failed" }

$probeC = Join-Path $workPath "driver-probe.c"
"int probe(void) { return 0; }" | Set-Content $probeC -Encoding ascii
& $clang -v -E -x c $probeC -o NUL 2>&1 | Set-Content (Join-Path $diagnosticsPath "clang-include-search.txt")
if ($LASTEXITCODE -ne 0) { throw "clang include-search probe failed" }

& $clang -### -shared $probeC -o (Join-Path $workPath "driver-probe.dll") 2>&1 |
    Set-Content (Join-Path $diagnosticsPath "clang-link-plan.txt")
if ($LASTEXITCODE -ne 0) { throw "clang linker-plan probe failed" }

$linkPlan = Get-Content (Join-Path $diagnosticsPath "clang-link-plan.txt") -Raw
if ($linkPlan -notmatch "(?i)(ld\.lld|lld-link)") {
    throw "LLVM-MinGW clang link plan did not select LLD"
}

$python3Candidates = @(
    (Join-Path $pythonPrefixPath "python3.dll"),
    (Join-Path $pythonPrefixPath "DLLs/python3.dll"),
    (Join-Path $pythonPrefixPath "Library/bin/python3.dll")
)
$python3Dll = $python3Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python3Dll) {
    throw "Could not locate CPython stable-ABI python3.dll below $pythonPrefixPath"
}

$importLibDir = Join-Path $workPath "python-import-lib"
New-Item -ItemType Directory -Force $importLibDir | Out-Null

$exports = & $readobj --coff-exports $python3Dll 2>&1
if ($LASTEXITCODE -ne 0) { throw "llvm-readobj failed while reading python3.dll exports" }
$exports | Set-Content (Join-Path $diagnosticsPath "python3-exports.txt")

$exportNames = @(
    $exports |
        ForEach-Object {
            if ($_ -match "^\s*Name:\s+(.+?)\s*$") { $Matches[1] }
        } |
        Where-Object { $_ } |
        Sort-Object -Unique
)
if ($exportNames.Count -lt 10) {
    throw "Unexpectedly few exports found in python3.dll: $($exportNames.Count)"
}

$defPath = Join-Path $importLibDir "python3.def"
@("LIBRARY python3.dll", "EXPORTS") + $exportNames |
    Set-Content $defPath -Encoding ascii

$versionTag = & $python -c "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) { throw "Failed to determine Python version tag" }
$versionTag = $versionTag.Trim()

foreach ($libraryName in @("libpython3.a", "libpython$versionTag.a")) {
    $libraryPath = Join-Path $importLibDir $libraryName
    & $dlltool -m i386:x86-64 -d $defPath -l $libraryPath -D python3.dll 2>&1 |
        Add-Content (Join-Path $diagnosticsPath "dlltool.txt")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $libraryPath)) {
        throw "Failed to create GNU import library: $libraryName"
    }
}

$env:JIT_PYTHON_LIB_DIR = $importLibDir
$proofScript = Join-Path $PSScriptRoot "minimal-cffi-proof.py"
$proofLog = Join-Path $diagnosticsPath "cffi-build.txt"

& $python $proofScript --work-dir $workPath --diagnostics-dir $diagnosticsPath --python-lib-dir $importLibDir 2>&1 |
    Tee-Object -FilePath $proofLog
if ($LASTEXITCODE -ne 0) {
    throw "Minimal CFFI proof failed"
}

$pydPath = (Get-Content (Join-Path $diagnosticsPath "pyd-path.txt") -Raw).Trim()
if (-not (Test-Path $pydPath)) {
    throw "CFFI proof did not produce the recorded .pyd: $pydPath"
}

$importsPath = Join-Path $diagnosticsPath "pyd-imports.txt"
& $readobj --coff-imports $pydPath 2>&1 | Set-Content $importsPath
if ($LASTEXITCODE -ne 0) { throw "llvm-readobj failed while inspecting CFFI .pyd" }

$imports = Get-Content $importsPath -Raw
if ($imports -notmatch "(?i)python3\.dll") {
    throw "CFFI .pyd does not import python3.dll"
}
if ($imports -match "(?i)python3\d{2}t?(?:_d)?\.dll") {
    throw "CFFI .pyd unexpectedly imports a version-specific Python DLL"
}

$backend = (Get-Content (Join-Path $diagnosticsPath "setuptools-compiler.txt") -Raw).Trim()
if ($backend -ne "mingw32") {
    throw "Expected setuptools compiler backend mingw32, got '$backend'"
}

$buildLog = Get-Content $proofLog -Raw
if ($buildLog -notmatch [regex]::Escape("x86_64-w64-mingw32-clang.exe")) {
    throw "CFFI build log does not show LLVM-MinGW clang"
}
if ($buildLog -notmatch [regex]::Escape("-std=c17")) {
    throw "CFFI build log does not show GNU-driver-compatible C17 flag"
}

$diagnosticText = @(
    Get-Content (Join-Path $diagnosticsPath "clang-search-dirs.txt") -Raw
    Get-Content (Join-Path $diagnosticsPath "clang-include-search.txt") -Raw
    Get-Content (Join-Path $diagnosticsPath "clang-link-plan.txt") -Raw
    $buildLog
) -join "`n"

$forbiddenPathPatterns = @(
    "(?i)\\Microsoft Visual Studio\\",
    "(?i)\\Windows Kits\\"
)
foreach ($pattern in $forbiddenPathPatterns) {
    if ($diagnosticText -match $pattern) {
        throw "Host Visual Studio/Windows SDK path leaked into JIT diagnostics: $($Matches[0])"
    }
}

Write-Host "LLVM-MinGW CFFI proof passed: $pydPath"
