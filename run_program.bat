@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "PYTHON_EXE="
cd /d "%ROOT_DIR%source_files"

call :find_python
if not defined PYTHON_EXE goto :python_not_found

call "%PYTHON_EXE%" -c "import serial, minimalmodbus, PyQt5, pyqtgraph" >nul 2>nul
if errorlevel 1 goto :missing_deps

call "%PYTHON_EXE%" pps_GUI_program.py
goto :end

:find_python
for /d %%D in ("%LocalAppData%\Programs\Python\Python*") do (
    if exist "%%~fD\python.exe" set "PYTHON_EXE=%%~fD\python.exe"
)
if defined PYTHON_EXE exit /b 0

for /d %%D in ("%ProgramFiles%\Python*") do (
    if exist "%%~fD\python.exe" set "PYTHON_EXE=%%~fD\python.exe"
)
if defined PYTHON_EXE exit /b 0

where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info[0] == 3 else 1)" >nul 2>nul
    if not errorlevel 1 (
        for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%I"
        exit /b 0
    )
)

where py >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%I"
)
exit /b 0

:python_not_found
echo Python 3 not found.
echo Install any supported Python 3 version and then run this file again.
pause
goto :end

:missing_deps
echo Required Python packages are missing for:
echo %PYTHON_EXE%
echo Run "%ROOT_DIR%install_requirements.bat" first.
pause

:end
endlocal
