param(
    [string]$Destination = ".jit-toolchain",
    [string]$DiagnosticsDir = "jit-diagnostics/toolchain",
    [string]$Version = "20260826",
    [string]$Sha256 = "ae601f4e0f72bbdf441ad2df8bb16f037e2e9251559ea6b37b4057aef39c06c3"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$archiveName = "llvm-mingw-$Version-ucrt-x86_64.zip"
$url = "https://github.com/mstorsjo/llvm-mingw/releases/download/$Version/$archiveName"
$destinationPath = [System.IO.Path]::GetFullPath($Destination)
$diagnosticsPath = [System.IO.Path]::GetFullPath($DiagnosticsDir)
$archivePath = Join-Path $destinationPath $archiveName
$toolchainRoot = Join-Path $destinationPath "llvm-mingw-$Version-ucrt-x86_64"

New-Item -ItemType Directory -Force $destinationPath, $diagnosticsPath | Out-Null

if (-not (Test-Path $archivePath)) {
    Write-Host "Downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $archivePath
}

$actualSha256 = (Get-FileHash -Path $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSha256 -ne $Sha256.ToLowerInvariant()) {
    throw "LLVM-MinGW checksum mismatch: expected $Sha256, got $actualSha256"
}

if (-not (Test-Path $toolchainRoot)) {
    Write-Host "Extracting $archiveName"
    Expand-Archive -Path $archivePath -DestinationPath $destinationPath
}

$required = @(
    "bin/x86_64-w64-mingw32-clang.exe",
    "bin/x86_64-w64-mingw32-clang++.exe",
    "bin/ld.lld.exe",
    "bin/llvm-dlltool.exe",
    "bin/llvm-readobj.exe"
)
foreach ($relative in $required) {
    $path = Join-Path $toolchainRoot $relative
    if (-not (Test-Path $path)) {
        throw "Required LLVM-MinGW component missing: $path"
    }
}

$clang = Join-Path $toolchainRoot "bin/x86_64-w64-mingw32-clang.exe"
$lld = Join-Path $toolchainRoot "bin/ld.lld.exe"

@(
    "version=$Version"
    "archive=$archiveName"
    "url=$url"
    "sha256=$actualSha256"
    "toolchain_root=$toolchainRoot"
) | Set-Content (Join-Path $diagnosticsPath "manifest.txt")

& $clang --version 2>&1 | Set-Content (Join-Path $diagnosticsPath "clang-version.txt")
if ($LASTEXITCODE -ne 0) { throw "clang --version failed" }

& $lld --version 2>&1 | Set-Content (Join-Path $diagnosticsPath "lld-version.txt")
if ($LASTEXITCODE -ne 0) { throw "ld.lld --version failed" }

Write-Host "LLVM-MinGW ready at $toolchainRoot"
