# OpenSakura one-time setup (Windows, Python 3.11, NVIDIA GPU).
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
# Creates the two virtual environments, installs CUDA 12.8 torch for the STT service
# (RTX 50-series needs cu128), downloads the SenseVoiceSmall weights, and
# copies the example config files.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Find-Py311 {
    foreach ($c in @('py -3.11', 'python3.11', 'python')) {
        try {
            $v = & cmd /c "$c -c `"import sys;print(sys.version_info[:2]==(3,11))`"" 2>$null
            if ($v -match 'True') { return $c }
        } catch {}
    }
    throw "Python 3.11 not found. Install it from python.org (check 'Add to PATH')."
}
$py = Find-Py311
Write-Host "[setup] using $py"

# A failing step stops the script with its exit code (PowerShell does not stop on a
# native command's failure by itself), so "done" below really means done.
function Step([string]$what, [scriptblock]$cmd) {
    & $cmd
    if ($LASTEXITCODE -ne 0) {
        throw "[setup] $what failed (exit code $LASTEXITCODE). Fix the error above, then run this script again."
    }
}

if (-not (Test-Path '.venv\Scripts\python.exe')) { Step 'creating .venv' { & cmd /c "$py -m venv .venv" } }
Step 'pip (.venv)' { & .venv\Scripts\python.exe -m pip install -U pip wheel }
Step 'pip install -r requirements.txt' { & .venv\Scripts\python.exe -m pip install -r requirements.txt }

$yv = 'services\stt\.venv'
if (-not (Test-Path "$yv\Scripts\python.exe")) { Step "creating $yv" { & cmd /c "$py -m venv $yv" } }
Step 'pip (STT venv)' { & "$yv\Scripts\python.exe" -m pip install -U pip wheel }
Step 'CUDA 12.8 torch (STT)' { & "$yv\Scripts\python.exe" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128 }
# the rest of the STT deps; torch/torchaudio are already satisfied by the cu128 builds above
Step 'pip install -r services\stt\requirements.txt' { & "$yv\Scripts\python.exe" -m pip install -r services\stt\requirements.txt }

if (-not (Test-Path 'services\stt\models\model.pt')) {
    Step 'downloading the speech-recognition model' { & .venv\Scripts\python.exe scripts\download_sensevoice.py }
}
if (-not (Test-Path 'services\stt\models\model.pt')) {
    throw '[setup] services\stt\models\model.pt is missing after the download. Run this script again.'
}
if (-not (Test-Path '.env')) { Copy-Item .env.example .env }
if (-not (Test-Path 'config\settings.json')) { Copy-Item config\settings.example.json config\settings.json }

Write-Host ''
Write-Host '[setup] done. Next (README, Quick start):'
Write-Host '  1. python scripts\setup_tts.py   (her voice; type yes to accept her personal-use license)'
Write-Host '  2. give her a brain: your OpenRouter key in .env, or Ollama (README step 2)'
Write-Host '  3. .venv\Scripts\python launch.py --check, then Start_OpenSakura.bat  ->  http://localhost:8010'
