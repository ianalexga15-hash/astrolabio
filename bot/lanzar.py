"""Abre Astrolabio desde el escritorio: arranca el servidor en segundo plano si hace falta y abre su ventana.

Si ya está corriendo, solo abre la ventana. Cerrar la ventana no apaga el bot: se apaga desde Sistema, para que siga vigilando.
Con --sin-ventana solo arranca el servidor: lo usa el arranque automático al iniciar sesión y al desbloquear.
En ambos casos abre Ollama si no responde, porque al suspender la laptop se detiene y no vuelve solo.
"""
import ctypes
import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from bot.config import RAIZ, leer_env

PUERTO = int(leer_env().get('BOT_PORT', 8770))
URL = f'http://127.0.0.1:{PUERTO}'
OLLAMA_URL = leer_env().get('BOT_OLLAMA_URL', 'http://127.0.0.1:11434')
OLLAMA_APP = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Ollama' / 'ollama app.exe'


def corriendo():
    try:
        with build_opener(ProxyHandler({})).open(URL + '/api/salud', timeout=1) as r:
            return json.load(r).get('ok') is True
    except (OSError, ValueError):
        return False


def ollama_responde():
    try:
        with build_opener(ProxyHandler({})).open(OLLAMA_URL + '/api/version', timeout=1):
            return True
    except OSError:
        return False


def asegurar_ollama():
    """El bot decide con Ollama local; si no responde, se abre su aplicación, la misma que arranca al iniciar sesión."""
    if ollama_responde() or not OLLAMA_APP.exists():
        return False
    subprocess.Popen([str(OLLAMA_APP)], cwd=OLLAMA_APP.parent)
    return True


def avisar(mensaje):
    ctypes.windll.user32.MessageBoxW(0, mensaje, 'Astrolabio', 0x10)


def arrancar():
    (RAIZ / 'data').mkdir(exist_ok=True)
    python = Path(sys.executable)
    sin_ventana = python.with_name('pythonw.exe')
    with (RAIZ / 'data' / 'servidor.log').open('ab') as log:
        return subprocess.Popen([str(sin_ventana if sin_ventana.exists() else python), '-m', 'bot', '--sin-navegador'], cwd=RAIZ, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                creationflags=subprocess.CREATE_NO_WINDOW)


def abrir_ventana():
    for base in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles')):
        edge = Path(base or '') / 'Microsoft/Edge/Application/msedge.exe'
        if edge.exists():
            subprocess.Popen([str(edge), f'--app={URL}', '--new-window'])
            return
    webbrowser.open(URL)


def main(ventana=True):
    """Arranca el servidor si hace falta. Con ventana=False, como en el arranque automático, no abre el panel."""
    if not (RAIZ / '.env').exists():
        subprocess.run([sys.executable, '-m', 'bot.preparar'], cwd=RAIZ, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if not (RAIZ / 'frontend' / 'dist' / 'index.html').exists():
        avisar('El panel no está compilado. Ejecuta Iniciar Bot.cmd una vez para prepararlo.')
        return
    asegurar_ollama()
    if not corriendo():
        proceso = arrancar()
        for _ in range(120):
            if corriendo():
                break
            if proceso.poll() is not None:
                break
            time.sleep(0.25)
    if corriendo():
        if ventana:
            abrir_ventana()
    else:
        avisar(f'No se pudo iniciar. Revisa data\\servidor.log. El puerto {PUERTO} podría estar ocupado.')


if __name__ == '__main__':
    main(ventana='--sin-ventana' not in sys.argv)
