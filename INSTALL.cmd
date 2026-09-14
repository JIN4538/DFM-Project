@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
set "AMDFM_INSTALL_EXIT=1"
set "AMDFM_INSTALL_PYTHON="
if not exist "logs" mkdir "logs" 2>nul
echo [%date% %time%] Starting AM-DFM installation >>"logs\install-bootstrap.log"

if exist ".venv\Scripts\python.exe" call :probe ".venv\Scripts\python.exe"
if defined AMDFM_INSTALL_PYTHON goto selected_python
if defined AM_DFM_PYTHON call :probe "%AM_DFM_PYTHON%"
if defined AMDFM_INSTALL_PYTHON goto selected_python

py -3.12 -c "import sys; sys.exit(sys.version_info[:2] != (3,12) or sys.maxsize <= 2**32)" >>"logs\install-bootstrap.log" 2>&1
if not errorlevel 1 goto python312
py -3.13 -c "import sys; sys.exit(sys.version_info[:2] != (3,13) or sys.maxsize <= 2**32)" >>"logs\install-bootstrap.log" 2>&1
if not errorlevel 1 goto python313

for /f "delims=" %%P in ('where python.exe 2^>nul ^| findstr /i /v "\\WindowsApps\\"') do if not defined AMDFM_INSTALL_PYTHON call :probe "%%P"
if defined AMDFM_INSTALL_PYTHON goto selected_python
echo.
echo [FAILED] Python 3.12 or 3.13, 64-bit, could not be found.
echo Install Python from https://www.python.org/downloads/windows/ then run INSTALL.cmd again.
echo Or set AM_DFM_PYTHON to the full path of an existing supported python.exe.
echo Details: "%CD%\logs\install-bootstrap.log"
goto finish

:selected_python
"%AMDFM_INSTALL_PYTHON%" -X utf8 "scripts\install_environment.py" %*
set "AMDFM_INSTALL_EXIT=%errorlevel%"
goto finish

:python312
py -3.12 -X utf8 "scripts\install_environment.py" %*
set "AMDFM_INSTALL_EXIT=%errorlevel%"
goto finish

:python313
py -3.13 -X utf8 "scripts\install_environment.py" %*
set "AMDFM_INSTALL_EXIT=%errorlevel%"
goto finish

:probe
"%~1" -c "import sys; sys.exit(sys.version_info[:2] not in ((3,12),(3,13)) or sys.maxsize <= 2**32)" >>"logs\install-bootstrap.log" 2>&1
if not errorlevel 1 set "AMDFM_INSTALL_PYTHON=%~1"
exit /b

:finish
echo.
if not "%AMDFM_INSTALL_EXIT%"=="0" echo Installation did not complete. The error is shown above; logs are in the logs folder.
for %%A in (%*) do if /i "%%~A"=="--no-pause" goto return_code
echo Press any key to close this window.
pause >nul
:return_code
exit /b %AMDFM_INSTALL_EXIT%
