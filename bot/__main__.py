"""Arranque: python -m bot. Solo escucha en la laptop y abre el panel en el navegador."""
import sys
import threading
import webbrowser

import uvicorn

from bot.api import crear_app
from bot.config import cargar_ajustes
from bot.energia import mantener_despierto


def main():
    ajustes = cargar_ajustes()
    if ajustes.sin_suspender and sys.platform == 'win32':
        mantener_despierto()
    app = crear_app(ajustes)
    if '--sin-navegador' not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(f'http://127.0.0.1:{ajustes.puerto}')).start()
    # Sin proxy delante: con proxy_headers, uvicorn tomaría la IP de X-Forwarded-For y el límite de intentos por IP se podría saltar.
    uvicorn.run(app, host='127.0.0.1', port=ajustes.puerto, log_level='warning', proxy_headers=False)


if __name__ == '__main__':
    main()
