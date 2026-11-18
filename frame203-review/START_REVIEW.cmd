@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" src\review_app.py
) else (
  python src\review_app.py
)
if errorlevel 1 pause
