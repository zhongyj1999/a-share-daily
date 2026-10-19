@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
python scripts\daily_report.py
exit /b %ERRORLEVEL%
