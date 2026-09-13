@echo on
setlocal
set "BACKEND=%PREFIX%\Library\fenics-jit\backends\tinycc"
set "RUNTIME=%PREFIX%\Library\fenics-jit\runtime"
set "SELECTOR=%RUNTIME%\fenics_jit_selector.py"
if not exist "%BACKEND%\tinycc_runtime.py" exit /b 1
if not exist "%SELECTOR%" exit /b 1
if exist "%PREFIX%\Library\fenics-jit\backends\llvm-mingw" exit /b 1
python -m py_compile "%BACKEND%\tinycc_adapter.py" "%BACKEND%\tinycc_runtime.py" "%BACKEND%\selftest.py" "%SELECTOR%"
if errorlevel 1 exit /b %errorlevel%
python "%BACKEND%\selftest.py" --backend-root "%BACKEND%" --work-dir "%TEMP%\fenics-jit-tinycc-package-test"
if errorlevel 1 exit /b %errorlevel%
python "%BACKEND%\tinycc_runtime.py" --self-test --backend-root "%BACKEND%"
if errorlevel 1 exit /b %errorlevel%
set "FENICS_JIT_COMPILER=tinycc"
python "%SELECTOR%"
if errorlevel 1 exit /b %errorlevel%
exit /b 0
