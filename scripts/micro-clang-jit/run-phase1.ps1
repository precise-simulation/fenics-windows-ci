param(
    [Parameter(Mandatory = $true)][string]$PythonPrefix,
    [Parameter(Mandatory = $true)][string]$MicroClangRoot,
    [Parameter(Mandatory = $true)][string]$ReferenceRoot,
    [string]$WorkDir = "micro-clang-phase1-work",
    [string]$DiagnosticsDir = "micro-clang-phase1-diagnostics",
    [string]$PoissonScript = "scripts/test-poisson.py"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$prefix = [System.IO.Path]::GetFullPath($PythonPrefix)
$micro = [System.IO.Path]::GetFullPath($MicroClangRoot)
$reference = [System.IO.Path]::GetFullPath($ReferenceRoot)
$work = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $WorkDir))
$diagnostics = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $DiagnosticsDir))
Remove-Item -Recurse -Force $work, $diagnostics -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $work, $diagnostics | Out-Null

$importArgs = @{
    MicroClangRoot = $micro
    PythonPrefix = $prefix
}
& (Join-Path $PSScriptRoot "prepare-python-import-libs.ps1") @importArgs
if ($LASTEXITCODE -ne 0) { throw "Stable-ABI import-library preparation failed" }

$python = Join-Path $prefix "python.exe"
& $python (Join-Path $PSScriptRoot "phase1-sentinels.py") --micro-root $micro --reference-root $reference --diagnostics-dir (Join-Path $diagnostics "sentinels") --require-space-path
if ($LASTEXITCODE -ne 0) { throw "micro-Clang/reference sentinel comparison failed" }

$proofDir = Join-Path $diagnostics "jit-proof"
$proofArgs = @{
    PythonPrefix = $prefix
    ToolchainRoot = $micro
    WorkDir = $work
    DiagnosticsDir = $proofDir
    PoissonScript = (Join-Path $repoRoot $PoissonScript)
}
& (Join-Path $repoRoot "scripts\llvm-mingw-jit\run-cffi-proof.ps1") @proofArgs
if ($LASTEXITCODE -ne 0) { throw "micro-Clang private CFFI/FFCx proof failed" }

$config = Get-Content (Join-Path $proofDir "runtime-config.json") -Raw | ConvertFrom-Json
if ([System.IO.Path]::GetFullPath([string]$config.toolchain_root) -ne $micro) {
    throw "JIT runtime escaped the private micro-Clang root: $($config.toolchain_root)"
}

$commandFiles = @(
    (Join-Path $proofDir "compiler-commands.txt"),
    (Join-Path $proofDir "poisson\compiler-commands.txt")
)
foreach ($commandFile in $commandFiles) {
    $commands = Get-Content $commandFile -Raw
    if ($commands.IndexOf($reference, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Reference LLVM-MinGW path leaked into private micro-Clang JIT commands"
    }
    if ($commands -match '(?i)(^|[\\\s"])(cl|link)\.exe(["\s]|$)') {
        throw "Visual Studio compiler/linker appeared in micro-Clang JIT commands"
    }
    if ($commands.IndexOf("Library\fenics-jit\backends\llvm-mingw", [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Installed LLVM-MinGW backend leaked into micro-Clang JIT commands"
    }
}

"phase1_private_jit=passed" | Set-Content (Join-Path $diagnostics "result.txt")
Write-Host "micro-Clang Phase-1 private functional/hermeticity proof passed"
