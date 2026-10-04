@echo off
cd /d "%~dp0"
set "PYTHONUTF8=1"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m opticslabkit serve --port 8766
) else (
    python -m opticslabkit serve --port 8766
)
if errorlevel 1 pause
