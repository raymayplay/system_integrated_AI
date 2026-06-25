@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_EXE=C:\Users\moksh\OneDrive\Documents\.venv-1\Scripts\python.exe"
if exist "%PYTHON_EXE%" (
  start "HandleAI Moksh" "%PYTHON_EXE%" "%~dp0pew.py"
) else (
  where py >nul 2>nul
  if %ERRORLEVEL% EQU 0 (
    start "HandleAI Moksh" py -3 "%~dp0pew.py"
  ) else (
    start "HandleAI Moksh" python "%~dp0pew.py"
  )
)
