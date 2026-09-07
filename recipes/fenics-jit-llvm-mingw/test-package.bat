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
if not exist "%JIT_ROOT%\minimization-stage-b.json" exit /b 1
if not exist "%JIT_ROOT%\runtime\fenics_jit_runtime.py" exit /b 1

powershell.exe -NoProfile -Command "$files = @(Get-ChildItem -LiteralPath '%JIT_BIN%' -File); $bad = @($files.Where({$_.Name -match '^(?:aarch64|arm64ec|armv7|i686)-w64-mingw32(?:uwp)?(?:-|$)'})); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1

powershell.exe -NoProfile -Command "$bad = @(); foreach ($p in @('%JIT_ROOT%\include\c++','%JIT_ROOT%\include\libunwind.h','%JIT_ROOT%\include\libunwind.modulemap')) { if (Test-Path -LiteralPath $p) { $bad += $p } }; $drivers = @(Get-ChildItem -LiteralPath '%JIT_BIN%' -File | Where-Object { $_.Name -match '^(?:(?:c|g|clang)\+\+|x86_64-w64-mingw32(?:uwp)?-(?:c|g|clang)\+\+)(?:\.exe)?

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
 }); $runtime = @(); foreach ($d in @('%JIT_ROOT%\x86_64-w64-mingw32\bin','%JIT_ROOT%\x86_64-w64-mingw32\lib')) { if (Test-Path -LiteralPath $d) { $runtime += @(Get-ChildItem -LiteralPath $d -File | Where-Object { $_.Name -match '^(?:libc\+\+|libunwind)' }) } }; if ($bad.Count -ne 0 -or $drivers.Count -ne 0 -or $runtime.Count -ne 0) { $bad; $drivers.FullName; $runtime.FullName; exit 1 }"
if errorlevel 1 exit /b 1

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
