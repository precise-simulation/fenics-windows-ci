param(
    [Parameter(Mandatory = $true)][string]$Revision,
    [string]$SourceDir = "tinycc-source",
    [string]$OutputDir = "tinycc-stage",
    [string]$DiagnosticsDir = "tinycc-bootstrap-diagnostics"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = [System.IO.Path]::GetFullPath($SourceDir)
$output = [System.IO.Path]::GetFullPath($OutputDir)
$diagnostics = [System.IO.Path]::GetFullPath($DiagnosticsDir)

Remove-Item -Recurse -Force $source, $output, $diagnostics -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $source, $output, $diagnostics | Out-Null

Write-Host "Fetching TinyCC revision $Revision"
git -C $source init
if ($LASTEXITCODE -ne 0) { throw "git init failed" }
git -C $source remote add origin https://github.com/TinyCC/tinycc.git
if ($LASTEXITCODE -ne 0) { throw "git remote add failed" }
git -C $source fetch --depth 1 origin $Revision
if ($LASTEXITCODE -ne 0) { throw "git fetch failed for $Revision" }
git -C $source checkout --detach FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw "git checkout failed" }
$actualRevision = (git -C $source rev-parse HEAD).Trim()
if ($actualRevision -ne $Revision) {
    throw "TinyCC revision mismatch: expected $Revision, got $actualRevision"
}

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio/Installer/vswhere.exe"
if (-not (Test-Path $vswhere)) { throw "vswhere.exe not found" }
$vsInstall = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1).Trim()
if (-not $vsInstall) { throw "Visual Studio C++ tools not found for TinyCC bootstrap" }
$vcvars = Join-Path $vsInstall "VC/Auxiliary/Build/vcvars64.bat"
if (-not (Test-Path $vcvars)) { throw "vcvars64.bat not found: $vcvars" }

$buildScript = Join-Path $source "win32/build-tcc.bat"
if (-not (Test-Path $buildScript)) { throw "TinyCC Windows build script not found: $buildScript" }

$cmd = "call `"$vcvars`" >nul && call `"$buildScript`" -c cl -t x86_64 -i `"$output`""
cmd.exe /d /s /c $cmd 2>&1 | Tee-Object -FilePath (Join-Path $diagnostics "build.log")
if ($LASTEXITCODE -ne 0) { throw "TinyCC bootstrap failed" }

$tcc = Join-Path $output "tcc.exe"
if (-not (Test-Path $tcc)) { throw "TinyCC bootstrap did not produce $tcc" }

$versionOutput = (& $tcc -v 2>&1 | Out-String).Trim()
$versionOutput | Set-Content -Encoding utf8 (Join-Path $diagnostics "version.txt")

$smokeSource = Join-Path $diagnostics "bootstrap-smoke.c"
$smokeDll = Join-Path $diagnostics "bootstrap-smoke.dll"
'__declspec(dllexport) int tinycc_bootstrap_smoke(void) { return 42; }' | Set-Content -Encoding ascii $smokeSource
& $tcc ("-B" + $output) -shared $smokeSource -o $smokeDll
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $smokeDll)) { throw "TinyCC bootstrap smoke compile failed" }

$metadata = [ordered]@{
    revision = $actualRevision
    version = $versionOutput
    bootstrap = "msvc-vcvars64"
    target = "x86_64-windows-pe"
    tcc_sha256 = (Get-FileHash -Algorithm SHA256 $tcc).Hash.ToLowerInvariant()
    tcc_size_bytes = (Get-Item $tcc).Length
}
$metadata | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (Join-Path $output "fenics-tinycc-bootstrap.json")
$metadata | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (Join-Path $diagnostics "bootstrap.json")
Get-Content (Join-Path $diagnostics "bootstrap.json")
