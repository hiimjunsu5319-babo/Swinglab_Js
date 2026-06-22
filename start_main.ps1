$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PORT = "8000"
$env:APP_ENV = "main"
$env:NAVER_CAPTURE_DIR = "static/naver_captures"
& "$PSScriptRoot\start_app.ps1"
