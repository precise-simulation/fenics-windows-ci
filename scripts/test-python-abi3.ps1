param(
    [switch]$Preview
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot | Split-Path
$output = Join-Path $root "output"

$channels = @()
if (Test-Path "$output/win-64/repodata.json") {
    $localChannel = "file:///$($output -replace '\\','/')"
    $channels += $localChannel
    Write-Host "Using freshly built packages from $localChannel"
} else {
    Write-Host "No local build output found; testing published packages only."
}
$channels += "precise-simulation"

if ($Preview) {
    $pythonVersions = @("3.15.*")
    $channels += "conda-forge/label/python_dev", "conda-forge"
} else {
    # Test both ends of the supported ABI3 range: the build/minimum Python
    # and the newest stable Python currently supported by the stack.
    $pythonVersions = @("3.12.*", "3.14.*")
    $channels += "conda-forge"
}

function Invoke-Micromamba {
    param([string[]]$Arguments)
    & micromamba @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "micromamba failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

foreach ($pythonVersion in $pythonVersions) {
    $tag = ($pythonVersion -replace '[^0-9]', '')
    $envName = "fenics-abi3-$tag"
    if ($Preview) { $envName += "-preview" }

    Write-Host "== ABI3 consumer test: Python $pythonVersion =="
    & micromamba env remove -y -n $envName 2>$null | Out-Null

    $createArgs = @("create", "-y", "-n", $envName, "--override-channels")
    foreach ($channel in $channels) {
        $createArgs += @("-c", $channel)
    }
    $createArgs += @(
        "python=$pythonVersion",
        "libblas=*=*openblas",
        "fenics-dolfinx"
    )

    try {
        Invoke-Micromamba -Arguments $createArgs

        Invoke-Micromamba -Arguments @(
            "run", "-n", $envName,
            "python", "-c",
            "import sys, dolfinx, petsc4py; print(sys.version); print('DOLFINx', dolfinx.__version__); print('petsc4py', petsc4py.__version__)"
        )

        Invoke-Micromamba -Arguments @(
            "run", "-n", $envName,
            "python", "-c",
            "from mpi4py import MPI; from dolfinx import mesh; mesh.create_unit_square(MPI.COMM_SELF, 4, 4); print('serial ABI3 smoke test OK')"
        )
    }
    finally {
        & micromamba env remove -y -n $envName 2>$null | Out-Null
    }
}
