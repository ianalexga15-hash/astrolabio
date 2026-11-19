# Arranca Astrolabio en segundo plano al iniciar sesión y al desbloquear la laptop, por ejemplo al volver de suspenderla, sin abrir ventana.
# Activar:  powershell -ExecutionPolicy Bypass -File scripts\inicio_automatico.ps1
# Quitar:   powershell -ExecutionPolicy Bypass -File scripts\inicio_automatico.ps1 -Quitar
# Crea o borra la tarea «Astrolabio» del Programador de tareas, solo para tu usuario. Si el bot ya corre, la tarea no hace nada.
param([switch]$Quitar)
$raiz = Split-Path -Parent $PSScriptRoot
$nombre = 'Astrolabio'
$viejo = Join-Path ([Environment]::GetFolderPath('Startup')) 'Astrolabio en segundo plano.lnk'
if (Test-Path $viejo) { Remove-Item $viejo }  # versión anterior: solo arrancaba al iniciar sesión
if ($Quitar) {
    if (Get-ScheduledTask -TaskName $nombre -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $nombre -Confirm:$false
        Write-Output 'Arranque automático quitado.'
    } else {
        Write-Output 'El arranque automático no estaba activado.'
    }
    return
}
$usuario = "$env:USERDOMAIN\$env:USERNAME"
$accion = New-ScheduledTaskAction -Execute (Join-Path $raiz '.venv\Scripts\pythonw.exe') -Argument '-m bot.lanzar --sin-ventana' -WorkingDirectory $raiz
$alEntrar = New-ScheduledTaskTrigger -AtLogOn -User $usuario
$clase = Get-CimClass -Namespace 'Root/Microsoft/Windows/TaskScheduler' -ClassName 'MSFT_TaskSessionStateChangeTrigger'
$alDesbloquear = New-CimInstance -CimClass $clase -ClientOnly -Property @{ StateChange = [uint32]8; UserId = $usuario; Enabled = $true }  # 8: desbloqueo de la sesión
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $nombre -Action $accion -Trigger @($alEntrar, $alDesbloquear) -Settings $ajustes -Force `
    -Description 'Arranca Astrolabio en segundo plano al iniciar sesión y al desbloquear la laptop. Si ya corre, no hace nada.' | Out-Null
Write-Output "Arranque automático activado: tarea «$nombre», al iniciar sesión y al desbloquear la laptop."
