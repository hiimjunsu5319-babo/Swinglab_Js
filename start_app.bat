@echo off
cd /d "%~dp0"
set "PYTHON_EXE=C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%PYTHON_EXE%" (
  "%PYTHON_EXE%" -u app.py
) else (
  py app.py
)

pause
