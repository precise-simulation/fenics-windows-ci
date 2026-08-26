setlocal EnableDelayedExpansion
@echo on

call "%RECIPE_DIR%\prepare-dolfinx-source.bat"
if errorlevel 1 exit 1

rem MSVC + nanobind >=2.8 caster fix and Windows libpetsc.dll lookup fix
rem (see apply-caster-petsc-fix.py)
%PYTHON% "%RECIPE_DIR%\apply-caster-petsc-fix.py" "%SRC_DIR%"
if errorlevel 1 exit 1

set "CXXFLAGS=%CXXFLAGS% -DH5_BUILT_AS_DYNAMIC_LIB /MP2 /wd4244 /wd4267"
rem fenics-libdolfinx no longer exports Boost headers, but the wrapper
rem sources include boost headers directly (geometry.h, FunctionSpace.h),
rem so point the compiler at the host Boost explicitly.
set "CXXFLAGS=%CXXFLAGS% -I%LIBRARY_PREFIX%\include"
set "CMAKE_BUILD_PARALLEL_LEVEL=2"
set "PETSC_DIR=%LIBRARY_PREFIX%"
set "PKG_CONFIG_PATH=%LIBRARY_PREFIX%\lib\pkgconfig;%PKG_CONFIG_PATH%"
set "PATH=%LIBRARY_PREFIX%\bin;%PATH%"

set "SKBUILD_CMAKE_ARGS=-DCMAKE_PREFIX_PATH=%LIBRARY_PREFIX%;-DCMAKE_TOOLCHAIN_FILE=%RECIPE_DIR%\impi-toolchain.cmake;-DHDF5_NO_FIND_PACKAGE_CONFIG_FILE=ON;-DHDF5_ROOT=%LIBRARY_PREFIX%;-DPETSC_DIR=%LIBRARY_PREFIX%;-DCMAKE_MODULE_LINKER_FLAGS=/LIBPATH:%LIBRARY_PREFIX%\lib;-DCMAKE_SHARED_LINKER_FLAGS=/LIBPATH:%LIBRARY_PREFIX%\lib"
rem PETSc's external-lib metadata lists bare .lib names (mkl_*, impi); the
rem /LIBPATH flags above make sure they resolve at link time.
set PIP_DISABLE_PIP_VERSION_CHECK=1

rem The caster-petsc-msvc-nanobind.patch recipe patch fixes the MSVC
rem ambiguity in DOLFINx's PETSc casters; no nanobind header edits needed.

echo CXXFLAGS=!CXXFLAGS!
echo CMAKE_ARGS=!CMAKE_ARGS!
echo SKBUILD_CMAKE_ARGS=!SKBUILD_CMAKE_ARGS!

%PYTHON% -m pip install -v --no-deps --no-build-isolation ./python --config-settings=build.verbose=true
if errorlevel 1 exit 1
