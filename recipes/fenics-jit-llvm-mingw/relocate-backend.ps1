Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $env:LIBRARY_PREFIX) { throw "LIBRARY_PREFIX is not set" }

$jitRoot = Join-Path $env:LIBRARY_PREFIX "fenics-jit"
if (-not (Test-Path -LiteralPath $jitRoot -PathType Container)) {
    throw "Staged LLVM-MinGW root is missing: $jitRoot"
}

# The compiler package must not absorb files owned by the common runtime or
# another backend. During package construction the historical minimization
# stages use Library/fenics-jit as a private staging root; only after all of
# those proven stages finish do we move that complete payload under the
# backend-specific ownership boundary required by Phase 4B.
foreach ($sharedName in @("runtime", "backends")) {
    $sharedPath = Join-Path $jitRoot $sharedName
    if (Test-Path -LiteralPath $sharedPath) {
        throw "Unexpected shared/backend path in LLVM-MinGW staging root: $sharedPath"
    }
}

$stagedRoot = Join-Path $env:LIBRARY_PREFIX "_fenics-jit-llvm-mingw-staged"
Remove-Item -Recurse -Force $stagedRoot -ErrorAction SilentlyContinue
Move-Item -LiteralPath $jitRoot -Destination $stagedRoot

$backendRoot = Join-Path $jitRoot "backends\llvm-mingw"
New-Item -ItemType Directory -Force $backendRoot | Out-Null

$entries = @(Get-ChildItem -LiteralPath $stagedRoot -Force)
if ($entries.Count -eq 0) {
    throw "LLVM-MinGW staged payload is empty: $stagedRoot"
}
foreach ($entry in $entries) {
    Move-Item -LiteralPath $entry.FullName -Destination $backendRoot
}
Remove-Item -LiteralPath $stagedRoot -Force

# The proven compiler-specific CFFI runtime implementation belongs to the LLVM
# backend package. Keep the shared runtime path as a backend-neutral loader.
$backendRuntimeSource = Join-Path $PSScriptRoot "fenics_jit_runtime.py"
if (-not (Test-Path -LiteralPath $backendRuntimeSource -PathType Leaf)) {
    throw "LLVM-MinGW backend runtime source is missing: $backendRuntimeSource"
}
Copy-Item -LiteralPath $backendRuntimeSource -Destination (Join-Path $backendRoot "fenics_jit_runtime.py") -Force

foreach ($required in @(
    "bin\x86_64-w64-mingw32-clang.exe",
    "bin\ld.lld.exe",
    "include\io.h",
    "lib\python\libpython3.a",
    "x86_64-w64-mingw32\lib\libunwind.a",
    "metadata.json",
    "manifest.csv",
    "size.txt",
    "fenics_jit_runtime.py"
)) {
    $path = Join-Path $backendRoot $required
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Relocated LLVM-MinGW payload is missing required file: $path"
    }
}

if (Test-Path -LiteralPath (Join-Path $jitRoot "bin")) {
    throw "LLVM-MinGW compiler files remain in the shared JIT root after relocation"
}

Write-Host "Relocated fenics-jit-llvm-mingw payload"
Write-Host "  backend root: $backendRoot"
