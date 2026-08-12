@echo off
chcp 65001 >nul
title Threads Dashboard - Package Release
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [Notice] Run the main launcher file at least once first so the local environment is ready.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" scripts\package_release.py

pause
