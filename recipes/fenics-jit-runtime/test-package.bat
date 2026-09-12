@echo on
setlocal

set "RUNTIME_HELPER=%LIBRARY_PREFIX%\fenics-jit\runtime\fenics_jit_runtime.py"
if not exist "%RUNTIME_HELPER%" exit /b 1
python -m py_compile "%RUNTIME_HELPER%"
if errorlevel 1 exit /b %errorlevel%

rem The shared runtime package must not pull either compiler backend into its
rem own payload/dependency test environment.
if exist "%LIBRARY_PREFIX%\fenics-jit\bin\x86_64-w64-mingw32-clang.exe" exit /b 1
if exist "%LIBRARY_PREFIX%\fenics-jit\backends\tinycc\tcc\tcc.exe" exit /b 1

exit /b 0
