@echo on
setlocal EnableExtensions

set "PETSC_DIR=%PREFIX%\Library"
set "PATH=%PREFIX%\Library\bin;%PATH%"
set "PETSC4PY_BUILD_PYSABI="
set "CL=/Zc:preprocessor"

"%PYTHON%" conf/cythonize.py
if errorlevel 1 exit /b 1
"%PYTHON%" -m pip -v install --no-deps .
if errorlevel 1 exit /b 1

endlocal
