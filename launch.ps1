$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (Test-Path -LiteralPath '.venv\Scripts\python.exe') {
    $labPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
} else {
    $labPython = (Get-Command python -ErrorAction Stop).Source
}
& $labPython -m opticslabkit serve --port 8766
