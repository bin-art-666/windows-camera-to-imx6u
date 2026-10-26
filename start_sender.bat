@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -u sender.py %*
) else if exist "%USERPROFILE%\.conda\envs\qrushi\python.exe" (
    "%USERPROFILE%\.conda\envs\qrushi\python.exe" -u sender.py %*
) else (
    python -u sender.py %*
)
if errorlevel 1 (
    echo Camera sender failed. Check README.md and the error above.
    pause
)
