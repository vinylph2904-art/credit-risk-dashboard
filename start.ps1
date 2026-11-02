param(
    [string]$DatabaseHost = '127.0.0.1',
    [int]$DatabasePort = 3306,
    [string]$DatabaseName = 'home_credit_submission',
    [string]$DatabaseUser = 'root',
    [int]$WebPort = 5001
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonExecutable = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw 'Create .venv and install requirements first; see README.md.'
}
$privatePassword = Read-Host 'MySQL password (not the dashboard demo password)' -AsSecureString
$passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($privatePassword)
try {
    $env:MYSQL_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
}
$env:MYSQL_HOST = $DatabaseHost
$env:MYSQL_PORT = [string]$DatabasePort
$env:MYSQL_DATABASE = $DatabaseName
$env:MYSQL_USER = $DatabaseUser
if (-not $env:FLASK_SECRET_KEY) { $env:FLASK_SECRET_KEY = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N') }
try {
    & $pythonExecutable web/app.py --port $WebPort
} finally {
    Remove-Item Env:MYSQL_PASSWORD -ErrorAction SilentlyContinue
}
