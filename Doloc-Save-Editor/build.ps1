$ErrorActionPreference = 'Stop'

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = (Get-Command python).Source
$buildRoot = Join-Path ([IO.Path]::GetTempPath()) 'doloc-save-editor-pyinstaller'
$distDir = Join-Path $projectDir 'dist'

python -c "import customtkinter, Crypto, PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw '缺少构建依赖。请先执行：python -m pip install -r requirements.txt'
}

New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
New-Item -ItemType Directory -Path $distDir -Force | Out-Null

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name DolocSaveEditor `
    --collect-all customtkinter `
    --distpath (Join-Path $buildRoot 'dist') `
    --workpath (Join-Path $buildRoot 'build') `
    --specpath $buildRoot `
    (Join-Path $projectDir 'app.py')

Copy-Item -LiteralPath (Join-Path $buildRoot 'dist\DolocSaveEditor.exe') -Destination $distDir -Force
Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $distDir 'DolocSaveEditor.exe')

