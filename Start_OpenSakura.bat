@echo off
setlocal
chcp 65001 >nul
title OpenSakura
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" launch.py %*
) else (
  echo [!] .venv not found. Run scripts\setup_windows.ps1 first ^(or: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt^).
  python launch.py %*
)
if errorlevel 1 pause
