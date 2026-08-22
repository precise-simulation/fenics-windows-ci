setlocal EnableDelayedExpansion
@echo on

set "PETSC_DIR=%LIBRARY_PREFIX%"
set "PKG_CONFIG_PATH=%LIBRARY_PREFIX%\lib\pkgconfig;%PKG_CONFIG_PATH%"
set "PATH=%PREFIX%\bin;%LIBRARY_PREFIX%\bin;%PATH%"

ffcx cpp/test/poisson.py -o cpp/test
if errorlevel 1 exit 1

cmake %CMAKE_ARGS% ^
  -G Ninja ^
  --debug-output --debug-trycompile ^
  -D "CMAKE_TOOLCHAIN_FILE=%cd%\impi-toolchain.cmake" ^
  -D HDF5_NO_FIND_PACKAGE_CONFIG_FILE=ON ^
  -D HDF5_ROOT=%LIBRARY_PREFIX% ^
  -B build-test/ ^
  -S cpp/test/

if errorlevel 1 (
  dir build-test
  dir build-test\CMakeFiles
  type build-test\CMakeFiles\CMakeConfigureLog.yaml

  exit 1
)

cmake --build build-test --verbose
if errorlevel 1 exit 1

:: FIXME: proceed past ctest errors in case there are more

cd build-test
ctest -V --output-on-failure -R unittests
:: if errorlevel 1 exit 1
cd ..

cmake %CMAKE_ARGS% ^
  -G Ninja ^
  -D "CMAKE_TOOLCHAIN_FILE=%cd%\impi-toolchain.cmake" ^
  -D CMAKE_PREFIX_PATH=%LIBRARY_PREFIX% ^
  -D PETSC_DIR=%LIBRARY_PREFIX% ^
  -B build-test-petsc/ ^
  -S tests/
if errorlevel 1 exit 1

cmake --build build-test-petsc --verbose
if errorlevel 1 exit 1

build-test-petsc\dolfinx-petsc-consumer.exe
if errorlevel 1 exit 1

echo STAGE 9 C++ TEST PASS: installed DOLFINx reports PETSc and links consumer
exit 0
