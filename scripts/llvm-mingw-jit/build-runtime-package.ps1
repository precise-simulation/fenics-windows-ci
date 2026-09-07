param(
    [string]$OutputDir = "jit-package-output",
    [string]$DiagnosticsDir = "jit-package-logs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = $PSScriptRoot | Split-Path | Split-Path
$recipe = Join-Path $root "recipes\fenics-jit-llvm-mingw\recipe.yaml"
$output = [System.IO.Path]::GetFullPath((Join-Path $root $OutputDir))
$diagnostics = [System.IO.Path]::GetFullPath((Join-Path $root $DiagnosticsDir))

Remove-Item -Recurse -Force $output, $diagnostics -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $output, $diagnostics | Out-Null

$rattler = Get-ChildItem "$env:MAMBA_ROOT_PREFIX\envs" -Recurse -Filter rattler-build.exe `
    -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
if (-not $rattler) { throw "rattler-build.exe not found under MAMBA_ROOT_PREFIX" }

$rattlerVersion = (& $rattler --version 2>&1 | Out-String).Trim()
"rattler-build=$rattlerVersion" | Set-Content (Join-Path $diagnostics "tooling.txt")

$log = Join-Path $diagnostics "rattler-build.log"
& $rattler build `
    --recipe $recipe `
    --output-dir $output `
    --channel-priority strict `
    -c conda-forge 2>&1 | Tee-Object -FilePath $log
if ($LASTEXITCODE -ne 0) {
    throw "rattler-build failed for fenics-jit-llvm-mingw"
}

$win64 = Join-Path $output "win-64"
$repodata = Join-Path $win64 "repodata.json"
if (-not (Test-Path $repodata)) {
    throw "Runtime package build produced no win-64 repodata.json"
}

$noarch = Join-Path $output "noarch"
New-Item -ItemType Directory -Force $noarch | Out-Null
Set-Content (Join-Path $noarch "repodata.json") '{"info":{"subdir":"noarch"},"packages":{},"packages.conda":{}}'

$packages = @(Get-ChildItem $win64 -File -Filter "fenics-jit-llvm-mingw-*.conda")
if ($packages.Count -ne 1) {
    throw "Expected one fenics-jit-llvm-mingw package, found $($packages.Count)"
}
$package = $packages[0]

$repodataJson = Get-Content $repodata -Raw | ConvertFrom-Json
$records = @()
foreach ($section in @("packages", "packages.conda")) {
    $property = $repodataJson.PSObject.Properties[$section]
    if ($null -ne $property -and $null -ne $property.Value) {
        $records += @($property.Value.PSObject.Properties | ForEach-Object { $_.Value })
    }
}
$record = @($records | Where-Object { $_.name -eq "fenics-jit-llvm-mingw" })
if ($record.Count -ne 1) {
    throw "Could not identify exactly one runtime package record in repodata"
}

$metrics = [ordered]@{
    package = $package.Name
    package_bytes = $package.Length
    package_mib = [math]::Round($package.Length / 1MB, 2)
    sha256 = (Get-FileHash $package.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    repodata_record = $record[0]
}
$metrics | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $diagnostics "package-metrics.json")

Copy-Item $recipe (Join-Path $diagnostics "recipe.yaml") -Force
Copy-Item $repodata (Join-Path $diagnostics "repodata.json") -Force

Write-Host "fenics-jit-llvm-mingw package built:"
Write-Host "  $($package.FullName)"
Write-Host "  compressed MiB: $($metrics.package_mib)"
Write-Host "  sha256: $($metrics.sha256)"
