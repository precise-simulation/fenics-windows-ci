param(
    [Parameter(Mandatory = $true)]
    [string]$Prefix,

    [Parameter(Mandatory = $true)]
    [string]$PythonVersion
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $env:MAMBA_EXE) {
    throw "MAMBA_EXE is not set"
}

function Invoke-FenicsEnvironmentCreate {
    & $env:MAMBA_EXE create -y -p $Prefix `
        --override-channels --strict-channel-priority `
        -c precise-simulation -c conda-forge `
        "python=$PythonVersion" "libblas=*=*openblas" `
        fenics-jit-llvm-mingw fenics-dolfinx cffi setuptools pefile | Out-Host
    $code = $LASTEXITCODE
    return $code
}

$firstExit = Invoke-FenicsEnvironmentCreate
if ($firstExit -eq 0) {
    return
}

Write-Warning (
    "FEniCS environment creation failed once (exit $firstExit). " +
    "Clearing micromamba caches and retrying exactly once."
)

Remove-Item -LiteralPath $Prefix -Recurse -Force -ErrorAction SilentlyContinue

& $env:MAMBA_EXE clean --all --yes | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "micromamba cache cleanup failed after environment-create failure"
}

$secondExit = Invoke-FenicsEnvironmentCreate
if ($secondExit -ne 0) {
    throw "FEniCS environment installation failed after one cache-clean retry"
}
