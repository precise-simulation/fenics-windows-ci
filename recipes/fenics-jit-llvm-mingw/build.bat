@echo on
setlocal

rem rattler build activation can replace PSModulePath with conda-only paths.
rem Restore the inbox Windows PowerShell modules used by the staging script.
set "PSModulePath=%SystemRoot%\System32\WindowsPowerShell\v1.0\Modules"

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-toolchain.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-i-ui-automation.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-j-windows-ui.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-k-windows-devices.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-l-windows-applicationmodel.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-m-windows-media.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-n-windows-storage.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-o-windows-graphics.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-p-windows-gaming.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-q-windows-foundation.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-r-windows-security.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-s-windows-networking.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-t-windows-data.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-u-windows-system.ps1"
if errorlevel 1 exit /b %errorlevel%

exit /b 0
