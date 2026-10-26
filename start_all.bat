@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -u launch.py %*
) else if exist "%USERPROFILE%\.conda\envs\qrushi\python.exe" (
    "%USERPROFILE%\.conda\envs\qrushi\python.exe" -u launch.py %*
) else (
    python -u launch.py %*
)
if errorlevel 1 (
    echo One-click camera service failed. See the error above and README.md.
    pause
)
