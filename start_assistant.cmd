@echo off
setlocal
cd /d "%~dp0"
if exist "%USERPROFILE%\.venv\Scripts\pythonw.exe" (
  start "" "%USERPROFILE%\.venv\Scripts\pythonw.exe" "%~dp0pew.py"
  exit /b
)
where pyw >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  start "" pyw "%~dp0pew.py"
  exit /b
)
where pythonw >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  start "" pythonw "%~dp0pew.py"
  exit /b
)
start "" python "%~dp0pew.py"
