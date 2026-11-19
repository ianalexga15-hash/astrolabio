"""Crea .env con claves aleatorias si no existe. Nunca lo sobrescribe."""
import secrets

from bot.config import RAIZ

ruta = RAIZ / '.env'
if ruta.exists():
    print(f'{ruta} ya existe; no se modificó.')
else:
    clave = secrets.token_urlsafe(24)
    ruta.write_text(f'BOT_ADMIN_KEY={clave}\nBOT_LLM_KEY={secrets.token_urlsafe(32)}\n', encoding='utf-8')
    print(f'Creado {ruta}. Tu clave del panel es BOT_ADMIN_KEY en ese archivo.')
