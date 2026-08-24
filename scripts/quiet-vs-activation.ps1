# Silences the chatty conda-forge VS activation script (vs2022_compiler_vars.bat)
# in a conda env. Package-owned file -> any env update/recreate restores the noise;
# just rerun this script. Idempotent.
#
# Usage:  powershell -File quiet-vs-activation.ps1 -Env fenics-windows
param([string]$EnvName = "fenics-windows")

$ErrorActionPreference = "Stop"
$f = "$env:USERPROFILE\miniconda3\envs\$EnvName\etc\conda\activate.d\vs2022_compiler_vars.bat"
if (-not (Test-Path $f)) { throw "not found: $f" }
if ((Get-Content $f -Raw) -match "\[quiet-patch applied\]") { Write-Output "already patched: $f"; exit 0 }

$t = Get-Content $f -Raw
$t = $t.Replace('@echo on', @'
@echo off
:: [quiet-patch applied]
'@)
$repl = @(
    @('echo "Didn''t find any windows 10 SDK. I''m not sure if things will work, but let''s try..."',
      'echo "Didn''t find any windows 10 SDK. I''m not sure if things will work, but let''s try..." >nul 2>&1'),
    @('echo Windows SDK version found as: "%WindowsSDKVer%"',
      'echo Windows SDK version found as: "%WindowsSDKVer%" >nul 2>&1'),
    @('echo "NEWER_VS_WITH_OLDER_VC=%NEWER_VS_WITH_OLDER_VC%"',
      'echo "NEWER_VS_WITH_OLDER_VC=%NEWER_VS_WITH_OLDER_VC%" >nul 2>&1'),
    @('type "%VSINSTALLDIR%\VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt"',
      'type "%VSINSTALLDIR%\VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt" >nul 2>&1'),
    @('dir "%VSINSTALLDIR%\VC\Redist\MSVC\"',
      'dir "%VSINSTALLDIR%\VC\Redist\MSVC\" >nul 2>&1'),
    @('CALL "VC\Auxiliary\Build\vcvars%VCVARSBAT%.bat" -vcvars_ver=%LATEST_VS:~0,5% %WindowsSDKVer%',
      'CALL "VC\Auxiliary\Build\vcvars%VCVARSBAT%.bat" -vcvars_ver=%LATEST_VS:~0,5% %WindowsSDKVer% >nul'),
    @('CALL "VC\Auxiliary\Build\vcvars%VCVARSBAT%.bat" -vcvars_ver=14.44 %WindowsSDKVer%',
      'CALL "VC\Auxiliary\Build\vcvars%VCVARSBAT%.bat" -vcvars_ver=14.44 %WindowsSDKVer% >nul')
)
foreach ($r in $repl) { $t = $t.Replace($r[0], $r[1]) }
# retry-without-args call (only exact standalone line)
$t = $t -replace '(?m)^(\s*CALL "VC\\Auxiliary\\Build\\vcvars%VCVARSBAT%\.bat")\s*$','$1 >nul'

# conda hard-links env files to the pkgs cache: editing in place would corrupt
# the cache (conda SafetyError on next install). Break the link via temp+move.
$tmp = "$f.quiet-tmp"
Set-Content $tmp $t -Encoding ASCII
Move-Item $tmp $f -Force
Write-Output "patched: $f"

