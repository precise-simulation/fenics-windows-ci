@echo on
setlocal EnableExtensions
set "OPENBLAS_NUM_THREADS=1"

if not defined PREFIX (
  echo PREFIX is not set
  exit /b 1
)
if not defined PYTHON (
  echo PYTHON is not set
  exit /b 1
)

set "PATH=%PREFIX%\bin;%PREFIX%\Library\bin;%PATH%"
set "PETSC_DIR=%PREFIX%\Library"
set "TEST_SOURCE=%CD%\tests"
set "TEST_BUILD=%TEMP%\petsc4py-windows-test-%RANDOM%"
set "MPI_TEST_PATH=%PREFIX%\bin;%PREFIX%\Scripts;%PREFIX%\Library\bin;%SystemRoot%\system32;%SystemRoot%"
set "MPI_PYTHONPATH=%PREFIX%\Lib\site-packages"
set "SERIAL_OUTPUT=%TEST_BUILD%\serial-output.txt"
set "MPI_OUTPUT=%TEST_BUILD%\mpi-output.txt"

if not exist "%TEST_SOURCE%\test_windows_ksp.py" (
  echo Missing Windows petsc4py test source
  exit /b 1
)

if not exist "%TEST_BUILD%" mkdir "%TEST_BUILD%"

python -m pip check > "%TEST_BUILD%\pip-check.txt" 2>&1
if errorlevel 1 (
  echo PETSC4PY_PIP_CHECK_OUTPUT_BEGIN
  type "%TEST_BUILD%\pip-check.txt"
  echo PETSC4PY_PIP_CHECK_OUTPUT_END
  exit /b 1
)

python "%TEST_SOURCE%\test_windows_ksp.py" > "%SERIAL_OUTPUT%" 2>&1
if errorlevel 1 (
  echo PETSC4PY_SERIAL_TEST_OUTPUT_BEGIN
  type "%SERIAL_OUTPUT%"
  echo PETSC4PY_SERIAL_TEST_OUTPUT_END
  exit /b 1
)
findstr /i /c:"STAGE 7 KSP PASS" "%SERIAL_OUTPUT%" >nul
if errorlevel 1 (
  echo PETSC4PY_SERIAL_TEST_OUTPUT_BEGIN
  type "%SERIAL_OUTPUT%"
  echo PETSC4PY_SERIAL_TEST_OUTPUT_END
  exit /b 1
)

mpiexec.exe -localonly -n 2 -env PATH "%MPI_TEST_PATH%" -env PYTHONPATH "%MPI_PYTHONPATH%" "%PYTHON%" "%TEST_SOURCE%\test_windows_ksp.py" > "%MPI_OUTPUT%" 2>&1
if errorlevel 1 (
  echo PETSC4PY_MPI_TEST_OUTPUT_BEGIN
  type "%MPI_OUTPUT%"
  echo PETSC4PY_MPI_TEST_OUTPUT_END
  exit /b 1
)
findstr /i /c:"STAGE 7 KSP PASS" "%MPI_OUTPUT%" >nul
if errorlevel 1 (
  echo PETSC4PY_MPI_TEST_OUTPUT_BEGIN
  type "%MPI_OUTPUT%"
  echo PETSC4PY_MPI_TEST_OUTPUT_END
  exit /b 1
)

for /f "delims=" %%I in ('powershell.exe -NoProfile -Command "$p = Get-ChildItem -LiteralPath '%PREFIX%\Lib\site-packages\petsc4py\lib' -Filter 'PETSc*.pyd' | Select-Object -First 1 -ExpandProperty FullName; if ($p) { $p }"') do set "PETSC4PY_EXTENSION=%%I"
if not defined PETSC4PY_EXTENSION (
  echo Missing installed petsc4py extension
  exit /b 1
)

dumpbin /dependents "%PETSC4PY_EXTENSION%" > "%TEST_BUILD%\petsc4py.dependents.txt"
if errorlevel 1 exit /b 1
findstr /i /c:"libpetsc.dll" "%TEST_BUILD%\petsc4py.dependents.txt" >nul
if errorlevel 1 exit /b 1
findstr /i /c:"cygwin1.dll" "%TEST_BUILD%\petsc4py.dependents.txt" >nul
if not errorlevel 1 exit /b 1

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$patterns = @([regex]::Escape($env:SRC_DIR), [regex]::Escape($env:BUILD_PREFIX), [regex]::Escape($env:RECIPE_DIR)); $roots = @((Join-Path $env:PREFIX 'Lib/site-packages/petsc4py'), (Join-Path $env:PREFIX 'Library/lib/petsc'), (Join-Path $env:PREFIX 'Library/share/petsc')); $files = foreach ($r in $roots) { if (Test-Path -LiteralPath $r) { Get-ChildItem -LiteralPath $r -Recurse -File | Where-Object { $_.Extension -in '.py', '.pyi', '.cfg', '.h', '.pc', '.txt' } } }; $pc = Join-Path $env:PREFIX 'Library/lib/pkgconfig/PETSc.pc'; if (Test-Path -LiteralPath $pc) { $files += Get-Item -LiteralPath $pc }; $leaks = foreach ($f in $files) { $t = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($f.FullName)); foreach ($p in $patterns) { if ($p -and [regex]::IsMatch($t, $p)) { $f.FullName; break } } }; if ($leaks) { $leaks; exit 1 }"
if errorlevel 1 exit /b 1

echo STAGE 7 TEST PASS: petsc4py import, metadata, DLL linkage, and serial/two-rank KSP
endlocal
