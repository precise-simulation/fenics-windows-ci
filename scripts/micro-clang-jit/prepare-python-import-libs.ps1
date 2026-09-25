param(
    [Parameter(Mandatory = $true)][string]$MicroClangRoot,
    [Parameter(Mandatory = $true)][string]$PythonPrefix
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = [System.IO.Path]::GetFullPath($MicroClangRoot)
$prefix = [System.IO.Path]::GetFullPath($PythonPrefix)
$readobj = Join-Path $root "bin\llvm-readobj.exe"
$dlltool = Join-Path $root "bin\llvm-dlltool.exe"
foreach ($path in @($readobj, $dlltool)) {
    if (-not (Test-Path $path)) { throw "micro-Clang tool missing: $path" }
}

$candidates = @(
    (Join-Path $prefix "python3.dll"),
    (Join-Path $prefix "DLLs\python3.dll"),
    (Join-Path $prefix "Library\bin\python3.dll")
)
$python3Dll = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python3Dll) { throw "python3.dll not found below $prefix" }

$exports = & $readobj --coff-exports $python3Dll 2>&1
if ($LASTEXITCODE -ne 0) { throw "llvm-readobj failed for $python3Dll" }
$names = @(
    $exports |
        ForEach-Object {
            if ($_ -match "^\s*Name:\s+(.+?)\s*$") { $Matches[1] }
        } |
        Where-Object { $_ } |
        Sort-Object -Unique
)
if ($names.Count -lt 10) { throw "Unexpectedly few python3.dll exports: $($names.Count)" }

$libDir = Join-Path $root "lib\python"
New-Item -ItemType Directory -Force $libDir | Out-Null
$def = Join-Path $libDir "python3.def"
@("LIBRARY python3.dll", "EXPORTS") + $names | Set-Content $def -Encoding Ascii

foreach ($name in @("libpython3.a", "libpython312.a", "libpython313.a", "libpython314.a", "libpython315.a")) {
    $out = Join-Path $libDir $name
    & $dlltool -m i386:x86-64 -d $def -l $out -D python3.dll
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $out)) {
        throw "Failed to build Stable-ABI import-library alias: $name"
    }
}

Write-Host "Prepared micro-Clang Stable-ABI Python import libraries from $python3Dll"
