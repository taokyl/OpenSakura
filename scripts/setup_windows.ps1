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

if (-not (Test-Path '.venv\Scripts\python.exe')) { & cmd /c "$py -m venv .venv" }
& .venv\Scripts\python.exe -m pip install -U pip wheel
& .venv\Scripts\python.exe -m pip install -r requirements.txt

$yv = 'services\stt\.venv'
if (-not (Test-Path "$yv\Scripts\python.exe")) { & cmd /c "$py -m venv $yv" }
& "$yv\Scripts\python.exe" -m pip install -U pip wheel
& "$yv\Scripts\python.exe" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
# the rest of the STT deps; torch/torchaudio are already satisfied by the cu128 builds above
& "$yv\Scripts\python.exe" -m pip install -r services\stt\requirements.txt

if (-not (Test-Path 'services\stt\models\model.pt')) { & .venv\Scripts\python.exe scripts\download_sensevoice.py }
if (-not (Test-Path '.env')) { Copy-Item .env.example .env }
if (-not (Test-Path 'config\settings.json')) { Copy-Item config\settings.example.json config\settings.json }

Write-Host ''
Write-Host '[setup] done. Next:'
Write-Host '  1. python scripts\setup_tts.py   (her voice. First, once: accept the terms at'
Write-Host '     https://huggingface.co/MekaHime/MekaHime_Sakura and create a Read token at'
Write-Host '     https://huggingface.co/settings/tokens; the script asks for it. README: Quick start)'
Write-Host '  2. .venv\Scripts\python launch.py --check'
Write-Host '  3. Start_OpenSakura.bat  ->  http://localhost:8010'
