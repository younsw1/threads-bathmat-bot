@echo off
chcp 65001 >nul
title Threads Dashboard
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [Notice] Python is not installed on this computer.
    echo.
    echo 1^) Download and install Python from https://www.python.org/downloads/
    echo 2^) On the install screen, check "Add python.exe to PATH" before installing.
    echo 3^) Once installed, double-click this file again.
    echo.
    pause
    exit /b 1
)

python scripts\bootstrap.py

pause
