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

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-v-windows-globalization.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-w-windows-management.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-x-directx-libraries.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-y-legacy-msvc-libraries.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-z-onecore-uwp-libraries.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-aa-nanosrv-headless-libraries.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-ab-optional-windows-api-libraries.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-ac-speech-api-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-ad-opengl-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-ae-ddk-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-af-msxml-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-ag-media-foundation-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-ah-windows-media-sdk-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-ai-windows-media-player-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-aj-windows-perception-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-ak-directshow-strmif-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-al-broadcast-tuner-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-am-xps-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-an-gdiplus-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-ao-directshow-qedit-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-ap-directshow-amstream-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-aq-enhanced-video-renderer-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-ar-task-scheduler-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-as-windows-update-agent-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-at-directshow-dvd-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-au-directshow-vmr9-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-av-directshow-amvideo-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\stage-aw-bda-interface-headers.ps1"
if errorlevel 1 exit /b %errorlevel%

rem Phase 4B package ownership: keep the proven Stage I-AW minimization staging
rem path unchanged, then move the complete payload under the LLVM backend root.
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RECIPE_DIR%\relocate-backend.ps1"
if errorlevel 1 exit /b %errorlevel%

exit /b 0
