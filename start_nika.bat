@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\scripts\python.exe" (
    echo Nika Python environment was not found.
    echo Install the project dependencies first.
    pause
    exit /b 1
)

".venv\scripts\python.exe" -m nika.cli foreground
if errorlevel 1 (
    echo.
    echo Nika exited with an error.
    pause
)
