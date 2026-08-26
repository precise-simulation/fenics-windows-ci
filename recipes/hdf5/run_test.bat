@echo on
setlocal EnableExtensions

if not defined PREFIX (
  echo PREFIX is not set
  exit /b 1
)

set "PATH=%PREFIX%\bin;%PREFIX%\Scripts;%PREFIX%\Library\bin;%PATH%"
set "CMAKE_PREFIX_PATH=%PREFIX%\Library"
set "TEST_SOURCE=%CD%\tests"
set "TEST_BUILD=%TEMP%\hdf5-consumer-%RANDOM%"
set "MPI_TEST_PATH=%PREFIX%\bin;%PREFIX%\Scripts;%PREFIX%\Library\bin;%SystemRoot%\system32;%SystemRoot%"

if not exist "%TEST_SOURCE%\CMakeLists.txt" (
  echo Missing HDF5 consumer test sources: %TEST_SOURCE%
  exit /b 1
)

findstr /r /i /c:"ENABLE_ROS3_VFD.*OFF" "%PREFIX%\Library\cmake\hdf5-config.cmake" >nul
if errorlevel 1 (
  echo HDF5 config does not disable ROS3 VFD
  exit /b 1
)

cmake -S "%TEST_SOURCE%" -B "%TEST_BUILD%" -G Ninja -DCMAKE_C_COMPILER=cl -DCMAKE_CXX_COMPILER=cl -DCMAKE_BUILD_TYPE=Release -DHDF5_DIR="%PREFIX%\Library\cmake"
if errorlevel 1 exit /b 1
cmake --build "%TEST_BUILD%" --config Release
if errorlevel 1 exit /b 1

"%TEST_BUILD%\hdf5-c-smoke.exe"
if errorlevel 1 exit /b 1
"%TEST_BUILD%\hdf5-cxx-smoke.exe"
if errorlevel 1 exit /b 1

set "MPI_OUTPUT=%TEST_BUILD%\mpi-output.txt"
mpiexec.exe -localonly -n 2 -env PATH "%MPI_TEST_PATH%" "%TEST_BUILD%\hdf5-mpi-smoke.exe" > "%MPI_OUTPUT%" 2>&1
if errorlevel 1 (
  type "%MPI_OUTPUT%"
  exit /b 1
)
findstr /i /c:"PASS MPI HDF5" "%MPI_OUTPUT%" >nul
if errorlevel 1 (
  type "%MPI_OUTPUT%"
  exit /b 1
)

set "HDF5_DEPENDENTS=%TEST_BUILD%\hdf5-dependents.txt"
dumpbin /dependents "%PREFIX%\Library\bin\hdf5.dll" > "%HDF5_DEPENDENTS%"
if errorlevel 1 exit /b 1
findstr /i /c:"impi.dll" "%HDF5_DEPENDENTS%" >nul
if errorlevel 1 exit /b 1
for %%D in (libcurl.dll libcrypto-3-x64.dll libssh2.dll psl-5.dll icuuc78.dll icudt78.dll) do (
  findstr /i /c:"%%D" "%HDF5_DEPENDENTS%" >nul
  if not errorlevel 1 (
    echo HDF5 unexpectedly depends on %%D
    exit /b 1
  )
)

set "ROS3_OUTPUT=%TEST_BUILD%\ros3-output.txt"
"%PREFIX%\Library\bin\h5dump.exe" --filedriver=ros3 http://127.0.0.1:9/no.h5 > "%ROS3_OUTPUT%" 2>&1
if not errorlevel 1 (
  echo ROS3 VFD unexpectedly accepted
  exit /b 1
)
findstr /i /c:"unable to set VFD" "%ROS3_OUTPUT%" >nul
if errorlevel 1 (
  type "%ROS3_OUTPUT%"
  exit /b 1
)

echo HDF5 ROS3-off C, C++, MPI, linkage, and unavailable-driver checks passed
endlocal
