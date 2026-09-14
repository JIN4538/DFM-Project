@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run INSTALL.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -m streamlit run app.py --server.port 8507
