# Обёртка над python src/build.py для Windows.
# Все аргументы прокидываются как есть: .\build.ps1 --check-only
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
python src/build.py @args
exit $LASTEXITCODE
