# Build a Nuitka standalone bundle from the published FEniCSx packages.
# Run from an x64 VS2022 Native Tools PowerShell.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$EntryPoint,
    [string]$OutputDir = "output-nuitka"
)

$ErrorActionPreference = "Stop"
$environmentName = "fenicsx-nuitka"
$repoRoot = Split-Path -Parent $PSScriptRoot

$entry = Resolve-Path -LiteralPath $EntryPoint -ErrorAction Stop
$output = if ([IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir
} else {
    Join-Path $repoRoot $OutputDir
}
New-Item -ItemType Directory -Force -Path $output | Out-Null

$conda = (Get-Command conda.exe -ErrorAction Stop).Source
$channels = @(
    "--override-channels",
    "--strict-channel-priority",
    "-c", "precise-simulation",
    "-c", "conda-forge"
)
$packages = @(
    "python=3.12.14",
    "fenics-dolfinx=0.11.0.post0=py312hde24a44_110",
    "fenics-libdolfinx=0.11.0.post0=py312h539a487_110",
    "hdf5=1.14.6=mpi_impi_hros3off_10",
    "petsc=3.25.4=real_hbc849e4_7",
    "petsc4py=3.25.4=py312hb00311a_3",
    "mpi4py=4.1.2",
    "metis=5.2.1",
    "libblas=*=*openblas",
    "nuitka=4.1.3",
    "c-compiler",
    "ordered-set"
)

$envInfo = & $conda env list --json | ConvertFrom-Json
$envPrefix = $envInfo.envs |
    Where-Object { (Split-Path -Leaf $_) -eq $environmentName } |
    Select-Object -First 1

$condaAction = if ($envPrefix) { "install" } else { "create" }
Write-Host "== $condaAction $environmentName from public channels =="
& $conda $condaAction --yes --name $environmentName @channels @packages
if ($LASTEXITCODE -ne 0) { throw "Conda $condaAction failed" }

$envPrefix = (& $conda run --name $environmentName python -c "import sys; print(sys.prefix)" |
    Select-Object -Last 1).Trim()
if (-not (Test-Path -LiteralPath $envPrefix)) {
    throw "Could not resolve the $environmentName environment prefix"
}

Write-Host "== selected packages =="
& $conda list --name $environmentName --show-channel-urls
if ($LASTEXITCODE -ne 0) { throw "Could not list the $environmentName packages" }

$dllNames = @(
    "dolfinx.dll",
    "basix.dll",
    "hdf5.dll",
    "libpetsc.dll",
    "impi.dll",
    "spdlog.dll",
    "fmt.dll",
    "pugixml.dll",
    "openblas.dll",
    "metis.dll",
    "ffi-8.dll",
    "libexpat.dll",
    "szip.dll"
)
$includeDlls = foreach ($dllName in $dllNames) {
    $dllPath = Join-Path $envPrefix "Library\bin\$dllName"
    if (-not (Test-Path -LiteralPath $dllPath)) {
        throw "Missing channel-installed runtime DLL: $dllPath"
    }
    "--include-data-files=$dllPath=$dllName"
}

$nuitkaArgs = @(
    "--standalone",
    "--assume-yes-for-downloads",
    "--remove-output",
    "--output-dir=$output",
    "--output-filename=fenicsx.exe",
    "--include-package=dolfinx",
    "--include-package=basix",
    "--include-package=mpi4py",
    "--include-package=petsc4py",
    "--include-package=ufl",
    "--include-package=ffcx",
    "--include-package-data=dolfinx",
    "--include-package-data=basix",
    "--include-package-data=petsc4py",
    "--include-package-data=ffcx"
) + $includeDlls + @(
    "--report=$(Join-Path $output 'nuitka-report.xml')",
    $entry.Path
)

Write-Host "== Nuitka build =="
& $conda run --name $environmentName --no-capture-output python -m nuitka @nuitkaArgs
if ($LASTEXITCODE -ne 0) { throw "Nuitka build failed" }

Write-Host "== bundle written to $output =="
