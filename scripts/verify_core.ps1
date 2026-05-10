param(
    [switch]$Quick
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== CryptCore verification =="
Write-Host "root: $root"

Write-Host "`n== Import and CLI smoke =="
python -m compileall -q main.py core tools crypt tests
python main.py --help | Out-Null
python -m crypt --help | Out-Null

Write-Host "`n== Lint =="
python -m ruff check .

Write-Host "`n== Benchmark inventory =="
python main.py bench --bench-list

Write-Host "`n== Tests =="
if ($Quick) {
    python -m pytest `
        tests/test_registry.py `
        tests/test_runtime_defaults.py `
        tests/test_production_runtime.py `
        tests/test_permissions.py `
        tests/test_bash_safety.py `
        tests/test_read_tools.py `
        tests/test_edit_file.py `
        tests/test_write_file.py
} else {
    python -m pytest
}

Write-Host "`nCryptCore verification passed."
