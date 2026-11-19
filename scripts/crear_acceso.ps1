# Crea el acceso "Astrolabio" en el escritorio. No cambia ningún ajuste del sistema.
$raiz = Split-Path -Parent $PSScriptRoot
$python = Join-Path $raiz '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $python)) { $python = Join-Path $raiz '.venv\Scripts\python.exe' }
$shell = New-Object -ComObject WScript.Shell
$ruta = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Astrolabio.lnk'
$acceso = $shell.CreateShortcut($ruta)
$acceso.TargetPath = $python
$acceso.Arguments = '-m bot.lanzar'
$acceso.WorkingDirectory = $raiz
$acceso.IconLocation = (Join-Path $raiz 'assets\astrolabio.ico')
$acceso.Description = 'Astrolabio: cartera Paper de 40 activos de MEXC'
$acceso.Save()
Write-Output "Acceso creado: $ruta"
