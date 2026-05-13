param(
    [string]$Python,
    [switch]$NoPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $HOME ".crypt\bin"

function Test-PythonInvocation {
    param([string[]]$Invocation)
    try {
        $tail = @()
        if ($Invocation.Length -gt 1) {
            $tail = $Invocation[1..($Invocation.Length - 1)]
        }
        & $Invocation[0] @tail --version *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Resolve-PythonInvocation {
    if ($Python) {
        return @($Python)
    }
    if ((Get-Command python -ErrorAction SilentlyContinue) -and (Test-PythonInvocation @("python"))) {
        return @("python")
    }
    if ((Get-Command py -ErrorAction SilentlyContinue) -and (Test-PythonInvocation @("py", "-3.13"))) {
        return @("py", "-3.13")
    }
    throw "No working Python found. Install Python 3.13 or pass -Python C:\Path\python.exe."
}

function Invoke-Python {
    param(
        [string[]]$Invocation,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )
    $tail = @()
    if ($Invocation.Length -gt 1) {
        $tail = $Invocation[1..($Invocation.Length - 1)]
    }
    & $Invocation[0] @tail @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed ($LASTEXITCODE): $($Invocation -join ' ') $($Arguments -join ' ')"
    }
}

function Quote-CmdPart {
    param([string]$Value)
    if ($Value -match "\s") {
        return '"' + $Value.Replace('"', '\"') + '"'
    }
    return $Value
}

$py = Resolve-PythonInvocation
Write-Host "== Crypt install/link =="
Write-Host "root: $root"
Write-Host "python: $($py -join ' ')"

Write-Host "`n== Compile =="
Invoke-Python -Invocation $py -Arguments @("-m", "compileall", "-q", "main.py", "core", "tools", "crypt")

Write-Host "`n== Editable package install =="
Invoke-Python -Invocation $py -Arguments @("-m", "pip", "install", "-e", $root)

Write-Host "`n== Shims =="
New-Item -ItemType Directory -Force -Path $bin | Out-Null
$cmdPath = Join-Path $bin "crypt.cmd"
$psPath = Join-Path $bin "crypt.ps1"
$pyCmd = ($py | ForEach-Object { Quote-CmdPart $_ }) -join " "
$mainPath = Join-Path $root "main.py"

@"
@echo off
$pyCmd "$mainPath" %*
"@ | Set-Content -Path $cmdPath -Encoding ASCII

@"
& $pyCmd "$mainPath" @args
exit `$LASTEXITCODE
"@ | Set-Content -Path $psPath -Encoding ASCII

if (-not $NoPath) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @()
    if ($userPath) {
        $parts = $userPath -split ";"
    }
    if ($parts -notcontains $bin) {
        $newPath = (($parts + $bin) | Where-Object { $_ }) -join ";"
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Host "Added to user PATH: $bin"
        Write-Host "Open a new PowerShell window for PATH changes to apply."
    } else {
        Write-Host "Already on user PATH: $bin"
    }
}

Write-Host "`nLinked commands:"
Write-Host "  $cmdPath"
Write-Host "  $psPath"
Write-Host "`nTry from any project:"
Write-Host "  crypt doctor"
