@echo on
setlocal
set "BACKEND=%PREFIX%\Library\fenics-jit\backends\tinycc"
if not exist "%BACKEND%\tinycc_runtime.py" exit /b 1
python -m py_compile "%BACKEND%\tinycc_adapter.py" "%BACKEND%\tinycc_runtime.py" "%BACKEND%\selftest.py"
if errorlevel 1 exit /b %errorlevel%
python "%BACKEND%\selftest.py" --backend-root "%BACKEND%" --work-dir "%TEMP%\fenics-jit-tinycc-package-test"
if errorlevel 1 exit /b %errorlevel%
python "%BACKEND%\tinycc_runtime.py" --self-test --backend-root "%BACKEND%"
if errorlevel 1 exit /b %errorlevel%
exit /b 0
