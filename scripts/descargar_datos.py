"""Descarga velas diarias públicas de MEXC, guarda el original con su ficha y el procesado con su auditoría."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from bot import data, mexc  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--simbolo', default='BTCUSDT')
    p.add_argument('--inicio', default='2017-01-01')
    a = p.parse_args()
    ahora = datetime.now(timezone.utc)
    inicio = int(datetime.fromisoformat(a.inicio).replace(tzinfo=timezone.utc).timestamp() * 1000)
    fin = int(ahora.timestamp() * 1000)
    filas = mexc.Mexc().history(a.simbolo, inicio, fin)
    cerradas = [f for f in filas if f[6] <= fin]  # la vela abierta no se guarda
    crudo = data.frame_from_rows(cerradas)
    auditoria = data.audit(crudo)
    limpio, bitacora = data.clean(crudo)

    (RAIZ / 'data/raw').mkdir(parents=True, exist_ok=True)
    (RAIZ / 'data/processed').mkdir(parents=True, exist_ok=True)
    base = f'{a.simbolo}_1d'
    crudo.to_csv(RAIZ / f'data/raw/{base}.csv', index=False)
    limpio.to_csv(RAIZ / f'data/processed/{base}.csv', index=False)
    ficha = dict(
        activo=a.simbolo, mercado='Criptomonedas spot', plataforma='MEXC', fuente=mexc.BASE + '/api/v3/klines', frecuencia='1d',
        moneda_base=a.simbolo[:-4], moneda_cotizada=a.simbolo[-4:], zona_horaria='UTC', calendario='Continuo, sin días inhábiles',
        fecha_descarga=ahora.isoformat(timespec='seconds'), ajustes='Sin ajustes: precios tal como los reporta la plataforma; no hay dividendos ni particiones.',
        volumen='Reportado por la fuente, no estimado.', periodo_crudo=[auditoria['primera'], auditoria['ultima']],
        periodo_limpio=[limpio.date.iloc[0], limpio.date.iloc[-1]], filas_crudas=len(crudo), filas_limpias=len(limpio), auditoria=auditoria,
        limpieza=bitacora, huella_crudo=data.dataset_hash(crudo), huella_limpio=data.dataset_hash(limpio),
    )
    (RAIZ / f'data/processed/{base}.ficha.json').write_text(json.dumps(ficha, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(json.dumps({k: ficha[k] for k in ('periodo_crudo', 'periodo_limpio', 'filas_crudas', 'filas_limpias', 'limpieza', 'huella_limpio')}, indent=2, ensure_ascii=False))
    if len(limpio) < 1500:
        raise SystemExit(f'Solo hay {len(limpio)} observaciones válidas; se necesitan al menos 1,500.')


if __name__ == '__main__':
    main()
