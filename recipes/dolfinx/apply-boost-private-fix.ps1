# Make Boost a private build dependency of the DOLFINx library (Windows).
#
# Upstream exports Boost::headers from the dolfinx CMake target and requires
# find_package(Boost) in DOLFINXConfig.cmake.in, which drags libboost,
# libboost-devel and libboost-headers (~174 MB) into every runtime install
# even though no Boost DLL is ever loaded. Both edits are idempotent and
# fail loudly if the expected upstream state is not found exactly once.
#
# 1. cpp/dolfinx/CMakeLists.txt: link Boost::headers PRIVATE instead of
#    PUBLIC so the installed DOLFINXTargets.cmake no longer references Boost.
# 2. cpp/cmake/templates/DOLFINXConfig.cmake.in: drop the Boost discovery
#    block so loading DOLFINXConfig.cmake needs no Boost installation.
#
# The top-level cpp/CMakeLists.txt find_package(Boost) stays, so the library
# itself still compiles with Boost headers available privately.

param([Parameter(Mandatory = $true)][string]$SrcDir)

$ErrorActionPreference = 'Stop'

$LinkOld = "# Boost`ntarget_link_libraries(dolfinx PUBLIC Boost::headers)`n"
$LinkNew = "# Boost`ntarget_link_libraries(dolfinx PRIVATE Boost::headers)`n"

$ConfigOld = @(
    'if(POLICY CMP0167)',
    '  cmake_policy(SET CMP0167 NEW)  # Boost CONFIG mode',
    'endif()',
    'if(POLICY CMP0144)',
    '  cmake_policy(SET CMP0144 NEW)  # https://cmake.org/cmake/help/latest/policy/CMP0144.html',
    'endif()',
    '',
    '# Check for Boost',
    'if(DEFINED ENV{BOOST_ROOT} OR DEFINED BOOST_ROOT)',
    '  set(Boost_NO_SYSTEM_PATHS on)',
    'endif()',
    'set(Boost_USE_MULTITHREADED $ENV{BOOST_USE_MULTITHREADED})',
    'set(Boost_VERBOSE TRUE)',
    'find_package(Boost 1.70 REQUIRED)',
    ''
) -join "`n"
$ConfigNew = @(
    'if(POLICY CMP0144)',
    '  cmake_policy(SET CMP0144 NEW)  # https://cmake.org/cmake/help/latest/policy/CMP0144.html',
    'endif()',
    ''
) -join "`n"

function Read-Lf([string]$Path) {
    ([IO.File]::ReadAllText($Path)) -replace "`r`n", "`n"
}

function Fix-Link([string]$Dir) {
    $path = Join-Path $Dir 'cpp\dolfinx\CMakeLists.txt'
    $text = Read-Lf $path
    if ($text.Contains($LinkNew)) {
        if ($text.Contains($LinkOld)) { throw "$path is in a mixed state" }
        Write-Host 'cpp/dolfinx/CMakeLists.txt: private Boost link already applied'
        return
    }
    $count = ([regex]::Matches($text, [regex]::Escape($LinkOld))).Count
    if ($count -ne 1) { throw "${path}: expected 1 PUBLIC Boost::headers link, found $count" }
    [IO.File]::WriteAllText($path, $text.Replace($LinkOld, $LinkNew))
    Write-Host 'cpp/dolfinx/CMakeLists.txt: linked Boost::headers PRIVATE'
}

function Fix-Config([string]$Dir) {
    $path = Join-Path $Dir 'cpp\cmake\templates\DOLFINXConfig.cmake.in'
    $text = Read-Lf $path
    if (-not $text.Contains('find_package(Boost')) {
        if ($text.Contains($ConfigOld)) { throw "$path is in a mixed state" }
        Write-Host 'DOLFINXConfig.cmake.in: Boost discovery already removed'
        return
    }
    $count = ([regex]::Matches($text, [regex]::Escape($ConfigOld))).Count
    if ($count -ne 1) { throw "${path}: expected 1 Boost discovery block, found $count" }
    [IO.File]::WriteAllText($path, $text.Replace($ConfigOld, $ConfigNew))
    Write-Host 'DOLFINXConfig.cmake.in: removed Boost discovery block'
}

Fix-Link $SrcDir
Fix-Config $SrcDir

if ($env:BOOST_PRIVATE_FIX_SELFTEST -eq '1') {
    Fix-Link $SrcDir
    Fix-Config $SrcDir
}
