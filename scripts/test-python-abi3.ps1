param(
    [switch]$Preview
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot | Split-Path
$output = Join-Path $root "output"
$logOutput = Join-Path $root "build-logs"
New-Item -ItemType Directory -Force $logOutput | Out-Null

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
    $channels += "conda-forge/label/python_dev", "conda-forge/label/python_rc", "conda-forge"
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

function Save-EnvironmentProvenance {
    param(
        [string]$EnvironmentName,
        [string]$Tag
    )

    & micromamba list -n $EnvironmentName > (Join-Path $logOutput "abi3-$Tag-list.txt") 2>&1
    if ($LASTEXITCODE -eq 0) {
        & micromamba list -n $EnvironmentName --explicit > (Join-Path $logOutput "abi3-$Tag-explicit.txt") 2>&1
    }
}

foreach ($pythonVersion in $pythonVersions) {
    $tag = ($pythonVersion -replace '[^0-9]', '')
    $modeTag = if ($Preview) { "py${tag}-preview" } else { "py${tag}" }
    $envName = "fenics-abi3-$tag"
    if ($Preview) { $envName += "-preview" }

    Write-Host "== ABI3 consumer test: Python $pythonVersion =="
    & micromamba env remove -y -n $envName 2>$null | Out-Null

    $createArgs = @(
        "create", "-y", "-n", $envName,
        "--override-channels",
        "--strict-channel-priority"
    )
    foreach ($channel in $channels) {
        $createArgs += @("-c", $channel)
    }
    $createArgs += @(
        "python=$pythonVersion",
        "libblas=*=*openblas",
        "fenics-dolfinx"
    )

    $environmentCreated = $false
    try {
        try {
            Invoke-Micromamba -Arguments $createArgs
            $environmentCreated = $true
        }
        catch {
            if ($Preview) {
                Write-Warning "Python 3.15 ecosystem not solvable yet — preview skipped"
                Write-Warning $_.Exception.Message
                continue
            }
            throw
        }

        Save-EnvironmentProvenance -EnvironmentName $envName -Tag $modeTag

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
    catch {
        # If creation succeeded, any failure below this point is a real
        # consumer/import/runtime failure rather than preview-channel lag.
        if ($environmentCreated) {
            Save-EnvironmentProvenance -EnvironmentName $envName -Tag "$modeTag-failure"
        }
        throw
    }
    finally {
        # A failed preview solve never created an environment. Avoid running a
        # failing cleanup command in that case, since its native exit code can
        # otherwise make an intentionally skipped preview step fail.
        if ($environmentCreated) {
            & micromamba env remove -y -n $envName 2>$null | Out-Null
        }
    }
}

# A preview solve failure is intentionally non-fatal. Native-command failures
# leave $LASTEXITCODE nonzero even after they are caught, so explicitly return
# success after all preview iterations. Real import/runtime failures throw
# above and therefore never reach this point.
if ($Preview) {
    exit 0
}
