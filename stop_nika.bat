@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\scripts\python.exe" (
    echo Nika Python environment was not found.
    pause
    exit /b 1
)

".venv\scripts\python.exe" -m nika.cli stop
if errorlevel 1 (
    echo Nika is not running or could not stop cleanly.
    pause
)
