"""Elige los activos de la cartera y descarga su historia diaria.

Regla, fija y sin mirar resultados del modelo: pares spot contra USDT de MEXC, operables, ordenados por volumen de 24 horas,
sin monedas estables, tokens envueltos, oro, acciones tokenizadas ni tokens apalancados, con historia y spread suficientes.

Límite conocido: elegir por el volumen de hoy introduce sesgo de supervivencia al evaluar en el pasado.
"""
import json
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding='utf-8')

from bot import data, mexc  # noqa: E402

CUANTOS = 40
MINIMO_DIAS = 900
SPREAD_MAX_BPS = 25.0
ESTABLES = re.compile(r'^(USDC|USDE|FDUSD|TUSD|DAI|USD1|USDD|PYUSD|EUR|EURT|EURI|GBP|BUSD|USDP|USD0|RLUSD|USDS|GUSD|FRAX|LUSD|USDG|USDQ|USDX|WBTC|WETH|STETH|WSTETH|WEETH|CBBTC|BNSOL|BTCB|TBTC|JITOSOL|MSOL|BBSOL|WBNB|XAUT)USDT$')
OTROS = re.compile(r'(\d+[LS]USDT$)|(^GOLD)|(^SILVER)|(ONUSDT$)|(\()')  # apalancados, metales y acciones tokenizadas


def main():
    m = mexc.Mexc()
    informacion = m._get('/api/v3/exchangeInfo', {})['symbols']
    operables = {s['symbol'] for s in informacion if str(s.get('status')) == '1' and s.get('quoteAsset') == 'USDT' and s.get('isSpotTradingAllowed') and not s.get('st')}
    volumenes = m._get('/api/v3/ticker/24hr', {})
    candidatos = [v for v in volumenes if v['symbol'] in operables and not ESTABLES.match(v['symbol']) and not OTROS.search(v['symbol'])]
    candidatos.sort(key=lambda v: float(v.get('quoteVolume') or 0), reverse=True)

    # Spread medido en varias lecturas, no en una sola
    lecturas = {}
    primeros = [v['symbol'] for v in candidatos[:250]]
    for _ in range(5):
        for s, p in m.libro(primeros).items():
            if p['ask'] > 0:
                lecturas.setdefault(s, []).append((p['ask'] - p['bid']) / p['ask'] * 10_000)
        time.sleep(1)

    carpeta = RAIZ / 'data' / 'cartera'
    carpeta.mkdir(parents=True, exist_ok=True)
    ahora = datetime.now(timezone.utc)
    fin = int(ahora.timestamp() * 1000)
    inicio = int(datetime(2017, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    elegidos, descartes, fichas = [], [], {}
    for v in candidatos[:250]:
        s = v['symbol']
        spread = statistics.median(lecturas.get(s, [1e9]))
        if spread > SPREAD_MAX_BPS:
            descartes.append((s, f'spread {spread:.0f} pb'))
            continue
        try:
            filas = [f for f in m.history(s, inicio, fin) if f[6] <= fin]
            limpio, bitacora = data.clean(data.frame_from_rows(filas))
        except (mexc.MexcError, data.DataError) as e:
            descartes.append((s, str(e)[:60]))
            continue
        if len(limpio) < MINIMO_DIAS:
            descartes.append((s, f'{len(limpio)} días'))
            continue
        limpio.to_csv(carpeta / f'{s}.csv', index=False)
        fichas[s] = dict(volumen_24h=round(float(v['quoteVolume'])), spread_bps=round(spread, 1), dias=len(limpio), desde=limpio.date.iloc[0], hasta=limpio.date.iloc[-1], limpieza=bitacora, huella=data.dataset_hash(limpio))
        elegidos.append(s)
        print(f'{len(elegidos):2d} {s:12s} {len(limpio):5d} días  spread {spread:5.1f} pb  volumen {float(v["quoteVolume"]) / 1e6:8.1f} M', flush=True)
        if len(elegidos) == CUANTOS:
            break
    if 'BTCUSDT' not in elegidos:
        raise SystemExit('BTCUSDT debe estar en la cartera: es el activo de la práctica.')
    (RAIZ / 'config' / 'universo.json').write_text(json.dumps(dict(
        simbolos=elegidos, fecha=ahora.isoformat(timespec='seconds'),
        regla_inicial=f'Spot contra USDT, operables, por volumen de 24 h, sin estables, envueltos, metales, acciones ni apalancados, con al menos {MINIMO_DIAS} días y spread mediano de hasta {SPREAD_MAX_BPS} puntos base.',
        limite='Elegir por volumen de hoy introduce sesgo de supervivencia en cualquier evaluación del pasado.', descartes=descartes, fichas=fichas), indent=1, ensure_ascii=False), encoding='utf-8')
    print('Elegidos:', len(elegidos), 'Descartados:', len(descartes))


if __name__ == '__main__':
    main()
