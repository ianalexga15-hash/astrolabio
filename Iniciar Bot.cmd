@echo off
rem Doble clic para abrir el bot. Prepara lo que falte la primera vez y abre el panel en el navegador.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Creando el entorno de Python...
  py -3.13 -m venv .venv || goto error
  .venv\Scripts\python -m pip install --quiet -r requirements.txt || goto error
)
if not exist .env .venv\Scripts\python -m bot.preparar
if not exist frontend\dist\index.html (
  echo Compilando el panel...
  pushd frontend
  call npm install --no-fund --no-audit || goto error
  call npm run build || goto error
  popd
)
echo El bot queda en http://127.0.0.1:8770 . Tu clave es BOT_ADMIN_KEY en el archivo .env
echo Cierra esta ventana para apagarlo. Mientras este apagado no toma decisiones.
.venv\Scripts\python -m bot
goto :eof
:error
echo No se pudo preparar el bot. Revisa el mensaje de arriba.
pause
