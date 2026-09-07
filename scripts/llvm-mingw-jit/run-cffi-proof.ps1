param(
    [Parameter(Mandatory = $true)]
    [string]$PythonPrefix,

    [Parameter(Mandatory = $true)]
    [string]$ToolchainRoot,

    [string]$WorkDir = "jit-work",
    [string]$DiagnosticsDir = "jit-diagnostics/proof",
    [string]$PoissonScript = ""
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
$readobj = Join-Path $jitBin "llvm-readobj.exe"
$runtimeHelper = Join-Path $toolchainRootPath "runtime\fenics_jit_runtime.py"

foreach ($path in @($python, $clang, $readobj, $runtimeHelper)) {
    if (-not (Test-Path $path)) {
        throw "Required JIT runtime file missing: $path"
    }
}

Remove-Item -Recurse -Force $workPath, $diagnosticsPath -ErrorAction Ignore
New-Item -ItemType Directory -Force $workPath, $diagnosticsPath | Out-Null

# Deliberately poison all ambient compiler/SDK signals. The Python runtime
# helper, not this wrapper, must neutralize them inside the JIT process.
$poisonRoot = Join-Path $workPath "ambient-poison"
$env:VSINSTALLDIR = Join-Path $poisonRoot "Microsoft Visual Studio"
$env:VCINSTALLDIR = Join-Path $poisonRoot "Microsoft Visual Studio\VC"
$env:VCToolsInstallDir = Join-Path $poisonRoot "Microsoft Visual Studio\VC\Tools"
$env:INCLUDE = Join-Path $poisonRoot "Windows Kits\Include"
$env:LIB = Join-Path $poisonRoot "Windows Kits\Lib"
$env:LIBPATH = Join-Path $poisonRoot "Windows Kits\LibPath"
$env:LIBRARY_PATH = Join-Path $poisonRoot "fake-library-path"
$env:WindowsSdkDir = Join-Path $poisonRoot "Windows Kits"
$env:WindowsSDKVersion = "poison"
$env:UniversalCRTSdkDir = Join-Path $poisonRoot "Windows Kits\UCRT"
$env:UCRTVersion = "poison"
$env:DISTUTILS_USE_SDK = "1"
$env:MSSdk = "1"
$env:CC = "cl.exe"
$env:CXX = "cl.exe"
$env:CPP = "cl.exe /E"
$env:LD = "link.exe"
$env:LDSHARED = "link.exe /DLL"
$env:VSCMD_ARG_TGT_ARCH = "x64"
$env:CPATH = Join-Path $poisonRoot "cp"
$env:C_INCLUDE_PATH = Join-Path $poisonRoot "c-include"
$env:CPLUS_INCLUDE_PATH = Join-Path $poisonRoot "cxx-include"
$env:COMPILER_PATH = Join-Path $poisonRoot "compiler-path"
$env:GCC_EXEC_PREFIX = Join-Path $poisonRoot "gcc-prefix"

@(
    "VSINSTALLDIR=$env:VSINSTALLDIR"
    "WindowsSdkDir=$env:WindowsSdkDir"
    "INCLUDE=$env:INCLUDE"
    "LIB=$env:LIB"
    "CC=$env:CC"
    "CXX=$env:CXX"
    "LD=$env:LD"
) | Set-Content (Join-Path $diagnosticsPath "ambient-poison.txt")

function Assert-HelperDiagnostics {
    param(
        [Parameter(Mandatory = $true)][string]$Directory,
        [Parameter(Mandatory = $true)][string]$CommandLogPath
    )

    $configPath = Join-Path $Directory "runtime-config.json"
    $environmentPath = Join-Path $Directory "runtime-environment.txt"
    if (-not (Test-Path $configPath)) {
        throw "Runtime helper did not emit configuration diagnostics: $configPath"
    }
    if (-not (Test-Path $environmentPath)) {
        throw "Runtime helper did not emit environment diagnostics: $environmentPath"
    }
    if (-not (Test-Path $CommandLogPath)) {
        throw "JIT proof did not record compiler commands: $CommandLogPath"
    }

    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    $commands = Get-Content $CommandLogPath -Raw
    $environment = Get-Content $environmentPath -Raw

    if ($config.backend -ne "mingw32") {
        throw "Runtime helper selected unexpected backend: $($config.backend)"
    }
    if ($config.crt -ne "UCRT") {
        throw "Runtime helper selected unexpected CRT: $($config.crt)"
    }
    if ($config.clang_reported_target -notmatch "(?i)^x86_64-w64-(mingw32|windows-gnu)$") {
        throw "Runtime helper selected unexpected Clang target: $($config.clang_reported_target)"
    }

    foreach ($requiredPath in @(
        [string]$config.python_include,
        [string]$config.ffcx_include,
        [string]$config.toolchain_include,
        [string]$config.python_import_library_dir,
        [string]$config.target_library_dir
    )) {
        if ($commands.IndexOf($requiredPath, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
            throw "Compiler/linker commands do not contain helper-selected path: $requiredPath"
        }
    }

    if ($commands -notmatch [regex]::Escape("x86_64-w64-mingw32-clang.exe")) {
        throw "Compiler commands do not use packaged LLVM-MinGW Clang"
    }

    if ($environment -notmatch "(?m)^CC=x86_64-w64-mingw32-clang\.exe$") {
        throw "Runtime helper did not select packaged CC"
    }
    if ($environment -notmatch "(?m)^FFCX_CFFI_COMPILER_BACKEND=mingw32$") {
        throw "Runtime helper did not expose the FFCx backend selection"
    }

    $forbidden = @(
        [regex]::Escape($poisonRoot),
        "(?i)\\Microsoft Visual Studio\\",
        "(?i)\\Windows Kits\\"
    )
    $text = $commands + "`n" + $environment + "`n" + (Get-Content $configPath -Raw)
    foreach ($pattern in $forbidden) {
        if ($text -match $pattern) {
            throw "Ambient compiler/SDK path leaked into helper-selected JIT inputs: $($Matches[0])"
        }
    }

    return $config
}

$proofScript = Join-Path $PSScriptRoot "minimal-cffi-proof.py"
$proofLog = Join-Path $diagnosticsPath "cffi-build.txt"

& $python $proofScript `
    --work-dir $workPath `
    --diagnostics-dir $diagnosticsPath `
    --toolchain-root $toolchainRootPath `
    --python-prefix $pythonPrefixPath 2>&1 |
    Tee-Object -FilePath $proofLog
if ($LASTEXITCODE -ne 0) {
    throw "Minimal CFFI runtime-helper proof failed"
}

$backend = (Get-Content (Join-Path $diagnosticsPath "setuptools-compiler.txt") -Raw).Trim()
if ($backend -ne "mingw32") {
    throw "Expected runtime helper compiler backend mingw32, got '$backend'"
}

$commandLogPath = Join-Path $diagnosticsPath "compiler-commands.txt"
$config = Assert-HelperDiagnostics -Directory $diagnosticsPath -CommandLogPath $commandLogPath
$commandLog = Get-Content $commandLogPath -Raw
if ($commandLog -notmatch [regex]::Escape("-std=c17")) {
    throw "Minimal CFFI commands do not contain GNU-driver-compatible C17 flag"
}

$poisonCfg = Get-Content (Join-Path $workPath "setup.cfg") -Raw
if ($poisonCfg -notmatch "compiler\s*=\s*msvc") {
    throw "Minimal CFFI proof did not retain the deliberately poisoned setup.cfg"
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

Write-Host "Hermetic LLVM-MinGW CFFI helper proof passed: $pydPath"

if ($PoissonScript) {
    $poissonPath = [System.IO.Path]::GetFullPath($PoissonScript)
    if (-not (Test-Path $poissonPath)) {
        throw "Poisson test script not found: $poissonPath"
    }

    $poissonDiagnostics = Join-Path $diagnosticsPath "poisson"
    $cacheHome = Join-Path $workPath "ffcx-cache"
    $cacheDir = Join-Path $cacheHome "fenics"
    Remove-Item -Recurse -Force $cacheHome -ErrorAction Ignore
    New-Item -ItemType Directory -Force $cacheDir, $poissonDiagnostics | Out-Null

    $patchScript = Join-Path $PSScriptRoot "patch-ffcx-c17.py"
    & $python $patchScript --diagnostics-dir $poissonDiagnostics 2>&1 |
        Tee-Object -FilePath (Join-Path $poissonDiagnostics "ffcx-patch-output.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "FFCx C17 patch failed"
    }

    & $python -c "import dolfinx, ffcx, cffi, setuptools; print('dolfinx=' + dolfinx.__version__); print('ffcx=' + ffcx.__version__); print('cffi=' + cffi.__version__); print('setuptools=' + setuptools.__version__)" 2>&1 |
        Set-Content (Join-Path $poissonDiagnostics "versions.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Could not import the installed FEniCS/JIT stack"
    }

    $poissonProof = Join-Path $PSScriptRoot "ffcx-poisson-proof.py"
    $poissonLog = Join-Path $poissonDiagnostics "poisson-output.txt"
    & $python $poissonProof `
        --poisson-script $poissonPath `
        --cache-dir $cacheDir `
        --diagnostics-dir $poissonDiagnostics `
        --toolchain-root $toolchainRootPath `
        --python-prefix $pythonPrefixPath 2>&1 |
        Tee-Object -FilePath $poissonLog
    if ($LASTEXITCODE -ne 0) {
        throw "Fresh FFCx Poisson runtime-helper proof failed"
    }

    $poissonBackend = (Get-Content (Join-Path $poissonDiagnostics "setuptools-compiler.txt") -Raw).Trim()
    if ($poissonBackend -ne "mingw32") {
        throw "Expected FFCx runtime helper backend mingw32, got '$poissonBackend'"
    }

    $poissonCommandPath = Join-Path $poissonDiagnostics "compiler-commands.txt"
    $poissonConfig = Assert-HelperDiagnostics -Directory $poissonDiagnostics -CommandLogPath $poissonCommandPath
    $poissonCommands = Get-Content $poissonCommandPath -Raw

    if ($poissonCommands -notmatch [regex]::Escape("-std=c17")) {
        throw "FFCx Poisson commands do not contain GNU-driver-compatible -std=c17"
    }
    if ($poissonCommands -match [regex]::Escape("-std:c17")) {
        throw "FFCx Poisson commands still contain the MSVC-only -std:c17 flag"
    }
    if ($poissonCommands -notmatch [regex]::Escape("-D__STDC_NO_COMPLEX__")) {
        throw "FFCx Poisson commands do not suppress complex UFCx members for MSVC ABI compatibility"
    }

    $poissonFfcxCfg = Get-Content (Join-Path $cacheDir "setup.cfg") -Raw
    if ($poissonFfcxCfg -notmatch "compiler\s*=\s*msvc") {
        throw "FFCx proof did not retain the deliberately poisoned setup.cfg"
    }

    $pydPaths = Get-Content (Join-Path $poissonDiagnostics "pyd-paths.txt") |
        Where-Object { $_ -and (Test-Path $_) }
    if (-not $pydPaths) {
        throw "FFCx Poisson proof recorded no readable JIT .pyd files"
    }

    $poissonImportsPath = Join-Path $poissonDiagnostics "pyd-imports.txt"
    Remove-Item $poissonImportsPath -ErrorAction Ignore
    foreach ($jitPyd in $pydPaths) {
        "=== $jitPyd ===" | Add-Content $poissonImportsPath
        $jitImports = & $readobj --coff-imports $jitPyd 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "llvm-readobj failed while inspecting FFCx JIT module: $jitPyd"
        }
        $jitImports | Add-Content $poissonImportsPath
        $jitImportText = $jitImports -join "`n"
        if ($jitImportText -notmatch "(?i)python3\.dll") {
            throw "FFCx JIT module does not import python3.dll: $jitPyd"
        }
        if ($jitImportText -match "(?i)python3\d{2}t?(?:_d)?\.dll") {
            throw "FFCx JIT module unexpectedly imports a version-specific Python DLL: $jitPyd"
        }
    }

    Write-Host "Hermetic LLVM-MinGW fresh FFCx Poisson helper proof passed"
}
