@echo on
setlocal

set "JIT_ROOT=%LIBRARY_PREFIX%\fenics-jit"
set "JIT_BIN=%JIT_ROOT%\bin"
set "JIT_TARGET_LIB=%JIT_ROOT%\x86_64-w64-mingw32\lib"
set "CLANG=%JIT_BIN%\x86_64-w64-mingw32-clang.exe"

if not exist "%CLANG%" exit /b 1
if not exist "%JIT_BIN%\ld.lld.exe" exit /b 1
if not exist "%JIT_TARGET_LIB%" exit /b 1
if not exist "%JIT_TARGET_LIB%\libunwind.a" exit /b 1
if not exist "%JIT_ROOT%\include\io.h" exit /b 1
if not exist "%JIT_ROOT%\lib\clang" exit /b 1
if not exist "%JIT_ROOT%\lib\python\libpython3.a" exit /b 1
if not exist "%JIT_ROOT%\lib\python\libpython312.a" exit /b 1
if not exist "%JIT_ROOT%\lib\python\libpython313.a" exit /b 1
if not exist "%JIT_ROOT%\lib\python\libpython314.a" exit /b 1
if not exist "%JIT_ROOT%\manifest.csv" exit /b 1
if not exist "%JIT_ROOT%\metadata.json" exit /b 1
if not exist "%JIT_ROOT%\minimization-stage-w.json" exit /b 1
if not exist "%JIT_ROOT%\minimization-stage-ac.json" exit /b 1
if not exist "%JIT_ROOT%\minimization-stage-ad.json" exit /b 1
if not exist "%JIT_ROOT%\minimization-stage-ae.json" exit /b 1
if not exist "%JIT_ROOT%\minimization-stage-af.json" exit /b 1
if not exist "%JIT_ROOT%\minimization-stage-ag.json" exit /b 1
if not exist "%JIT_ROOT%\minimization-stage-ah.json" exit /b 1
if not exist "%JIT_ROOT%\minimization-stage-ai.json" exit /b 1
if not exist "%JIT_ROOT%\minimization-stage-aj.json" exit /b 1
if not exist "%JIT_ROOT%\minimization-stage-ak.json" exit /b 1
if not exist "%JIT_ROOT%\minimization-stage-al.json" exit /b 1
if not exist "%JIT_ROOT%\minimization-stage-am.json" exit /b 1
if not exist "%JIT_ROOT%\minimization-stage-an.json" exit /b 1
if not exist "%JIT_ROOT%\runtime\fenics_jit_runtime.py" exit /b 1
powershell.exe -NoProfile -Command "$meta = Get-Content -LiteralPath '%JIT_ROOT%\metadata.json' -Raw | ConvertFrom-Json; if ([string]$meta.minimization_stage -ne 'stage-an' -or [string]$meta.minimization_report -ne 'minimization-stage-an.json' -or [string]$meta.library_minimization_stage -ne 'stage-ab') { exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'mshtml*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'd3d*' -or $_.Name -like 'dxgi*' -or $_.Name -like 'dxcore*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'd2d*' -or $_.Name -like 'dwrite*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'uiautomation*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'windows.ui*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'windows.devices*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'windows.applicationmodel*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'windows.media*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'windows.storage*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'windows.graphics*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'windows.gaming*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'windows.foundation*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'windows.security*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'windows.networking*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'windows.data*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'windows.system*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'windows.globalization*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -like 'windows.management*' }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$names = @('sapi.h','sapi51.h','sapi51.idl','sapi53.h','sapi53.idl','sapi54.h','sapi54.idl'); $bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -in $names }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$names = @('gl.h','glaux.h','glcorearb.h','glext.h','glu.h','glxext.h','wgl.h','wglext.h'); $bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include\GL' -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -in $names }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
if exist "%JIT_ROOT%\include\ddk" exit /b 1
powershell.exe -NoProfile -Command "$names = @('msxml.h','msxml.idl','msxml2.h','msxml2.idl','msxml2did.h','msxml6.h','msxml6.idl','msxml6did.h','msxmldid.h'); $bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -in $names }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$names = @('mfapi.h','mfcaptureengine.h','mfcaptureengine.idl','mfd3d12.h','mfd3d12.idl','mferror.h','mfidl.h','mfidl.idl','mfmediacapture.h','mfmediacapture.idl','mfmediaengine.h','mfmediaengine.idl','mfmp2dlna.h','mfobjects.h','mfobjects.idl','mfplay.h','mfplay.idl','mfreadwrite.h','mfreadwrite.idl','mftransform.h','mftransform.idl'); $bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -in $names }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$names = @('wmsdk.h','wmsdkidl.h','wmsdkidl.idl'); $bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -in $names }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$names = @('wmp.h','wmp.idl','wmpids.h','wmprealestate.h','wmprealestate.idl','wmpservices.h','wmpservices.idl'); $bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -in $names }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$names = @('windows.perception.h','windows.perception.idl','windows.perception.spatial.h','windows.perception.spatial.idl','windows.perception.spatial.surfaces.h','windows.perception.spatial.surfaces.idl'); $bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -in $names }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$names = @('strmif.h','strmif.idl'); $bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -in $names }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$names = @('tuner.h','tuner.idl'); $bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -in $names }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -Command "$names = @('xpsdigitalsignature.h','xpsdigitalsignature.idl','xpsobjectmodel.h','xpsobjectmodel.idl','xpsobjectmodel_1.h','xpsobjectmodel_1.idl','xpsprint.h','xpsprint.idl','xpsrassvc.h','xpsrassvc.idl'); $bad = @(Get-ChildItem -LiteralPath '%JIT_ROOT%\include' -File | Where-Object { $_.Name -in $names }); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1
if exist "%JIT_ROOT%\include\gdiplus" exit /b 1
if exist "%JIT_ROOT%\include\gdiplus.h" exit /b 1

powershell.exe -NoProfile -Command "$files = @(Get-ChildItem -LiteralPath '%JIT_BIN%' -File); $bad = @($files.Where({$_.Name -match '^(?:aarch64|arm64ec|armv7|i686)-w64-mingw32(?:uwp)?(?:-|$)'})); if ($bad.Count -ne 0) { $bad.FullName; exit 1 }"
if errorlevel 1 exit /b 1

powershell.exe -NoProfile -Command "$bad = @(); foreach ($p in @('%JIT_ROOT%\include\c++','%JIT_ROOT%\include\libunwind.h','%JIT_ROOT%\include\libunwind.modulemap')) { if (Test-Path -LiteralPath $p) { $bad += $p } }; $drivers = @(); foreach ($f in @(Get-ChildItem -LiteralPath '%JIT_BIN%' -File)) { if ($f.Name -match '^(?:(?:c|g|clang)\+\+|x86_64-w64-mingw32(?:uwp)?-(?:c|g|clang)\+\+)(?:\.exe)?$') { $drivers += $f } }; $runtime = @(); foreach ($d in @('%JIT_ROOT%\x86_64-w64-mingw32\bin','%JIT_TARGET_LIB%')) { if (Test-Path -LiteralPath $d) { foreach ($f in @(Get-ChildItem -LiteralPath $d -File)) { if ($f.Name -match '^libc\+\+' -or ($f.Name -match '^libunwind' -and $f.Name -ne 'libunwind.a')) { $runtime += $f } } } }; if ($bad.Count -ne 0 -or $drivers.Count -ne 0 -or $runtime.Count -ne 0) { $bad; $drivers.FullName; $runtime.FullName; exit 1 }"
if errorlevel 1 exit /b 1

for %%f in (clang-23.exe ld.lld.exe llvm-readobj.exe llvm-dlltool.exe) do if not exist "%JIT_BIN%\%%f" exit /b 1
for %%f in (clangd.exe clang-tidy.exe lldb.exe lldb-server.exe llvm-objdump.exe llvm-profdata.exe llvm-strip.exe) do if exist "%JIT_BIN%\%%f" exit /b 1

set "CLANG_RUNTIME=%JIT_ROOT%\lib\clang\23\lib"
if exist "%CLANG_RUNTIME%\linux" exit /b 1
if not exist "%CLANG_RUNTIME%\windows\libclang_rt.builtins-x86_64.a" exit /b 1
powershell.exe -NoProfile -Command "$files = @(Get-ChildItem -LiteralPath '%CLANG_RUNTIME%\windows' -Recurse -File); if ($files.Count -ne 1 -or $files[0].Name -ne 'libclang_rt.builtins-x86_64.a') { $files.FullName; exit 1 }"
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
