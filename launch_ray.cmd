@echo off
cd /d "%~dp0"
rem Use the first Python environment that exists: project venv, then a conda env named "ray".
for %%P in (
  ".venv\Scripts\pythonw.exe"
  "%USERPROFILE%\anaconda3\envs\ray\pythonw.exe"
  "%USERPROFILE%\miniconda3\envs\ray\pythonw.exe"
  "%LOCALAPPDATA%\anaconda3\envs\ray\pythonw.exe"
  "%LOCALAPPDATA%\miniconda3\envs\ray\pythonw.exe"
  "%PROGRAMDATA%\anaconda3\envs\ray\pythonw.exe"
) do (
  if exist %%P (
    start "" %%P "%~dp0pew.py"
    exit /b
  )
)
start "" pyw -3 "%~dp0pew.py"
