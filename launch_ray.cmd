@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "%~dp0pew.py"
) else (
  start "" pyw -3 "%~dp0pew.py"
)
