# Arranca Astrolabio en segundo plano al iniciar sesión y al desbloquear la laptop, por ejemplo al volver de suspenderla, sin abrir ventana.
# Además, diez minutos antes del cierre de la vela diaria (23:50 UTC) despierta la laptop si está suspendida y conectada a la corriente,
# para que el bot haga su ciclo. Con batería Windows no la despierta, y apagada del todo nada puede correr. Si cambias de zona horaria, vuelve a correrlo.
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
$despertar = [DateTime]::UtcNow.Date.AddHours(23).AddMinutes(50).ToLocalTime()  # la vela diaria cierra a las 00:00 UTC
$antesDelCierre = New-ScheduledTaskTrigger -Daily -At $despertar
# WakeToRun: Windows despierta el equipo para esta tarea si el plan de energía permite temporizadores de activación (con corriente, por omisión)
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -WakeToRun
Register-ScheduledTask -TaskName $nombre -Action $accion -Trigger @($alEntrar, $alDesbloquear, $antesDelCierre) -Settings $ajustes -Force `
    -Description 'Arranca Astrolabio en segundo plano al iniciar sesión, al desbloquear la laptop y diez minutos antes del cierre diario, cuando la despierta si está suspendida. Si ya corre, no hace nada.' | Out-Null
Write-Output "Arranque automático activado: tarea «$nombre», al iniciar sesión, al desbloquear la laptop y a las $($despertar.ToString('HH:mm')), cuando la despierta si está suspendida y conectada a la corriente."
