@echo off
setlocal
cd /d "C:\Users\moksh\OneDrive\Documents\portfolio\pew"
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 "C:\Users\moksh\OneDrive\Documents\portfolio\pew\pew.py" --auto
) else (
  python "C:\Users\moksh\OneDrive\Documents\portfolio\pew\pew.py" --auto
)
