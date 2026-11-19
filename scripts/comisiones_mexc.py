"""Actualiza config/comisiones.json con la comisión real de cada par para tu cuenta MEXC.

Usa la clave de solo ver de .env y guarda la comisión al comprar o vender al instante (taker), que es la que paga el bot.
Reinicia el bot después para que la use. Nunca imprime las claves.
"""
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding='utf-8')

from bot.config import cargar_universo, leer_env  # noqa: E402
from bot.cuenta_mexc import CuentaMexc  # noqa: E402
from bot.mexc import MexcError  # noqa: E402


def main():
    e = leer_env()
    cuenta = CuentaMexc(e.get('MEXC_API_KEY', ''), e.get('MEXC_API_SECRET', ''))
    if not cuenta.configurada:
        sys.exit('Falta MEXC_API_KEY o MEXC_API_SECRET en .env.')
    comisiones, fallas = {}, []
    for simbolo in cargar_universo(RAIZ, 'BTCUSDT'):
        try:
            comisiones[simbolo] = cuenta.comision(simbolo)['taker']
        except MexcError as error:
            fallas.append(f'{simbolo}: {error}')
        time.sleep(1.0)  # peso 20 por consulta: una por segundo queda lejos del límite de MEXC
    (RAIZ / 'config' / 'comisiones.json').write_text(json.dumps(dict(sorted(comisiones.items())), indent=1) + '\n', encoding='utf-8')
    print(f'{len(comisiones)} pares guardados en config/comisiones.json; sin comisión: {[s for s, c in comisiones.items() if c == 0] or "ninguno"}.')
    for falla in fallas:
        print('Sin dato, usará la comisión general:', falla)


if __name__ == '__main__':
    main()
