$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Python = $env:AXON_PYTHON

if (-not $Python) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($PythonCommand) {
        $Python = $PythonCommand.Source
    }
}

if (-not $Python) {
    $VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        $Python = $VenvPython
    }
}

if (-not $Python) {
    throw "Python executable not found. Activate the project environment, expose python on PATH, or set AXON_PYTHON."
}

$BuildRoot = Join-Path $RepoRoot "build\pyinstaller"
$DistPath = Join-Path $BuildRoot "dist"
$WorkPath = Join-Path $BuildRoot "work"
$SpecPath = Join-Path $BuildRoot "spec"

if (Test-Path $BuildRoot) {
    Remove-Item $BuildRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $DistPath | Out-Null
New-Item -ItemType Directory -Force -Path $WorkPath | Out-Null
New-Item -ItemType Directory -Force -Path $SpecPath | Out-Null

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --name axon `
    --onedir `
    --console `
    --paths $RepoRoot `
    --distpath $DistPath `
    --workpath $WorkPath `
    --specpath $SpecPath `
    packaging/axon_mvp_entry.py

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Output "Build completed: $DistPath\axon\axon.exe"