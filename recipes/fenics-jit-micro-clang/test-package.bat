@echo on
setlocal

set "BACKEND=%PREFIX%\Library\fenics-jit\backends\micro-clang"
set "RUNTIME=%PREFIX%\Library\fenics-jit\runtime"
set "SELECTOR=%RUNTIME%\fenics_jit_selector.py"
if not exist "%BACKEND%\micro_clang_runtime.py" exit /b 1
if not exist "%BACKEND%\fenics_jit_runtime.py" exit /b 1
if not exist "%BACKEND%\metadata.json" exit /b 1
if not exist "%BACKEND%\manifest.csv" exit /b 1
if not exist "%SELECTOR%" exit /b 1
if exist "%PREFIX%\Library\fenics-jit\backends\llvm-mingw" exit /b 1
if exist "%PREFIX%\Library\fenics-jit\backends\tinycc" exit /b 1
python -m py_compile "%BACKEND%\micro_clang_runtime.py" "%BACKEND%\fenics_jit_runtime.py" "%SELECTOR%"
if errorlevel 1 exit /b %errorlevel%
set "FENICS_JIT_COMPILER=micro-clang"
python "%SELECTOR%"
if errorlevel 1 exit /b %errorlevel%
exit /b 0
