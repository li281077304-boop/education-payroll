$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repo
& "$repo\.venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm education_payroll.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
