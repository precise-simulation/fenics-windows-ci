@echo on
setlocal
set "PSModulePath=%SystemRoot%\System32\WindowsPowerShell\v1.0\Modules"
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\build.ps1"
if errorlevel 1 exit /b %errorlevel%
exit /b 0
