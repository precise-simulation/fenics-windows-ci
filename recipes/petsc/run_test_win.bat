@echo on
setlocal EnableExtensions
rem proof requires no OpenMP runtime and no one-thread OMP workaround
set "OMP_NUM_THREADS="
set "OPENBLAS_NUM_THREADS=1"

if not defined PREFIX (
  echo PREFIX is not set
  exit /b 1
)

echo %PATH% | findstr /i /c:"cygwin" >nul
if not errorlevel 1 (
  echo Cygwin must not be present on the runtime PATH
  exit /b 1
)

set "PKG_CONFIG_PATH=%PREFIX%\Library\lib\pkgconfig"
set "CMAKE_PREFIX_PATH=%PREFIX%\Library"
set "TEST_SOURCE=%CD%\tests"
set "TEST_BUILD=%TEMP%\petsc-windows-test-%RANDOM%"
set "MPI_TEST_PATH=%PREFIX%\bin;%PREFIX%\Library\bin;%SystemRoot%\system32;%SystemRoot%"
set "MPI_OUTPUT=%TEST_BUILD%\mpi-output.txt"

if not exist "%TEST_SOURCE%\CMakeLists.txt" (
  echo Missing Windows package test sources: %TEST_SOURCE%
  exit /b 1
)
if not exist "%PREFIX%\Library\bin\libpetsc.dll" (
  echo Missing packaged PETSc DLL
  exit /b 1
)

findstr /i /c:"#define PETSC_HAVE_MUMPS 1" "%PREFIX%\Library\include\petscconf.h" >nul
if errorlevel 1 (
  echo PETSc was built without MUMPS
  exit /b 1
)
findstr /i /c:"#define PETSC_HAVE_METIS 1" "%PREFIX%\Library\include\petscconf.h" >nul
if errorlevel 1 (
  echo PETSc was built without METIS
  exit /b 1
)
if not exist "%PREFIX%\Library\include\metis.h" (
  echo Missing METIS header from runtime dependency
  exit /b 1
)
findstr /i /c:"#define IDXTYPEWIDTH 32" "%PREFIX%\Library\include\metis.h" >nul
if errorlevel 1 (
  echo METIS does not select 32-bit indices
  exit /b 1
)
for %%m in (dmumps mumps_common pord scalapack scalapack-F) do (
  if not exist "%PREFIX%\Library\lib\%%m.lib" (
    echo Missing static solver library: %%m.lib
    exit /b 1
  )
)

pkg-config --validate PETSc
if errorlevel 1 exit /b 1
pkg-config --cflags PETSc >nul
if errorlevel 1 exit /b 1
pkg-config --libs PETSc >nul
if errorlevel 1 exit /b 1

cmake -S "%TEST_SOURCE%" -B "%TEST_BUILD%" -G Ninja -DCMAKE_C_COMPILER=cl -DCMAKE_BUILD_TYPE=Release
if errorlevel 1 exit /b 1
cmake --build "%TEST_BUILD%" --config Release
if errorlevel 1 exit /b 1

"%TEST_BUILD%\ex1.exe"
if errorlevel 1 exit /b 1
mpiexec.exe -localonly -n 2 -env PATH "%MPI_TEST_PATH%" "%TEST_BUILD%\ex1.exe" > "%MPI_OUTPUT%" 2>&1
if errorlevel 1 exit /b 1
findstr /i /c:"KSP converged (reason" "%MPI_OUTPUT%" >nul
if errorlevel 1 exit /b 1

set "MUMPS_OPTS=-ksp_type preonly -pc_type lu -pc_factor_mat_solver_type mumps -mat_mumps_icntl_7 5 -ksp_error_if_not_converged"
"%TEST_BUILD%\ex1.exe" %MUMPS_OPTS%
if errorlevel 1 exit /b 1
mpiexec.exe -localonly -n 2 -env PATH "%MPI_TEST_PATH%" "%TEST_BUILD%\ex1.exe" %MUMPS_OPTS% > "%MPI_OUTPUT%" 2>&1
if errorlevel 1 exit /b 1
findstr /i /c:"KSP converged (reason" "%MPI_OUTPUT%" >nul
if errorlevel 1 exit /b 1

dumpbin /dependents "%TEST_BUILD%\ex1.exe" > "%TEST_BUILD%\ex1.dependents.txt"
if errorlevel 1 exit /b 1
findstr /i /c:"libpetsc.dll" "%TEST_BUILD%\ex1.dependents.txt" >nul
if errorlevel 1 exit /b 1
findstr /i /c:"cygwin1.dll" "%TEST_BUILD%\ex1.dependents.txt" >nul
if not errorlevel 1 exit /b 1

dumpbin /dependents "%PREFIX%\Library\bin\libpetsc.dll" > "%TEST_BUILD%\libpetsc.dependents.txt"
if errorlevel 1 exit /b 1
findstr /i /c:"impi.dll" "%TEST_BUILD%\libpetsc.dependents.txt" >nul
if errorlevel 1 exit /b 1
findstr /i /c:"openblas.dll" "%TEST_BUILD%\libpetsc.dependents.txt" >nul
if errorlevel 1 exit /b 1
findstr /i /c:"metis.dll" "%TEST_BUILD%\libpetsc.dependents.txt" >nul
if errorlevel 1 (
  echo libpetsc.dll does not depend on metis.dll
  exit /b 1
)
for %%d in (libiomp5md.dll libomp.dll vcomp cygwin1.dll) do (
  findstr /i /c:"%%d" "%TEST_BUILD%\libpetsc.dependents.txt" >nul
  if not errorlevel 1 (
    echo libpetsc.dll must not depend on %%d
    exit /b 1
  )
)

rem PETSc-owned installed link metadata must not reference an OpenMP runtime or flag
findstr /i /c:"libiomp5md" /c:"libomp" /c:"-fopenmp" "%PREFIX%\Library\lib\pkgconfig\PETSc.pc" >nul
if not errorlevel 1 (
  echo PETSc.pc references an OpenMP runtime or flag
  exit /b 1
)
findstr /i /s /c:"libiomp5md" /c:"libomp" /c:"-fopenmp" "%PREFIX%\Library\lib\petsc\*.*" >nul
if not errorlevel 1 (
  echo PETSc link metadata references an OpenMP runtime or flag
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TEST_SOURCE%\check_metadata.ps1" -Prefix "%PREFIX%"
if errorlevel 1 exit /b 1

echo Windows PETSc package interface, runtime, linkage, and metadata checks passed
endlocal
