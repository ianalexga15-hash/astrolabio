"""Reglas de evaluación y simulación del laboratorio."""
import math

import numpy as np
import pandas as pd
import pytest

from research import lab


def test_metricas_en_escala_original_y_precision_direccional_excluye_ceros():
    y = np.array([0.02, -0.01, 0.0, 0.03])
    p = np.array([0.01, 0.01, 0.02, 0.0])
    m = lab.metricas(y, p)
    assert m['MAE'] == pytest.approx(np.mean(np.abs(p - y)))
    assert m['RMSE'] == pytest.approx(np.sqrt(np.mean((p - y) ** 2)))
    assert m['direccional'] == pytest.approx(0.5)  # solo cuentan los pares sin ceros: uno acierta y otro falla


def test_precision_direccional_no_definida_sin_denominador():
    m = lab.metricas(np.array([0.0, 0.0]), np.array([0.0, 0.0]))
    assert m['direccional'] is None


def test_metricas_rechazan_formas_distintas_y_no_finitos():
    with pytest.raises(ValueError, match='longitud'):
        lab.metricas(np.zeros(3), np.zeros(4))
    with pytest.raises(ValueError, match='finit'):
        lab.metricas(np.array([np.nan]), np.array([0.0]))


def test_metricas_aplanan_para_evitar_el_error_de_broadcasting():
    y = np.array([[0.01], [0.02]])  # (n,1) contra (n,): el error que señalaban los notebooks
    p = np.array([0.01, 0.02])
    assert lab.metricas(y, p)['RMSE'] == pytest.approx(0.0)


def velas(precios_apertura, precios_cierre):
    n = len(precios_apertura)
    return pd.DataFrame({'date': [f'2026-01-{i + 1:02d}' for i in range(n)], 'open': precios_apertura, 'close': precios_cierre})


def test_senal_del_cierre_se_ejecuta_en_la_apertura_siguiente():
    v = velas([100, 110, 120, 130], [105, 115, 125, 135])
    r = lab.simular(v, [True, True, False, False], comision=0.0, capital=1000.0)
    # Compra en la apertura del día 2 (110), vende en la apertura del día 4 (130).
    assert r['operaciones'] == 1
    assert r['patrimonio_final'] == pytest.approx(1000 * 130 / 110)


def test_comision_se_cobra_por_compra_y_por_venta_solo_cuando_cambia_la_posicion():
    v = velas([100.0] * 6, [100.0] * 6)
    r = lab.simular(v, [True, True, True, False, False, False], comision=0.001, capital=1000.0)
    assert r['operaciones'] == 1
    assert r['costos'] == pytest.approx(2 * (1000 / 1.001) * 0.001, rel=1e-9)  # una compra y su venta: dos cargos
    assert r['patrimonio_final'] == pytest.approx(1000 / 1.001 * 0.999)


def test_liquida_al_ultimo_cierre_y_cobra_venta():
    v = velas([100, 100, 100], [100, 100, 200])
    r = lab.simular(v, [True, True, True], comision=0.001, capital=1000.0)
    assert r['operaciones'] == 1
    assert r['patrimonio_final'] == pytest.approx(1000 / 1.001 * 2 * 0.999)


def test_comprar_y_mantener_arranca_en_la_misma_fecha_con_costos_equivalentes():
    v = velas([100, 110, 120], [105, 115, 121])
    r = lab.comprar_y_mantener(v, comision=0.001, capital=1000.0)
    assert r['patrimonio_final'] == pytest.approx(1000 / 1.001 / 110 * 121 * 0.999)


def test_efectivo_no_cambia_y_win_rate_no_definido_sin_operaciones():
    v = velas([100, 110, 120], [105, 115, 125])
    r = lab.simular(v, [False, False, False], comision=0.001, capital=1000.0)
    assert r['patrimonio_final'] == 1000.0 and r['win_rate'] is None and r['operaciones'] == 0


def test_win_rate_cuenta_operaciones_cerradas_con_beneficio_neto():
    v = velas([100, 100, 110, 110, 100, 100], [100, 100, 110, 110, 100, 100])
    # Gana una (100→110) y otra queda sin beneficio neto (100→100).
    r = lab.simular(v, [True, True, False, True, False, False], comision=0.0, capital=1000.0)
    assert r['operaciones'] == 2 and r['win_rate'] == pytest.approx(0.5)


def test_maximo_drawdown_desde_un_maximo_previo():
    assert lab.max_drawdown(np.array([100, 120, 60, 90, 130.0])) == pytest.approx(0.5)


def test_tabla_de_simulacion_tiene_sus_columnas():
    v = velas([100, 110, 120], [105, 115, 125])
    r = lab.simular(v, [True, False, False], comision=0.001, capital=1000.0)
    assert {'fecha', 'precio_ejecucion', 'senal', 'posicion', 'efectivo', 'costos', 'patrimonio'} <= set(r['tabla'].columns)


def test_elige_umbral_por_rendimiento_neto_y_empata_por_menor_drawdown():
    resultados = [dict(umbral=0.001, rendimiento=0.10, drawdown=0.20), dict(umbral=0.002, rendimiento=0.10, drawdown=0.05),
                  dict(umbral=0.003, rendimiento=0.02, drawdown=0.01)]
    assert lab.elegir_regla(resultados)['umbral'] == 0.002


def test_umbrales_candidatos_son_hasta_cinco_y_positivos():
    assert 0 < len(lab.UMBRALES) <= 5 and all(u > 0 for u in lab.UMBRALES)


def test_ventanas_expansivas_siempre_entrenan_antes_del_bloque_y_dentro_de_tr():
    folds = lab.folds_expansivos(1000, 3)
    assert len(folds) == 3
    fin_anterior = 0
    for tr, bloque in folds:
        assert tr[0] == 0 and tr[-1] < bloque[0] and bloque[-1] < 1000
        assert bloque[0] >= fin_anterior
        fin_anterior = bloque[-1]


def test_control_de_alineacion_detecta_solapamiento_temporal():
    bien = dict(TR=['2026-01-01', '2026-01-02'], VA=['2026-01-03'], TE=['2026-01-04'])
    lab.verificar_particion(bien)
    mal = dict(TR=['2026-01-01', '2026-01-03'], VA=['2026-01-03'], TE=['2026-01-04'])
    with pytest.raises(ValueError, match='TR'):
        lab.verificar_particion(mal)


def test_descomposicion_mide_varianza_entre_reentrenamientos():
    y = np.array([1.0, 2.0, 3.0])
    predicciones = np.array([[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]])  # dos reentrenamientos
    d = lab.descomposicion(y, predicciones)
    assert d['varianza'] == pytest.approx(1.0)
    assert d['mse'] == pytest.approx(np.mean((predicciones - y) ** 2))
    assert d['sesgo2_mas_ruido'] == pytest.approx(d['mse'] - d['varianza'])


def test_apertura_de_te_queda_sellada_y_detecta_contaminacion(tmp_path):
    sello = tmp_path / 'te.json'
    primero = lab.abrir_te(sello, huella='config-a')
    assert primero['contaminado'] is False
    assert lab.abrir_te(sello, huella='config-a')['aperturas'] == 2
    assert lab.abrir_te(sello, huella='config-b')['contaminado'] is True


def test_predicciones_casi_constantes_se_detectan():
    assert lab.casi_constante(np.full(100, 0.001))
    assert not lab.casi_constante(np.random.default_rng(0).normal(0, 0.01, 100))


def test_lineal_ajusta_con_solo_tr_y_ridge_reduce_coeficientes():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(200, 5))
    y = X @ np.array([1.0, 0, 0, 0, -1.0]) + rng.normal(0, 0.1, 200)
    w0, b0 = lab.ajustar_lineal(X, y, alpha=0.0)
    w1, b1 = lab.ajustar_lineal(X, y, alpha=1000.0)
    assert w0[0] == pytest.approx(1.0, abs=0.05)
    assert np.abs(w1).sum() < np.abs(w0).sum()
    assert math.isfinite(b0) and math.isfinite(b1)


def tabla_sintetica(n=420, seed=5):
    from bot import data, features
    from tests.helpers import random_walk, rows
    return data.add_target(features.add_indicators(data.frame_from_rows(rows(random_walk(n, seed=seed)))))


def test_tabla_comun_da_las_mismas_fechas_a_ambos_conjuntos_de_variables():
    t = lab.tabla_comun(tabla_sintetica())
    a = lab.preparar(t, ['ret'])
    b = lab.preparar(t, ['ret', 'dist_sma20', 'vol20'])
    assert a['objetivo_VA'] == b['objetivo_VA'] and a['emision_TR'] == b['emision_TR']


def test_preparar_ajusta_escalador_solo_con_tr():
    t = lab.tabla_comun(tabla_sintetica())
    d = lab.preparar(t, ['ret'])
    assert d['escalador'].media[0] == pytest.approx(d['Xcrudo_TR'].mean())
    assert d['X_TR'].mean() == pytest.approx(0, abs=1e-9)
    assert d['X_VA'].mean() != pytest.approx(0, abs=1e-9)


def test_validacion_expansiva_da_error_por_ventana_y_entrena_antes_del_bloque():
    d = lab.preparar(lab.tabla_comun(tabla_sintetica()), ['ret'])
    filas = lab.validacion_expansiva(d)
    assert len(filas) == 6  # tres ventanas por dos modelos clásicos
    for f in filas:
        assert f['entrenamiento_hasta'] < f['bloque_desde'] <= f['bloque_hasta']
        assert f['bloque_hasta'] < d['objetivo_VA'][0]  # VA y TE no intervienen
    assert {f['modelo'] for f in filas} == {'cero', 'lineal'}


def test_referencias_registran_tr_y_va_sin_tocar_te():
    d = lab.preparar(lab.tabla_comun(tabla_sintetica()), ['ret'])
    experimentos = []
    candidatos = lab.probar_referencias(d, 'rezagos', experimentos)
    assert {e['modelo'] for e in experimentos} == {'cero', 'lineal', 'ridge'}
    assert all('RMSE_VA' in e and 'RMSE_TR' in e and not any('TE' in k for k in e) for e in experimentos)
    assert all(c['tipo'] == 'lineal' for c in candidatos)


def test_huella_de_configuracion_cambia_si_cambia_algo():
    assert lab.huella({'a': 1}) == lab.huella({'a': 1})
    assert lab.huella({'a': 1}) != lab.huella({'a': 2})


def test_transicion_manual_del_entorno_coincide_con_el_simulador():
    t = lab.transicion_ejemplo(efectivo=1000.0, precio_ejecucion=100.0, cierre=102.0, comision=0.001)
    assert t['cantidad'] == pytest.approx(1000 / 1.001 / 100)
    assert t['costo'] == pytest.approx(1000 / 1.001 * 0.001)
    assert t['recompensa'] == pytest.approx(t['patrimonio_nuevo'] - 1000.0)
