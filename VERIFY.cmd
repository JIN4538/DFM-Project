@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -X utf8 -m pytest tests_v3 tests -q
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -X utf8 verify_legacy.py
pause
