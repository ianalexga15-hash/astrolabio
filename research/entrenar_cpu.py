"""Entrenamiento de desarrollo en la laptop (CPU). Sirve para integrar y probar el agente HOY.

No sustituye al entrenamiento en T4 con Colab (notebook): sus modelos quedan como de desarrollo. Este script nunca abre TE.
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault('KERAS_BACKEND', 'torch')
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from bot import data, features  # noqa: E402
from research import lab  # noqa: E402

COMISION_VA = 0.001  # costo supuesto (0.10% por lado) al elegir la regla


def main():
    tabla = pd.read_csv(RAIZ / 'data/processed/BTCUSDT_1d.csv')
    ficha = json.loads((RAIZ / 'data/processed/BTCUSDT_1d.ficha.json').read_text(encoding='utf-8'))
    tabla = data.add_target(features.add_indicators(tabla))
    kw = dict(epocas=int(os.environ.get('EPOCAS', 150)), lote=64, paciencia=12)
    version = f'dev-cpu-{ficha["periodo_limpio"][1]}'
    salida = RAIZ / 'models' / version
    salida.mkdir(parents=True, exist_ok=True)
    experimentos, curvas, reglas, todos, ventanas = [], {}, [], [], []
    tabla = lab.tabla_comun(tabla)
    for nombre, variables in lab.CONJUNTOS_VARIABLES.items():
        d = lab.preparar(tabla, variables)
        velas = lab.velas_de(tabla, d['emision_VA'])
        candidatos = lab.probar_referencias(d, nombre, experimentos)
        for tipo, configs in (('mlp', lab.CONFIGS_MLP), ('lstm', lab.CONFIGS_LSTM)):
            c = lab.probar_red(d, nombre, tipo, configs, experimentos, curvas, **kw)
            print(f'{nombre} {c["nombre"]}: RMSE_VA media={c["rmse_media"]:.6f} desv={c["rmse_desv"]:.6f}', flush=True)
            candidatos.append(c)
        ventanas += [dict(variables=nombre, **f) for f in lab.validacion_expansiva(d, [(c['tipo'], c['cfg']) for c in candidatos if 'cfg' in c], **kw)]
        for c in candidatos:
            c['casi_constante'] = lab.casi_constante(c['pred_va'])
            c['metricas_va'] = lab.metricas(d['y_VA'], c['pred_va'])
            c['reglas'] = lab.probar_reglas(c['pred_va'], velas, COMISION_VA)
            c['regla'] = lab.elegir_regla(c['reglas'])
            reglas += [dict(variables=nombre, modelo=c['nombre'], **r) for r in c['reglas']]
        todos += [(d, velas, c, nombre) for c in candidatos]

    # Sistema final: mayor rendimiento neto en VA; en empate, menor drawdown. TE no interviene.
    d, velas, c, nombre_vars = max(todos, key=lambda t: (round(t[2]['regla']['rendimiento'], 10), -t[2]['regla']['drawdown']))
    print('ELEGIDO', nombre_vars, c['nombre'], c['regla'], flush=True)
    if c['tipo'] == 'lineal':
        miembros, pesos = lab.contrato_lineal(d, c['ajuste'])
    else:
        miembros, pesos = lab.contrato_redes(c['resultados'])
    velas_pasivas = lab.comprar_y_mantener(velas, COMISION_VA)
    resumen = dict(periodo_va=[d['emision_VA'][0], d['emision_VA'][-1]], modelo=c['nombre'], variables=nombre_vars, regla=c['regla'], metricas_va=c['metricas_va'],
                   comprar_y_mantener_va=dict(rendimiento=velas_pasivas['rendimiento'], drawdown=velas_pasivas['drawdown']), rmse_cero_va=lab.metricas(d['y_VA'], np.zeros_like(d['y_VA']))['RMSE'],
                   particion=lab.tabla_particion(d).to_dict('records'))
    m = lab.guardar_modelo(salida, version, c['tipo'], d, c['regla']['umbral'], c['regla']['filtro'], miembros, pesos,
                           extra=dict(valido_para_entrega=False, dispositivo='cpu', motivo='Modelo de desarrollo: sin evidencia de T4.', huella_datos=ficha['huella_limpio'],
                                      nombre=c['nombre'], conjunto_variables=nombre_vars, seleccion=resumen))
    assert np.allclose(m.predecir_x(d['ventanas'].X[d['indices']['VA']]), c['pred_va'], atol=1e-5), 'La exportación no reproduce las predicciones.'

    pd.DataFrame(experimentos).to_csv(salida / 'experimentos.csv', index=False)
    pd.DataFrame(reglas).to_csv(salida / 'reglas_va.csv', index=False)
    pd.DataFrame(ventanas).to_csv(salida / 'ventanas_expansivas.csv', index=False)
    (salida / 'curvas.json').write_text(json.dumps(curvas), encoding='utf-8')

    # Diagnóstico de sesgo y varianza con las variables elegidas
    print('Diagnóstico de sesgo y varianza...', flush=True)
    diagnostico = lab.tacticas_clasicas(d) + lab.tacticas_redes(d, **kw)  # con las variables del sistema elegido
    (salida / 'diagnostico.json').write_text(json.dumps(diagnostico, indent=2, ensure_ascii=False), encoding='utf-8')
    (RAIZ / 'models/ACTIVO.txt').write_text(version, encoding='utf-8')
    print(json.dumps(resumen, indent=2, ensure_ascii=False, default=str), flush=True)


if __name__ == '__main__':
    main()
