"""Modelo conjunto para los activos de la cartera, en CPU. Nunca abre TE y no sustituye a la práctica en T4.

Junta los ejemplos de todos los activos con las mismas fechas de corte de BTC. Las variables son relativas, así que son comparables entre activos.
Elige modelo y regla con VA simulando la cartera completa a cupos iguales, y reporta cómo le fue a cada activo. El código común vive en research/cartera.py,
el mismo que usa el notebook de la cartera en T4.
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault('KERAS_BACKEND', 'torch')
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd  # noqa: E402

from research import cartera, lab  # noqa: E402

ENTRENAMIENTO = dict(epocas=int(os.environ.get('EPOCAS', 60)), lote=256, paciencia=8)


def main():
    inicio = time.time()
    tablas, _ = cartera.cargar_tablas(RAIZ)
    d = cartera.preparar_conjunto(tablas)
    print({k: len(d[f'y_{k}']) for k in ('TR', 'VA', 'TE')}, 'activos', len(tablas), 'corte TR', d['fin_tr'], 'corte VA', d['fin_va'], flush=True)
    version = f'dev-cartera-{d["fin_va"]}-{len(tablas)}'
    salida = RAIZ / 'models' / version
    salida.mkdir(parents=True, exist_ok=True)
    experimentos, curvas = [], {}
    candidatos = lab.probar_referencias(d, 'rezagos_indicadores', experimentos)
    for tipo, configs in (('mlp', lab.CONFIGS_MLP), ('lstm', lab.CONFIGS_LSTM)):
        c = lab.probar_red(d, 'rezagos_indicadores', tipo, configs, experimentos, curvas, **ENTRENAMIENTO)
        print(c['nombre'], f'RMSE_VA media={c["rmse_media"]:.6f} desv={c["rmse_desv"]:.6f} {time.time() - inicio:.0f}s', flush=True)
        candidatos.append(c)

    final, reglas = cartera.seleccionar(tablas, d, candidatos)
    sim, pasivo, resumen = cartera.guardar(salida, version, tablas, d, final, reglas, experimentos, curvas,
                                           extra=dict(valido_para_entrega=False, dispositivo='cpu', motivo='Modelo conjunto de desarrollo: sin evidencia de T4.'))
    (RAIZ / 'models/CARTERA.txt').write_text(version, encoding='utf-8')
    a = pd.DataFrame(sim['por_activo'])
    print('ELEGIDO', final['nombre'], final['regla'], flush=True)
    print('Cartera en VA:', round(sim['rendimiento'], 4), 'caída', round(sim['drawdown'], 4), 'comprar y mantener:', round(pasivo['rendimiento'], 4), 'caída', round(pasivo['drawdown'], 4), flush=True)
    print('RMSE conjunto', round(final['metricas_va']['RMSE'], 6), 'cero', round(resumen['rmse_cero_va'], 6), 'dirección', round(final['metricas_va']['direccional'], 4), flush=True)
    print('Activos que superan a pronóstico cero en RMSE:', int((a.RMSE < a.RMSE_cero).sum()), 'de', len(a), ' con rendimiento mayor a comprar y mantener:', int((a.rendimiento > a.comprar_y_mantener).sum()), flush=True)
    print(f'Listo en {time.time() - inicio:.0f} s. Versión {version}', flush=True)


if __name__ == '__main__':
    main()
