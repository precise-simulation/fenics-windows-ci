@echo on
setlocal

set "SOURCE=%SRC_DIR%"
set "DEST=%LIBRARY_PREFIX%\fenics-jit\backends\micro-clang"
if not exist "%SOURCE%\metadata.json" exit /b 1
if not exist "%SOURCE%\manifest.csv" exit /b 1
if not exist "%SOURCE%\micro_clang_runtime.py" exit /b 1

if exist "%DEST%" rmdir /s /q "%DEST%"
mkdir "%LIBRARY_PREFIX%\fenics-jit\backends"
if errorlevel 1 exit /b %errorlevel%
xcopy "%SOURCE%" "%DEST%\" /E /I /Y
if errorlevel 1 exit /b %errorlevel%

exit /b 0
