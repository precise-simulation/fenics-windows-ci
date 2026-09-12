@echo on
setlocal

set "RUNTIME_DIR=%LIBRARY_PREFIX%\fenics-jit\runtime"
if exist "%RUNTIME_DIR%" rmdir /s /q "%RUNTIME_DIR%"
mkdir "%RUNTIME_DIR%"
if errorlevel 1 exit /b %errorlevel%

copy /y "%RECIPE_DIR%\fenics_jit_runtime.py" "%RUNTIME_DIR%\fenics_jit_runtime.py"
if errorlevel 1 exit /b %errorlevel%

exit /b 0
