@echo off
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 server.py
) else (
  python server.py
)
pause
