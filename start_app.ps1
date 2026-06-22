$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$pythonExe = "C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path $pythonExe) {
    & $pythonExe app.py
} else {
    py app.py
}
