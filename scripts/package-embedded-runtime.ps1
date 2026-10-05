# Package a relocatable FEniCS Windows runtime overlay for an embedded CPython 3.12 host.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Prefix,
    [string]$Output = "dist",
    [string]$Version = "0.1.0"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$prefixPath = (Resolve-Path -LiteralPath $Prefix -ErrorAction Stop).Path
$python = Join-Path $prefixPath "python.exe"
$condaMeta = Join-Path $prefixPath "conda-meta"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "FEniCS prefix is missing python.exe: $python"
}
if (-not (Test-Path -LiteralPath $condaMeta -PathType Container)) {
    throw "FEniCS prefix is missing conda metadata: $condaMeta"
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Embedded-runtime version must be X.Y.Z, got $Version"
}

$records = @(
    Get-ChildItem -LiteralPath $condaMeta -Filter "*.json" -File |
        ForEach-Object {
            $record = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
            [pscustomobject]@{
                name = [string]$record.name
                version = [string]$record.version
                build = [string]$record.build
                build_number = [int]$record.build_number
                channel = [string]$record.channel
                url = [string]$record.url
                files = @($record.files)
            }
        }
)
$recordByName = @{}
foreach ($record in $records) {
    $recordByName[$record.name] = $record
}

foreach ($required in @(
    "python",
    "numpy",
    "fenics-dolfinx",
    "fenics-libdolfinx",
    "fenics-jit-runtime",
    "fenics-jit-micro-clang",
    "petsc",
    "petsc4py",
    "mpi4py",
    "impi_rt",
    "hdf5",
    "fenics-basix",
    "fenics-ffcx",
    "fenics-ufl",
    "cffi",
    "setuptools"
)) {
    if (-not $recordByName.ContainsKey($required)) {
        throw "FEniCS prefix is missing required package: $required"
    }
}
foreach ($forbidden in @("fenics-jit-llvm-mingw", "fenics-jit-tinycc", "vs2022_win-64", "vswhere")) {
    if ($recordByName.ContainsKey($forbidden)) {
        throw "FEniCS embedded runtime unexpectedly contains forbidden package: $forbidden"
    }
}
if ($recordByName["python"].version -notmatch '^3\.12\.') {
    throw "FEniCS embedded runtime requires CPython 3.12, got $($recordByName["python"].version)"
}
if ($recordByName["numpy"].version -ne "2.5.2") {
    throw "FEniCS embedded runtime is pinned to NumPy 2.5.2, got $($recordByName["numpy"].version)"
}
if ($recordByName["fenics-jit-micro-clang"].version -ne "20260826") {
    throw "FEniCS embedded runtime requires qualified micro-Clang 20260826, got $($recordByName["fenics-jit-micro-clang"].version)"
}

$oldPath = $env:PATH
try {
    $env:PATH = @(
        $prefixPath,
        (Join-Path $prefixPath "Scripts"),
        (Join-Path $prefixPath "Library\bin"),
        $oldPath
    ) -join ";"
    $probeText = & $python -c @'
import json, platform, struct, sys
import basix, dolfinx, ffcx, mpi4py, numpy, petsc4py, ufl
print(json.dumps({
    "python": platform.python_version(),
    "implementation": platform.python_implementation(),
    "pointer_bits": 8 * struct.calcsize("P"),
    "numpy": numpy.__version__,
    "dolfinx": dolfinx.__version__,
    "petsc4py": petsc4py.__version__,
    "mpi4py": mpi4py.__version__,
    "ffcx": ffcx.__version__,
    "basix": basix.__version__,
    "ufl": ufl.__version__,
    "prefix": sys.prefix,
}))
'@
    if ($LASTEXITCODE -ne 0) {
        throw "FEniCS prefix import probe failed"
    }
}
finally {
    $env:PATH = $oldPath
}
$probe = ($probeText | Select-Object -Last 1) | ConvertFrom-Json
if ($probe.implementation -ne "CPython" -or $probe.pointer_bits -ne 64 -or $probe.python -notmatch '^3\.12\.') {
    throw "FEniCS prefix does not provide 64-bit CPython 3.12: $($probeText -join [Environment]::NewLine)"
}
if ($probe.numpy -ne "2.5.2") {
    throw "Imported NumPy version differs from package pin: $($probe.numpy)"
}

$outputPath = if ([IO.Path]::IsPathRooted($Output)) {
    [IO.Path]::GetFullPath($Output)
} else {
    Join-Path $repoRoot $Output
}
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

$workRoot = Join-Path ([IO.Path]::GetTempPath()) ("fenics-embed-" + [guid]::NewGuid().ToString("N"))
$stageRoot = Join-Path $workRoot "fenics-embed-runtime"
New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null

$allowedPrefixes = @(
    "Lib/site-packages/",
    "Library/bin/",
    "Library/fenics-jit/",
    "Library/share/",
    "Library/etc/",
    "Library/licenses/",
    "Include/"
)

$owners = @{}
try {
    foreach ($record in $records) {
        foreach ($rawRelative in @($record.files)) {
            if ($null -eq $rawRelative) { continue }
            $relative = ([string]$rawRelative).Replace("\", "/").TrimStart("/")
            if ($relative -match '(^|/)__pycache__/|\.(pyc|pyo)
            foreach ($allowedPrefix in $allowedPrefixes) {
                if ($relative.StartsWith($allowedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                    $allowed = $true
                    break
                }
            }
            if (-not $allowed) { continue }

            $source = Join-Path $prefixPath ($relative -replace '/', '\')
            if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
                throw "Package-owned runtime file is missing from prefix: $relative (owner $($record.name))"
            }
            $destination = Join-Path $stageRoot ($relative -replace '/', '\')
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null

            if (Test-Path -LiteralPath $destination -PathType Leaf) {
                $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
                $destinationHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($sourceHash -ne $destinationHash) {
                    throw "Two conda packages own different bytes at embedded runtime path: $relative"
                }
            }
            else {
                Copy-Item -LiteralPath $source -Destination $destination
            }

            if (-not $owners.ContainsKey($relative)) { $owners[$relative] = @() }
            $owners[$relative] = @($owners[$relative]) + $record.name
        }
    }

    $bootstrapSource = Join-Path $PSScriptRoot "fenics-embed-bootstrap.py"
    if (-not (Test-Path -LiteralPath $bootstrapSource -PathType Leaf)) {
        throw "Embedded-runtime bootstrap source is missing: $bootstrapSource"
    }
    $bootstrapDestination = Join-Path $stageRoot "Lib\site-packages\fenics_embed_runtime.py"
    Copy-Item -LiteralPath $bootstrapSource -Destination $bootstrapDestination
    $owners["Lib/site-packages/fenics_embed_runtime.py"] = @("fenics-windows-ci")

    $provenanceRoot = Join-Path $stageRoot "provenance"
    New-Item -ItemType Directory -Force -Path $provenanceRoot | Out-Null
    $packageSummary = @(
        $records |
            Sort-Object name |
            ForEach-Object {
                [ordered]@{
                    name = $_.name
                    version = $_.version
                    build = $_.build
                    build_number = $_.build_number
                    channel = $_.channel
                    url = $_.url
                }
            }
    )
    $packageSummary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $provenanceRoot "conda-packages.json") -Encoding utf8NoBOM

    $files = @(
        Get-ChildItem -LiteralPath $stageRoot -File -Recurse |
            Sort-Object FullName |
            ForEach-Object {
                $relative = [IO.Path]::GetRelativePath($stageRoot, $_.FullName).Replace("\", "/")
                [ordered]@{
                    path = $relative
                    bytes = $_.Length
                    sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                    owners = if ($owners.ContainsKey($relative)) { @($owners[$relative] | Sort-Object -Unique) } else { @("fenics-windows-ci") }
                }
            }
    )

    $manifest = [ordered]@{
        format_version = 1
        artifact = "fenics-embed-runtime-win-x64-cp312"
        version = $Version
        platform = "win-x64"
        python_abi = "cp312"
        python = [ordered]@{
            version = $probe.python
        }
        numpy = [ordered]@{ version = $probe.numpy }
        dolfinx = [ordered]@{ version = $probe.dolfinx }
        petsc4py = [ordered]@{ version = $probe.petsc4py }
        mpi4py = [ordered]@{ version = $probe.mpi4py }
        jit = [ordered]@{
            runtime_version = $recordByName["fenics-jit-runtime"].version
            backend = "micro-clang"
            backend_version = $recordByName["fenics-jit-micro-clang"].version
            backend_build = $recordByName["fenics-jit-micro-clang"].build
        }
        layout = [ordered]@{
            site_packages = "Lib/site-packages"
            native_bin = "Library/bin"
            jit_root = "Library/fenics-jit"
            python_include = "Include"
            bootstrap = "Lib/site-packages/fenics_embed_runtime.py"
        }
        packages = $packageSummary
        files = $files
    }
    $manifestPath = Join-Path $stageRoot "fenics-embed-manifest.json"
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8NoBOM

    $assetName = "fenics-embed-runtime-v$Version-win-x64-cp312.zip"
    $zipPath = Join-Path $outputPath $assetName
    Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
    Compress-Archive -Path (Join-Path $stageRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal

    $zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $checksumPath = Join-Path $outputPath "SHA256SUMS-embedded-runtime.txt"
    Set-Content -LiteralPath $checksumPath -Value "$zipHash  $assetName" -Encoding utf8NoBOM

    Write-Host "FEniCS embedded-runtime overlay packaged."
    Write-Host "artifact=$zipPath"
    Write-Host "artifact_bytes=$((Get-Item -LiteralPath $zipPath).Length)"
    Write-Host "sha256=$zipHash"
    Write-Host "overlay_files=$($files.Count)"
}
finally {
    Remove-Item -LiteralPath $workRoot -Recurse -Force -ErrorAction SilentlyContinue
}
) {
                continue
            }
            $allowed = $false
            foreach ($allowedPrefix in $allowedPrefixes) {
                if ($relative.StartsWith($allowedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                    $allowed = $true
                    break
                }
            }
            if (-not $allowed) { continue }

            $source = Join-Path $prefixPath ($relative -replace '/', '\')
            if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
                throw "Package-owned runtime file is missing from prefix: $relative (owner $($record.name))"
            }
            $destination = Join-Path $stageRoot ($relative -replace '/', '\')
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null

            if (Test-Path -LiteralPath $destination -PathType Leaf) {
                $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
                $destinationHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($sourceHash -ne $destinationHash) {
                    throw "Two conda packages own different bytes at embedded runtime path: $relative"
                }
            }
            else {
                Copy-Item -LiteralPath $source -Destination $destination
            }

            if (-not $owners.ContainsKey($relative)) { $owners[$relative] = @() }
            $owners[$relative] = @($owners[$relative]) + $record.name
        }
    }

    $bootstrapSource = Join-Path $PSScriptRoot "fenics-embed-bootstrap.py"
    if (-not (Test-Path -LiteralPath $bootstrapSource -PathType Leaf)) {
        throw "Embedded-runtime bootstrap source is missing: $bootstrapSource"
    }
    $bootstrapDestination = Join-Path $stageRoot "Lib\site-packages\fenics_embed_runtime.py"
    Copy-Item -LiteralPath $bootstrapSource -Destination $bootstrapDestination
    $owners["Lib/site-packages/fenics_embed_runtime.py"] = @("fenics-windows-ci")

    $provenanceRoot = Join-Path $stageRoot "provenance"
    New-Item -ItemType Directory -Force -Path $provenanceRoot | Out-Null
    $packageSummary = @(
        $records |
            Sort-Object name |
            ForEach-Object {
                [ordered]@{
                    name = $_.name
                    version = $_.version
                    build = $_.build
                    build_number = $_.build_number
                    channel = $_.channel
                    url = $_.url
                }
            }
    )
    $packageSummary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $provenanceRoot "conda-packages.json") -Encoding utf8NoBOM

    $files = @(
        Get-ChildItem -LiteralPath $stageRoot -File -Recurse |
            Sort-Object FullName |
            ForEach-Object {
                $relative = [IO.Path]::GetRelativePath($stageRoot, $_.FullName).Replace("\", "/")
                [ordered]@{
                    path = $relative
                    bytes = $_.Length
                    sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                    owners = if ($owners.ContainsKey($relative)) { @($owners[$relative] | Sort-Object -Unique) } else { @("fenics-windows-ci") }
                }
            }
    )

    $manifest = [ordered]@{
        format_version = 1
        artifact = "fenics-embed-runtime-win-x64-cp312"
        version = $Version
        platform = "win-x64"
        python_abi = "cp312"
        python = [ordered]@{
            version = $probe.python
        }
        numpy = [ordered]@{ version = $probe.numpy }
        dolfinx = [ordered]@{ version = $probe.dolfinx }
        petsc4py = [ordered]@{ version = $probe.petsc4py }
        mpi4py = [ordered]@{ version = $probe.mpi4py }
        jit = [ordered]@{
            runtime_version = $recordByName["fenics-jit-runtime"].version
            backend = "micro-clang"
            backend_version = $recordByName["fenics-jit-micro-clang"].version
            backend_build = $recordByName["fenics-jit-micro-clang"].build
        }
        layout = [ordered]@{
            site_packages = "Lib/site-packages"
            native_bin = "Library/bin"
            jit_root = "Library/fenics-jit"
            python_include = "Include"
            bootstrap = "Lib/site-packages/fenics_embed_runtime.py"
        }
        packages = $packageSummary
        files = $files
    }
    $manifestPath = Join-Path $stageRoot "fenics-embed-manifest.json"
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8NoBOM

    $assetName = "fenics-embed-runtime-v$Version-win-x64-cp312.zip"
    $zipPath = Join-Path $outputPath $assetName
    Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
    Compress-Archive -Path (Join-Path $stageRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal

    $zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $checksumPath = Join-Path $outputPath "SHA256SUMS-embedded-runtime.txt"
    Set-Content -LiteralPath $checksumPath -Value "$zipHash  $assetName" -Encoding utf8NoBOM

    Write-Host "FEniCS embedded-runtime overlay packaged."
    Write-Host "artifact=$zipPath"
    Write-Host "artifact_bytes=$((Get-Item -LiteralPath $zipPath).Length)"
    Write-Host "sha256=$zipHash"
    Write-Host "overlay_files=$($files.Count)"
}
finally {
    Remove-Item -LiteralPath $workRoot -Recurse -Force -ErrorAction SilentlyContinue
}
