"""Agrega o quita activos de la cartera: descarga y audita sus velas diarias y actualiza config/universo.json.

Las velas salen de la API pública de MEXC y se auditan y limpian con bot/data.py, igual que en scripts/elegir_universo.py.
Un activo nuevo necesita al menos 120 velas diarias seguidas, las que usa el bot para sus indicadores.
Cada cambio queda en la lista «cambios» del universo, con su fecha y su motivo. Después reinicia el bot y pulsa «Activar bot» en el panel:
los activos nuevos arrancan detenidos.

    python scripts/agregar_activos.py --agregar "GOLD(XAUT)USDT" EURUSDT --quitar ZIGUSDT --motivo "..."
"""
import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding='utf-8')

from bot import data, mexc  # noqa: E402
from bot.agent import HISTORIA  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--agregar', nargs='*', default=[])
    p.add_argument('--quitar', nargs='*', default=[])
    p.add_argument('--motivo', required=True)
    a = p.parse_args()
    ruta = RAIZ / 'config' / 'universo.json'
    universo = json.loads(ruta.read_text(encoding='utf-8'))
    if 'BTCUSDT' in a.quitar:
        raise SystemExit('BTCUSDT debe estar en la cartera: es el activo de la práctica.')
    if fuera := [s for s in a.quitar if s not in universo['simbolos']] + [s for s in a.agregar if s in universo['simbolos']]:
        raise SystemExit(f'Revisa la lista: {fuera} no se pueden quitar (no están) o agregar (ya están).')

    m = mexc.Mexc()
    volumenes = {t['symbol']: float(t.get('quoteVolume') or 0) for t in m._get('/api/v3/ticker/24hr', {}) if t['symbol'] in a.agregar}
    lecturas = {}  # spread en varias lecturas, no en una sola
    for _ in range(5):
        for s, q in m.libro(a.agregar).items():
            if q['ask'] > 0:
                lecturas.setdefault(s, []).append((q['ask'] - q['bid']) / q['ask'] * 10_000)
        time.sleep(1)

    ahora = datetime.now(timezone.utc)
    fin = int(ahora.timestamp() * 1000)
    inicio = int(datetime(2017, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    for s in a.agregar:
        par = m._get('/api/v3/exchangeInfo', {'symbol': s})['symbols'][0]
        if str(par.get('status')) != '1' or not par.get('isSpotTradingAllowed') or par.get('st'):
            raise SystemExit(f'{s} no está disponible para operar en MEXC.')
        crudo = data.frame_from_rows([f for f in m.history(s, inicio, fin) if f[6] <= fin])  # la vela abierta no se guarda
        auditoria = data.audit(crudo)
        limpio, bitacora = data.clean(crudo)
        if len(limpio) < HISTORIA:
            raise SystemExit(f'{s} tiene {len(limpio)} velas diarias seguidas; el bot necesita {HISTORIA}.')
        limpio.to_csv(RAIZ / 'data' / 'cartera' / f'{s}.csv', index=False)
        universo['fichas'][s] = dict(nombre=par.get('fullName'), volumen_24h=round(volumenes.get(s, 0.0)), spread_bps=round(statistics.median(lecturas.get(s, [float('nan')])), 1),
                                     dias=len(limpio), desde=limpio.date.iloc[0], hasta=limpio.date.iloc[-1], limpieza=bitacora,
                                     incoherentes=len(auditoria['incoherentes']), huella=data.dataset_hash(limpio))
        print(f'{s:16s} {len(limpio):5d} días desde {limpio.date.iloc[0]}  spread {universo["fichas"][s]["spread_bps"]} pb  volumen {volumenes.get(s, 0) / 1e3:,.0f} k', flush=True)

    universo['simbolos'] = [s for s in universo['simbolos'] if s not in a.quitar] + a.agregar
    universo.setdefault('cambios', []).append(dict(fecha=ahora.isoformat(timespec='seconds'), agregados=a.agregar, quitados=a.quitar, motivo=a.motivo))
    assert len(set(universo['simbolos'])) == len(universo['simbolos']) and 'BTCUSDT' in universo['simbolos']
    ruta.write_text(json.dumps(universo, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'{len(universo["simbolos"])} activos en config/universo.json. Corre scripts/comisiones_mexc.py, reinicia el bot y actívalo en el panel.')


if __name__ == '__main__':
    main()
