$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m PyInstaller --noconfirm --onefile --windowed --collect-all customtkinter --name 'Fluent文件转换工具' --add-data 'src/worker.py;runtime' --add-data 'src/converter.py;runtime' src/app.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
