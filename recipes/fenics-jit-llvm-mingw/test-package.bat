@echo on
setlocal

set "JIT_ROOT=%LIBRARY_PREFIX%\fenics-jit"
set "JIT_BIN=%JIT_ROOT%\bin"
set "CLANG=%JIT_BIN%\x86_64-w64-mingw32-clang.exe"

if not exist "%CLANG%" exit /b 1
if not exist "%JIT_BIN%\ld.lld.exe" exit /b 1
if not exist "%JIT_ROOT%\x86_64-w64-mingw32\lib" exit /b 1
if not exist "%JIT_ROOT%\include\io.h" exit /b 1
if not exist "%JIT_ROOT%\lib\clang" exit /b 1
if not exist "%JIT_ROOT%\lib\python\libpython3.a" exit /b 1
if not exist "%JIT_ROOT%\lib\python\libpython312.a" exit /b 1
if not exist "%JIT_ROOT%\lib\python\libpython313.a" exit /b 1
if not exist "%JIT_ROOT%\lib\python\libpython314.a" exit /b 1
if not exist "%JIT_ROOT%\manifest.csv" exit /b 1
if not exist "%JIT_ROOT%\metadata.json" exit /b 1

"%CLANG%" --version
if errorlevel 1 exit /b 1

"%CLANG%" -dumpmachine > "%TEMP%\fenics-jit-target.txt"
if errorlevel 1 exit /b 1
findstr /i "x86_64" "%TEMP%\fenics-jit-target.txt"
if errorlevel 1 exit /b 1

> "%TEMP%\fenics-jit-smoke.c" echo __declspec(dllexport) int fenics_jit_answer(void) { return 42; }
"%CLANG%" -shared "%TEMP%\fenics-jit-smoke.c" -o "%TEMP%\fenics-jit-smoke.dll"
if errorlevel 1 exit /b 1
if not exist "%TEMP%\fenics-jit-smoke.dll" exit /b 1

exit /b 0
