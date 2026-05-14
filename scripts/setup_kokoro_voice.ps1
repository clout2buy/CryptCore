param(
  [string]$Root = "$env:USERPROFILE\.crypt\voice\kokoro",
  [switch]$NoTest
)

$ErrorActionPreference = "Stop"

$ModelUrl = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
$VoicesUrl = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
$Root = [System.IO.Path]::GetFullPath($Root)
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Model = Join-Path $Root "kokoro-v1.0.onnx"
$Voices = Join-Path $Root "voices-v1.0.bin"
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$Runner = Join-Path $RepoRoot "scripts\kokoro_say.py"
$Cache = Join-Path ([System.IO.Path]::GetDirectoryName($Root)) "cache"
$Sample = Join-Path $Cache "kokoro-test.wav"

New-Item -ItemType Directory -Force -Path $Root | Out-Null
New-Item -ItemType Directory -Force -Path $Cache | Out-Null

if (-not (Test-Path $Python)) {
  Write-Host "Creating Kokoro voice environment at $Venv"
  python -m venv $Venv
}

Write-Host "Installing local Kokoro dependencies"
& $Python -m pip install --upgrade pip
& $Python -m pip install "kokoro-onnx>=0.5,<0.6" "soundfile>=0.13,<0.14"

if (-not (Test-Path $Model)) {
  Write-Host "Downloading kokoro-v1.0.onnx"
  Invoke-WebRequest -Uri $ModelUrl -OutFile $Model
}

if (-not (Test-Path $Voices)) {
  Write-Host "Downloading voices-v1.0.bin"
  Invoke-WebRequest -Uri $VoicesUrl -OutFile $Voices
}

if (-not $NoTest) {
  Write-Host "Generating Kokoro test voice"
  & $Python $Runner --model $Model --voices $Voices --out $Sample --voice af_heart --speed 0.96 --lang en-us --text "Crypt voice is online. Local Kokoro is ready."
  Write-Host "Created $Sample"
}

Write-Host "Kokoro voice setup complete."
