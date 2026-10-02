@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
".venv\Scripts\python.exe" -X utf8 -m pytest tests_v3 tests -q
set "AMDFM_VERIFY_EXIT=%errorlevel%"
if not "%AMDFM_VERIFY_EXIT%"=="0" goto finished
".venv\Scripts\python.exe" -X utf8 verify_legacy.py
set "AMDFM_VERIFY_EXIT=%errorlevel%"
:finished
if not "%AMDFM_VERIFY_EXIT%"=="0" echo Verification failed. See the error above.
pause
exit /b %AMDFM_VERIFY_EXIT%
