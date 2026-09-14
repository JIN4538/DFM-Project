@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run INSTALL.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -m streamlit run app.py --server.port 8507
set "AMDFM_START_EXIT=%errorlevel%"
if not "%AMDFM_START_EXIT%"=="0" (
  echo App startup failed. See the error above.
  echo If port 8507 is already in use, open http://127.0.0.1:8507/
  pause
)
exit /b %AMDFM_START_EXIT%
