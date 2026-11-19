"""Modelo conjunto para los activos de la cartera, en CPU. Nunca abre TE y no sustituye a la práctica en T4.

Junta los ejemplos de todos los activos con las mismas fechas de corte de BTC. Las variables son relativas, así que son comparables entre activos.
Elige modelo y regla con VA simulando la cartera completa a cupos iguales, y reporta cómo le fue a cada activo.
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault('KERAS_BACKEND', 'torch')
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from bot import data, features  # noqa: E402
from research import lab  # noqa: E402

COSTO = 0.001
VARIABLES = lab.CONJUNTOS_VARIABLES['rezagos_indicadores']
ENTRENAMIENTO = dict(epocas=int(os.environ.get('EPOCAS', 60)), lote=256, paciencia=8)


def cargar_tablas():
    universo = json.loads((RAIZ / 'config/universo.json').read_text(encoding='utf-8'))
    tablas = {}
    for s in universo['simbolos']:
        t = pd.read_csv(RAIZ / 'data/cartera' / f'{s}.csv')
        tablas[s] = lab.tabla_comun(data.add_target(features.add_indicators(t)))
    return tablas, universo


def preparar_conjunto(tablas):
    btc = lab.preparar(tablas['BTCUSDT'], VARIABLES)
    fin_tr, fin_va = btc['objetivo_TR'][-1], btc['objetivo_VA'][-1]
    partes = {k: dict(X=[], y=[], emision=[], objetivo=[], activo=[]) for k in ('TR', 'VA', 'TE')}
    for s, t in tablas.items():
        v = features.make_windows(t, VARIABLES, 20)
        for i, f in enumerate(v.objetivo):
            k = 'TR' if f <= fin_tr else 'VA' if f <= fin_va else 'TE'
            p = partes[k]
            p['X'].append(v.X[i]); p['y'].append(v.y[i]); p['emision'].append(v.emision[i]); p['objetivo'].append(f); p['activo'].append(s)
    tr = np.stack(partes['TR']['X'])
    escalador = features.Scaler.fit(tr)
    y_tr = np.array(partes['TR']['y'])
    d = dict(variables=VARIABLES, lookback=20, escalador=escalador, y_media=float(y_tr.mean()), y_desv=float(y_tr.std()), fin_tr=fin_tr, fin_va=fin_va)
    orden_tr = np.random.default_rng(0).permutation(len(tr))  # solo baraja el orden de presentación dentro de TR; las fechas ya están separadas
    for k, p in partes.items():
        X = np.stack(p['X']) if p['X'] else np.zeros((0, 20, len(VARIABLES)))
        d[f'X_{k}'] = escalador.transform(X)
        d[f'Xcrudo_{k}'] = X
        d[f'y_{k}'] = np.array(p['y'])
        d[f'emision_{k}'] = p['emision']
        d[f'objetivo_{k}'] = p['objetivo']
        d[f'activo_{k}'] = np.array(p['activo'])
    del orden_tr
    return d


def simular_cartera(tablas, d, pronostico, umbral, filtro, capital=50_000.0):
    """Cupos iguales. Cada activo opera su regla; el patrimonio conjunto suma los cupos por fecha."""
    cupo = capital / len(tablas)
    series, por_activo = {}, []
    for s, t in tablas.items():
        mascara = d['activo_VA'] == s
        if not mascara.any():
            continue
        velas = lab.velas_de(t, [e for e, a in zip(d['emision_VA'], d['activo_VA']) if a == s])
        r = lab.simular(velas, lab.senales(pronostico[mascara], velas, umbral, filtro), COSTO, cupo)
        series[s] = r['tabla'].set_index('fecha').patrimonio
        m = lab.metricas(d['y_VA'][mascara], pronostico[mascara])
        pasivo = lab.comprar_y_mantener(velas, COSTO, cupo)
        por_activo.append(dict(simbolo=s, ejemplos=int(mascara.sum()), RMSE=m['RMSE'], RMSE_cero=lab.metricas(d['y_VA'][mascara], np.zeros(mascara.sum()))['RMSE'], direccional=m['direccional'],
                               rendimiento=r['rendimiento'], comprar_y_mantener=pasivo['rendimiento'], drawdown=r['drawdown'], operaciones=r['operaciones'], win_rate=r['win_rate'], costos=r['costos']))
    tabla = pd.DataFrame(series).sort_index().ffill().fillna(cupo)
    total = tabla.sum(axis=1) + (len(tablas) - tabla.shape[1]) * cupo
    return dict(rendimiento=float(total.iloc[-1] / capital - 1), drawdown=lab.max_drawdown(total.to_numpy()), operaciones=sum(a['operaciones'] for a in por_activo), costos=sum(a['costos'] for a in por_activo),
                ganadoras=np.mean([a['win_rate'] for a in por_activo if a['win_rate'] is not None]) if por_activo else None, por_activo=por_activo, serie=total)


def pasivo_cartera(tablas, d, capital=50_000.0):
    cupo = capital / len(tablas)
    series = {}
    for s, t in tablas.items():
        fechas = [e for e, a in zip(d['emision_VA'], d['activo_VA']) if a == s]
        if fechas:
            series[s] = lab.comprar_y_mantener(lab.velas_de(t, fechas), COSTO, cupo)['tabla'].set_index('fecha').patrimonio
    tabla = pd.DataFrame(series).sort_index().ffill().fillna(cupo)
    total = tabla.sum(axis=1) + (len(tablas) - tabla.shape[1]) * cupo
    return dict(rendimiento=float(total.iloc[-1] / capital - 1), drawdown=lab.max_drawdown(total.to_numpy()))


def main():
    inicio = time.time()
    tablas, universo = cargar_tablas()
    d = preparar_conjunto(tablas)
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

    reglas = []
    for c in candidatos:
        c['casi_constante'] = lab.casi_constante(c['pred_va'])
        c['metricas_va'] = lab.metricas(d['y_VA'], c['pred_va'])
        filas = []
        for filtro in lab.FILTROS:
            for umbral in lab.UMBRALES:
                r = simular_cartera(tablas, d, c['pred_va'], umbral, filtro)
                filas.append(dict(umbral=umbral, filtro=filtro, rendimiento=r['rendimiento'], drawdown=r['drawdown'], operaciones=r['operaciones'], win_rate=r['ganadoras'], costos=r['costos']))
        c['regla'] = lab.elegir_regla(filas)
        reglas += [dict(variables='rezagos_indicadores', modelo=c['nombre'], **f) for f in filas]
        print(c['nombre'], 'RMSE', round(c['metricas_va']['RMSE'], 6), 'regla', c['regla'], flush=True)

    final = max(candidatos, key=lambda c: (round(c['regla']['rendimiento'], 10), -c['regla']['drawdown']))
    miembros, pesos = (lab.contrato_lineal(d, final['ajuste']) if final['tipo'] == 'lineal' else lab.contrato_redes(final['resultados']))
    sim = simular_cartera(tablas, d, final['pred_va'], final['regla']['umbral'], final['regla']['filtro'])
    pasivo = pasivo_cartera(tablas, d)
    resumen = dict(periodo_va=[min(d['emision_VA']), max(d['emision_VA'])], modelo=final['nombre'], variables='rezagos_indicadores', regla=final['regla'], metricas_va=final['metricas_va'], comprar_y_mantener_va=pasivo,
                   rmse_cero_va=lab.metricas(d['y_VA'], np.zeros_like(d['y_VA']))['RMSE'], activos=len(tablas),
                   particion=[dict(conjunto=k, ejemplos=len(d[f'y_{k}']), primera_emision=min(d[f'emision_{k}']), ultima_emision=max(d[f'emision_{k}']), primer_objetivo=min(d[f'objetivo_{k}']), ultimo_objetivo=max(d[f'objetivo_{k}'])) for k in ('TR', 'VA', 'TE')])
    m = lab.guardar_modelo(salida, version, final['tipo'], d, final['regla']['umbral'], final['regla']['filtro'], miembros, pesos,
                           extra=dict(valido_para_entrega=False, dispositivo='cpu', motivo='Modelo conjunto de desarrollo: sin evidencia de T4.', nombre=final['nombre'], conjunto_variables='rezagos_indicadores', seleccion=resumen, activos=list(tablas)))
    assert np.allclose(m.predecir_x(d['Xcrudo_VA']), final['pred_va'], atol=1e-4), 'La exportación no reproduce las predicciones.'
    pd.DataFrame(experimentos).to_csv(salida / 'experimentos.csv', index=False)
    pd.DataFrame(reglas).to_csv(salida / 'reglas_va.csv', index=False)
    pd.DataFrame(sim['por_activo']).to_csv(salida / 'por_activo_va.csv', index=False)
    (salida / 'curvas.json').write_text(json.dumps(curvas), encoding='utf-8')
    (RAIZ / 'models/CARTERA.txt').write_text(version, encoding='utf-8')
    a = pd.DataFrame(sim['por_activo'])
    print('ELEGIDO', final['nombre'], final['regla'], flush=True)
    print('Cartera en VA:', round(sim['rendimiento'], 4), 'caída', round(sim['drawdown'], 4), 'comprar y mantener:', round(pasivo['rendimiento'], 4), 'caída', round(pasivo['drawdown'], 4), flush=True)
    print('RMSE conjunto', round(final['metricas_va']['RMSE'], 6), 'cero', round(resumen['rmse_cero_va'], 6), 'dirección', round(final['metricas_va']['direccional'], 4), flush=True)
    print('Activos que superan a pronóstico cero en RMSE:', int((a.RMSE < a.RMSE_cero).sum()), 'de', len(a), ' con rendimiento mayor a comprar y mantener:', int((a.rendimiento > a.comprar_y_mantener).sum()), flush=True)
    print(f'Listo en {time.time() - inicio:.0f} s. Versión {version}', flush=True)


if __name__ == '__main__':
    main()
