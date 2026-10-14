@echo off
setlocal
cd /d "%~dp0"
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
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  start "" py -3 "%~dp0pew.py"
  exit /b
)
start "" python "%~dp0pew.py"
