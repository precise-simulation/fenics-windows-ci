@echo on
setlocal EnableDelayedExpansion

if defined SRC_DIR (
  set "SOURCE_DIR=%SRC_DIR%"
) else (
  set "SOURCE_DIR=%CD%"
)

set "SOURCE_ARCHIVE="
for /f "delims=" %%I in ('dir /b /a-d "%SOURCE_DIR%\dolfinx-*.tar.gz" 2^>nul') do (
  if defined SOURCE_ARCHIVE (
    echo More than one DOLFINx source archive found in "%SOURCE_DIR%"
    exit /b 1
  )
  set "SOURCE_ARCHIVE=%SOURCE_DIR%\%%I"
)
if not defined SOURCE_ARCHIVE (
  echo Missing DOLFINx source archive in "%SOURCE_DIR%"
  exit /b 1
)

tar.exe -xzf "%SOURCE_ARCHIVE%" --strip-components=1 ^
  --exclude="*/cpp/test/vcpkg.json" ^
  --exclude="*/python/COPYING" ^
  --exclude="*/python/COPYING.LESSER" ^
  --exclude="*/python/vcpkg.json" ^
  -C "%SOURCE_DIR%"
if errorlevel 1 exit /b 1

if not exist "%SOURCE_DIR%\COPYING" (
  echo Missing source file COPYING
  exit /b 1
)
if not exist "%SOURCE_DIR%\COPYING.LESSER" (
  echo Missing source file COPYING.LESSER
  exit /b 1
)
if not exist "%SOURCE_DIR%\cpp\vcpkg.json" (
  echo Missing source file cpp\vcpkg.json
  exit /b 1
)
if not exist "%SOURCE_DIR%\python" mkdir "%SOURCE_DIR%\python"
copy /y "%SOURCE_DIR%\COPYING" "%SOURCE_DIR%\python\COPYING" >nul
copy /y "%SOURCE_DIR%\COPYING.LESSER" "%SOURCE_DIR%\python\COPYING.LESSER" >nul
copy /y "%SOURCE_DIR%\cpp\vcpkg.json" "%SOURCE_DIR%\python\vcpkg.json" >nul
if errorlevel 1 exit /b 1

if exist "%SOURCE_DIR%\cpp\test\vcpkg.json" (
  echo Unexpected source file cpp\test\vcpkg.json
  exit /b 1
)
if not exist "%SOURCE_DIR%\python\COPYING" exit /b 1
if not exist "%SOURCE_DIR%\python\COPYING.LESSER" exit /b 1
if not exist "%SOURCE_DIR%\python\vcpkg.json" exit /b 1

exit /b 0
