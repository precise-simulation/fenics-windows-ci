[CmdletBinding()]
param(
    [string]$OutputPath = "build-logs/vs2022-jit-baseline.json"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RequiredValue {
    param(
        [hashtable]$Variables,
        [string]$Name
    )

    if (-not $Variables.ContainsKey($Name) -or [string]::IsNullOrWhiteSpace([string]$Variables[$Name])) {
        throw "vcvarsall did not define required variable $Name"
    }
    return [string]$Variables[$Name]
}

function New-Root {
    param(
        [string]$Name,
        [string]$Path,
        [string]$Reason
    )

    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "Required VS2022 baseline directory missing: $Name -> $resolved"
    }

    [pscustomobject]@{
        name = $Name
        path = $resolved
        reason = $Reason
    }
}

function Measure-RootSet {
    param([object[]]$Roots)

    $seenFiles = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    $rootReports = @()
    [int64]$uniqueBytes = 0
    [int64]$uniqueFiles = 0

    foreach ($root in $Roots) {
        $files = @(Get-ChildItem -LiteralPath $root.path -Recurse -File -Force -ErrorAction Stop)
        [int64]$rootBytes = 0
        foreach ($file in $files) {
            $rootBytes += [int64]$file.Length
            if ($seenFiles.Add($file.FullName)) {
                $uniqueBytes += [int64]$file.Length
                $uniqueFiles += 1
            }
        }

        $rootReports += [pscustomobject]@{
            name = $root.name
            path = $root.path
            reason = $root.reason
            file_count = $files.Count
            bytes = $rootBytes
        }
    }

    [pscustomobject]@{
        root_count = $Roots.Count
        unique_file_count = $uniqueFiles
        unique_bytes = $uniqueBytes
        roots = $rootReports
    }
}

function Add-UniqueExistingRoot {
    param(
        [System.Collections.Generic.List[object]]$Roots,
        [System.Collections.Generic.HashSet[string]]$Seen,
        [string]$Name,
        [string]$Path,
        [string]$Reason
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }

    $full = [IO.Path]::GetFullPath($Path.Trim())
    if (-not (Test-Path -LiteralPath $full -PathType Container)) {
        return
    }
    if ($Seen.Add($full)) {
        $Roots.Add([pscustomobject]@{
            name = $Name
            path = $full
            reason = $Reason
        })
    }
}

$programFilesX86 = [Environment]::GetFolderPath("ProgramFilesX86")
$vswhere = Join-Path $programFilesX86 "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
    throw "vswhere.exe not found: $vswhere"
}

$installationCandidates = @(
    & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
)
$vswhereSucceeded = $?
$installationPath = [string]($installationCandidates | Select-Object -First 1)
if (-not $vswhereSucceeded -or [string]::IsNullOrWhiteSpace($installationPath)) {
    throw "Could not locate VS2022 with Microsoft.VisualStudio.Component.VC.Tools.x86.x64"
}
$installationPath = $installationPath.Trim()

$vcvarsall = Join-Path $installationPath "VC\Auxiliary\Build\vcvarsall.bat"
if (-not (Test-Path -LiteralPath $vcvarsall -PathType Leaf)) {
    throw "vcvarsall.bat not found: $vcvarsall"
}

$activationCommand = 'call "' + $vcvarsall + '" x64 >nul && set'
$activationLines = & $env:ComSpec /d /s /c $activationCommand
$activationSucceeded = $?
if (-not $activationSucceeded) {
    throw "VS2022 x64 vcvarsall activation failed"
}

$variables = @{}
foreach ($line in $activationLines) {
    $separator = $line.IndexOf("=")
    if ($separator -gt 0) {
        $variables[$line.Substring(0, $separator)] = $line.Substring($separator + 1)
    }
}

$vcToolsDir = (Get-RequiredValue $variables "VCToolsInstallDir") -replace "[\\/]+$",""
$windowsSdkDir = (Get-RequiredValue $variables "WindowsSdkDir") -replace "[\\/]+$",""
$windowsSdkVersion = (Get-RequiredValue $variables "WindowsSDKVersion") -replace "[\\/]+$",""
$ucrtSdkDir = if ($variables.ContainsKey("UniversalCRTSdkDir")) {
    ([string]$variables["UniversalCRTSdkDir"]) -replace "[\\/]+$",""
} else {
    $windowsSdkDir
}
$ucrtVersion = if ($variables.ContainsKey("UCRTVersion")) {
    ([string]$variables["UCRTVersion"]) -replace "[\\/]+$",""
} else {
    $windowsSdkVersion
}

$vcAuxBuild = Join-Path $installationPath "VC\Auxiliary\Build"
$jitLowerBoundRoots = @(
    New-Root "vc-x64-tools" (Join-Path $vcToolsDir "bin\Hostx64\x64") "cl/link and adjacent compiler-tool runtime DLLs"
    New-Root "vc-headers" (Join-Path $vcToolsDir "include") "MSVC header search root exposed by x64 activation"
    New-Root "vc-x64-libraries" (Join-Path $vcToolsDir "lib\x64") "MSVC x64 library search root"
    New-Root "vc-activation" $vcAuxBuild "VS2022 activation files required by the old external-toolchain model"
    New-Root "sdk-x64-tools" (Join-Path $windowsSdkDir "bin\$windowsSdkVersion\x64") "selected Windows SDK x64 tools"
    New-Root "sdk-ucrt-headers" (Join-Path $ucrtSdkDir "Include\$ucrtVersion\ucrt") "UCRT headers"
    New-Root "sdk-shared-headers" (Join-Path $windowsSdkDir "Include\$windowsSdkVersion\shared") "Windows shared headers"
    New-Root "sdk-um-headers" (Join-Path $windowsSdkDir "Include\$windowsSdkVersion\um") "Windows user-mode headers"
    New-Root "sdk-ucrt-x64-libraries" (Join-Path $ucrtSdkDir "Lib\$ucrtVersion\ucrt\x64") "UCRT x64 import libraries"
    New-Root "sdk-um-x64-libraries" (Join-Path $windowsSdkDir "Lib\$windowsSdkVersion\um\x64") "Windows user-mode x64 import libraries"
)
$jitLowerBound = Measure-RootSet $jitLowerBoundRoots

$activatedRoots = [System.Collections.Generic.List[object]]::new()
$activatedSeen = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
foreach ($variableName in @("INCLUDE", "LIB")) {
    if (-not $variables.ContainsKey($variableName)) {
        continue
    }
    $index = 0
    foreach ($path in ([string]$variables[$variableName] -split ";")) {
        if ([string]::IsNullOrWhiteSpace($path)) {
            continue
        }
        Add-UniqueExistingRoot $activatedRoots $activatedSeen "$($variableName.ToLower())-$index" $path "directory exposed by vcvarsall $variableName"
        $index += 1
    }
}
Add-UniqueExistingRoot $activatedRoots $activatedSeen "vc-x64-tools" (Join-Path $vcToolsDir "bin\Hostx64\x64") "compiler/linker tool directory"
Add-UniqueExistingRoot $activatedRoots $activatedSeen "sdk-x64-tools" (Join-Path $windowsSdkDir "bin\$windowsSdkVersion\x64") "selected Windows SDK x64 tool directory"
$activatedSearchClosure = Measure-RootSet ($activatedRoots.ToArray())

$prerequisiteRoots = @(
    New-Root "versioned-msvc-toolset" $vcToolsDir "complete installed versioned MSVC toolset; contextual upper prerequisite"
    New-Root "vc-activation" $vcAuxBuild "Visual Studio activation files"
    New-Root "versioned-sdk-include" (Join-Path $windowsSdkDir "Include\$windowsSdkVersion") "complete selected Windows SDK include version"
    New-Root "versioned-sdk-lib" (Join-Path $windowsSdkDir "Lib\$windowsSdkVersion") "complete selected Windows SDK library version"
    New-Root "versioned-sdk-bin" (Join-Path $windowsSdkDir "bin\$windowsSdkVersion") "complete selected Windows SDK tool version"
)
$installedPrerequisiteContext = Measure-RootSet $prerequisiteRoots

$report = [ordered]@{
    schema_version = 1
    runner = [ordered]@{
        image = $env:ImageOS
        image_version = $env:ImageVersion
        os = [Environment]::OSVersion.VersionString
    }
    visual_studio = [ordered]@{
        installation_path = $installationPath
        vc_tools_install_dir = $vcToolsDir
        windows_sdk_dir = $windowsSdkDir        
        windows_sdk_version = $windowsSdkVersion
        ucrt_sdk_dir = $ucrtSdkDir
        ucrt_version = $ucrtVersion
    }
    methodology = [ordered]@{
        gate_denominator = "jit_lower_bound.unique_bytes"
        gate_rationale = "Use a conservative external x64 C compile/link prerequisite rather than the tiny conda activation package or the whole Visual Studio IDE."
        conda_activation_package = "Reported separately when needed; it is activation metadata and is not a self-contained compiler footprint."
        compressed_download = "Not attributable from the pre-baked GitHub runner image; do not substitute conda activation-package bytes."
        standalone_delta = "Exact standalone JIT delta is measured in Phase 7; Phase 6 records the staged toolchain contribution."
        ci_gate_export = "When GITHUB_ENV is available, export the measured lower-bound and 50% gate bytes for the subsequent package-staging step."
    }
    jit_lower_bound = $jitLowerBound
    activated_search_closure = $activatedSearchClosure
    installed_prerequisite_context = $installedPrerequisiteContext
    fifty_percent_gate_bytes = [int64][math]::Floor($jitLowerBound.unique_bytes / 2)
}

$outputDirectory = Split-Path -Parent $OutputPath
if ($outputDirectory) {
    New-Item -ItemType Directory -Force $outputDirectory | Out-Null
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

if ($env:GITHUB_ENV) {
    "PHASE6_VS2022_JIT_LOWER_BOUND_BYTES=$($jitLowerBound.unique_bytes)" |
        Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
    "PHASE6_VS2022_JIT_GATE_BYTES=$($report.fifty_percent_gate_bytes)" |
        Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
}

Write-Host "VS2022 JIT baseline"
Write-Host "  Visual Studio: $installationPath"
Write-Host "  VC tools: $vcToolsDir"
Write-Host "  Windows SDK: $windowsSdkVersion"
Write-Host "  x64 C JIT lower-bound files: $($jitLowerBound.unique_file_count)"
Write-Host "  x64 C JIT lower-bound MiB: $([math]::Round($jitLowerBound.unique_bytes / 1MB, 2))"
Write-Host "  activated INCLUDE/LIB closure MiB: $([math]::Round($activatedSearchClosure.unique_bytes / 1MB, 2))"
Write-Host "  installed prerequisite context MiB: $([math]::Round($installedPrerequisiteContext.unique_bytes / 1MB, 2))"
Write-Host "  50% lower-bound gate ceiling MiB: $([math]::Round($report.fifty_percent_gate_bytes / 1MB, 2))"
Write-Host "  report: $OutputPath"
