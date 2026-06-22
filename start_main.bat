@echo off
cd /d "%~dp0"
set "PORT=8000"
set "APP_ENV=main"
set "NAVER_CAPTURE_DIR=static\naver_captures"
call start_app.bat
