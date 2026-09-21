@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "AMDFM_NO_PAUSE=0"
for %%A in (%*) do if /i "%%~A"=="--no-pause" set "AMDFM_NO_PAUSE=1"
if not exist ".venv\Scripts\python.exe" (
  echo Run INSTALL.cmd first.
  if "%AMDFM_NO_PAUSE%"=="0" pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 scripts\start_review.py %*
set "AMDFM_START_EXIT=%errorlevel%"
if not "%AMDFM_START_EXIT%"=="0" (
  echo App startup failed. See the error above.
  if "%AMDFM_NO_PAUSE%"=="0" pause
)
exit /b %AMDFM_START_EXIT%
