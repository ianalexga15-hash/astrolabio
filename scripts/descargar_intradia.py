"""Descarga velas públicas de 15 minutos de MEXC y audita su calidad. No toca los CSV diarios ni la base del bot.

Uso: .venv/Scripts/python scripts/descargar_intradia.py [días]   (90 por defecto)
Guarda data/intradia/<PAR>_15m.csv y data/intradia/auditoria.json con fuente, fechas, auditoría y huella SHA-256.
"""
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding='utf-8')

from bot.mexc import Mexc  # noqa: E402
from research.simular_intradia import COLUMNAS, PASO_MS, auditar  # noqa: E402

SIMBOLOS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
POR_LLAMADA = 500
DIA_MS = 86_400_000


def descargar(mercado, simbolo, inicio_ms, fin_ms):
    filas, a = [], inicio_ms
    while a < fin_ms:
        b = min(a + POR_LLAMADA * PASO_MS, fin_ms)
        filas += mercado.klines(simbolo, a, b - 1, limit=POR_LLAMADA, intervalo='15m')  # MEXC exige inicio y fin juntos
        a = b
        time.sleep(0.25)
    return pd.DataFrame([f[:7] for f in filas], columns=COLUMNAS).astype({k: float for k in ('open', 'high', 'low', 'close', 'volume')})


def main(dias=90):
    ahora = int(time.time() * 1000)
    fin = ahora - ahora % PASO_MS  # la vela que empieza aquí sigue abierta: queda fuera
    inicio = (fin - dias * DIA_MS) // DIA_MS * DIA_MS + DIA_MS  # sesiones UTC completas para el VWAP de sesión
    carpeta = RAIZ / 'data' / 'intradia'
    carpeta.mkdir(parents=True, exist_ok=True)
    registro = dict(fuente='MEXC GET /api/v3/klines interval=15m, datos públicos', descargado=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    desde=datetime.fromtimestamp(inicio / 1000, timezone.utc).isoformat(), hasta=datetime.fromtimestamp(fin / 1000, timezone.utc).isoformat(), activos={})
    mercado = Mexc()
    for simbolo in SIMBOLOS:
        crudo = descargar(mercado, simbolo, inicio, fin)
        auditoria = auditar(crudo, fin)
        limpio = crudo.drop_duplicates('open_time').sort_values('open_time').reset_index(drop=True)
        ruta = carpeta / f'{simbolo}_15m.csv'
        limpio.to_csv(ruta, index=False)
        registro['activos'][simbolo] = dict(archivo=str(ruta.relative_to(RAIZ)).replace('\\', '/'), sha256=hashlib.sha256(ruta.read_bytes()).hexdigest(),
                                            velas_guardadas=len(limpio), auditoria_cruda=auditoria)
        print(simbolo, len(limpio), 'velas |', {k: v for k, v in auditoria.items() if k not in ('desde', 'hasta')})
    (carpeta / 'auditoria.json').write_text(json.dumps(registro, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print('Guardado en', carpeta.relative_to(RAIZ), '| de', registro['desde'], 'a', registro['hasta'])


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 90)
