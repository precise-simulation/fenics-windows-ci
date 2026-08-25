setlocal EnableDelayedExpansion
@echo on

set "CFLAGS=!CFLAGS! /wd4305"
set "OPENBLAS_NUM_THREADS=1"
set "PETSC_DIR=%PREFIX%\Library"
set "PATH=%PREFIX%\bin;%PREFIX%\Library\bin;%PATH%"
set "MPI_TEST_PATH=%PREFIX%\bin;%PREFIX%\Scripts;%PREFIX%\Library\bin;%SystemRoot%\system32;%SystemRoot%"
set "MPI_PYTHONPATH=%PREFIX%\Lib\site-packages"
pip check
if errorlevel 1 exit 1

:: test packaging
pytest -vs test_dolfinx.py
if errorlevel 1 exit 1

python tests\test_windows_petsc.py
if errorlevel 1 exit 1

set "PETSC_TEST_OUTPUT=%TEMP%\dolfinx-stage9-petsc-%RANDOM%.txt"
for /L %%N in (1,1,10) do (
  echo == MPI stability attempt %%N/10 ==
  mpiexec.exe -localonly -n 2 -env PATH "%MPI_TEST_PATH%" -env PYTHONPATH "%MPI_PYTHONPATH%" "%PYTHON%" tests\test_windows_petsc.py > "%PETSC_TEST_OUTPUT%" 2>&1
  if errorlevel 1 (
    type "%PETSC_TEST_OUTPUT%"
    exit /b 1
  )
  findstr /i /c:"STAGE 9 PETSC PASS" "%PETSC_TEST_OUTPUT%" >nul
  findstr /i /c:"STAGE 9 MUMPS PASS" "%PETSC_TEST_OUTPUT%" >nul
  findstr /i /c:"STAGE 9 METIS PASS" "%PETSC_TEST_OUTPUT%" >nul
  if errorlevel 1 exit /b 1
)

:: two-rank dolfinx mesh partitioning x10: PT-Scotch heap corruption guard.
:: int64 PT-SCOTCH crashed ~90%% of these; require clean exit AND rank output.
set "DOLFINX_REPRO=from mpi4py import MPI; import dolfinx.mesh as m; d=m.create_unit_square(MPI.COMM_WORLD,8,8); print('ok', d.topology.index_map(2).size_local)"
set "DOLFINX_TEST_OUTPUT=%TEMP%\dolfinx-stage9-repro-%RANDOM%.txt"
for /L %%N in (1,1,10) do (
  echo == dolfinx partitioning stability attempt %%N/10 ==
  mpiexec.exe -localonly -n 2 -env PATH "%MPI_TEST_PATH%" -env PYTHONPATH "%MPI_PYTHONPATH%" "%PYTHON%" -c "%DOLFINX_REPRO%" > "%DOLFINX_TEST_OUTPUT%" 2>&1
  if errorlevel 1 (
    type "%DOLFINX_TEST_OUTPUT%"
    exit /b 1
  )
  findstr /c:"ok" "%DOLFINX_TEST_OUTPUT%" >nul
  if errorlevel 1 exit /b 1
)

:: exercise a demo
cd python/demo
:: pytest --mpiexec=mpiexec -vs -k demo_poisson test.py
:: if errorlevel 1 exit 1

:: run some tests
cd ../test
:: subset of tests should exercise dependencies, solvers, partitioners
set TESTS="unit/fem/test_fem_pipeline.py unit/mesh/test_mesh_partitioners.py"
pytest -v -m "not petsc4py and not adios2" unit
if errorlevel 1 exit 1

mpiexec -n 2 pytest -v -k "not test_discrete_curl and not test_mesh_single_process_distribution" -m "not petsc4py and not adios2" unit
if errorlevel 1 exit 1

for /f "delims=" %%I in ('powershell.exe -NoProfile -Command "$p = Get-ChildItem -LiteralPath '%PREFIX%\Lib\site-packages\dolfinx' -Filter 'cpp*.pyd' | Select-Object -First 1 -ExpandProperty FullName; if ($p) { $p }"') do set "DOLFINX_EXTENSION=%%I"
if not defined DOLFINX_EXTENSION (
  echo Missing installed DOLFINx Python extension
  exit 1
)
dumpbin /dependents "%DOLFINX_EXTENSION%" > "%TEMP%\dolfinx-extension-dependents.txt"
if errorlevel 1 exit 1
powershell.exe -NoProfile -Command "$t = Get-Content -Raw '%TEMP%\dolfinx-extension-dependents.txt'; if ($t -notmatch '(?i)(?:lib)?dolfinx\.dll') { exit 1 }; if ($t -match '(?i)cygwin1\.dll') { exit 1 }"
if errorlevel 1 exit 1

for /f "delims=" %%I in ('powershell.exe -NoProfile -Command "$p = Get-ChildItem -LiteralPath '%PREFIX%\Library\bin' -Filter '*dolfinx*.dll' | Select-Object -First 1 -ExpandProperty FullName; if ($p) { $p }"') do set "DOLFINX_DLL=%%I"
if not defined DOLFINX_DLL (
  echo Missing installed DOLFINx DLL
  exit 1
)
dumpbin /dependents "%DOLFINX_DLL%" > "%TEMP%\dolfinx-dependents.txt"
if errorlevel 1 exit 1
powershell.exe -NoProfile -Command "$t = Get-Content -Raw '%TEMP%\dolfinx-dependents.txt'; if ($t -notmatch '(?i)libpetsc\.dll') { exit 1 }; if ($t -match '(?i)cygwin1\.dll') { exit 1 }"
if errorlevel 1 exit 1

rem Scan DOLFINx-owned files for build-prefix leakage. Third-party pkgconfig
rem files (e.g. conda-forge's hdf4, which ships a D:\bld\... Libs.private) are
rem not ours to fix and are excluded.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$patterns = @([regex]::Escape($env:SRC_DIR), [regex]::Escape($env:BUILD_PREFIX), [regex]::Escape($env:RECIPE_DIR), '(?i)[A-Z]:[\\/].*[\\/](?:bld|build(?:_env)?|src|source|work|h_env)(?:[\\/]|$)'); $roots = @((Join-Path $env:PREFIX 'Lib/site-packages/dolfinx'), (Join-Path $env:PREFIX 'Library/lib/cmake/dolfinx'), (Join-Path $env:PREFIX 'Library/lib/pkgconfig'), (Join-Path $env:PREFIX 'Library/include/dolfinx')); $files = foreach ($r in $roots) { if (Test-Path -LiteralPath $r) { Get-ChildItem -LiteralPath $r -Recurse -File | Where-Object { $_.Extension -in '.py', '.pyi', '.cmake', '.pc', '.h', '.txt' } } }; $files = $files | Where-Object { $_.Directory.Name -ne 'pkgconfig' -or $_.Name -match '^(dolfinx|petsc)' }; $leaks = foreach ($f in $files) { $t = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($f.FullName)); foreach ($p in $patterns) { if ($p -and [regex]::IsMatch($t, $p)) { $f.FullName; break } } }; if ($leaks) { $leaks; exit 1 }"
if errorlevel 1 exit 1

echo STAGE 9 TEST PASS: DOLFINx PETSc import, Poisson, DLL linkage, and metadata
