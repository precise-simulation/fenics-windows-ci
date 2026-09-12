@echo on
setlocal
set "BACKEND=%PREFIX%\Library\fenics-jit\backends\tinycc"
python "%BACKEND%\selftest.py" --backend-root "%BACKEND%" --work-dir "%TEMP%\fenics-jit-tinycc-package-test"
if errorlevel 1 exit /b %errorlevel%
exit /b 0
