@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -u stop.py %*
) else if exist "%USERPROFILE%\.conda\envs\qrushi\python.exe" (
    "%USERPROFILE%\.conda\envs\qrushi\python.exe" -u stop.py
) else (
    python -u stop.py
)
if errorlevel 1 pause
