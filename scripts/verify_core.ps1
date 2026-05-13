param(
    [switch]$Quick,
    [string]$Python
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $Python) {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $Python = "python"
        $script:PythonArgsPrefix = @()
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $Python = "py"
        $script:PythonArgsPrefix = @("-3.13")
    } else {
        throw "No Python interpreter found. Install Python 3.13 or pass -Python <path>."
    }
} else {
    $script:PythonArgsPrefix = @()
}

function Invoke-Python {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )
    $prefix = $script:PythonArgsPrefix
    & $Python @prefix @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed ($LASTEXITCODE): $Python $($prefix -join ' ') $($Arguments -join ' ')"
    }
}

Write-Host "== CryptCore verification =="
Write-Host "root: $root"
Write-Host "python: $Python $($script:PythonArgsPrefix -join ' ')"

Write-Host "`n== Import and CLI smoke =="
Invoke-Python -m compileall -q main.py core tools crypt tests
Invoke-Python main.py --help | Out-Null
Invoke-Python -m crypt --help | Out-Null

Write-Host "`n== Lint =="
Invoke-Python -m ruff check .

Write-Host "`n== Benchmark inventory =="
Invoke-Python main.py bench --bench-list

Write-Host "`n== Tests =="
if ($Quick) {
    Invoke-Python -m pytest `
        tests/test_registry.py `
        tests/test_runtime_defaults.py `
        tests/test_production_runtime.py `
        tests/test_permissions.py `
        tests/test_mcp.py `
        tests/test_skills.py `
        tests/test_task_state.py `
        tests/test_project_index.py `
        tests/test_bash_safety.py `
        tests/test_read_tools.py `
        tests/test_edit_file.py `
        tests/test_write_file.py
} else {
    Invoke-Python -m pytest
}

Write-Host "`nCryptCore verification passed."
