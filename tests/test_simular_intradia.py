"""Simulador intradía de investigación: entrada causal, costos, stop primero, saltos, tiempo, sin duplicados y conciliación."""
import numpy as np
import pandas as pd
import pytest

from research.simular_intradia import PASO_MS, auditar, resumen, simular

INICIO = 1_700_000_000_000 - 1_700_000_000_000 % PASO_MS


def velas(precios, atr=0.01):
    """Velas planas al precio dado. atr14 es relativo al cierre, como lo da el generador: 0.01 a 100 son 1.0 en precio."""
    n = len(precios)
    s = pd.DataFrame({'open_time': INICIO + np.arange(n) * PASO_MS, 'open': precios, 'high': precios, 'low': precios, 'close': precios, 'volume': 1.0})
    s['close_time'] = s.open_time + PASO_MS - 1
    s['atr14'] = atr
    return s


def entradas(n, *indices):
    e = pd.Series(False, index=range(n))
    e.iloc[list(indices)] = True
    return e


def test_entra_en_la_apertura_siguiente_a_la_senal_y_cobra_costos_en_ambos_lados():
    s = velas([100.0] * 6)
    s.loc[3, 'high'] = 104.0  # objetivo: 100.1 + 3 ATR = 103.1
    ops, curva = simular(s, entradas(6, 1), comision=0.001, deslizamiento_bps=10, capital=10_000, riesgo=0.01, exposicion_max=1.0)
    o = ops[0]
    precio = 100.0 * 1.001
    cantidad = 100.0 / (2 * 1.0)  # riesgo 1 % de 10,000 entre la distancia al stop de 2 ATR
    assert o['entrada'] == s.open_time[1] and o['precio_entrada'] == pytest.approx(precio) and o['cantidad'] == pytest.approx(cantidad)
    assert o['motivo'] == 'objetivo' and o['precio_salida'] == pytest.approx(precio + 3)
    esperado = cantidad * (precio + 3) * (1 - 0.001) - cantidad * precio * (1 + 0.001)
    assert o['resultado'] == pytest.approx(esperado)


def test_si_la_vela_toca_stop_y_objetivo_cuenta_primero_el_stop():
    s = velas([100.0] * 5)
    s.loc[2, ['high', 'low']] = [110.0, 90.0]
    ops, _ = simular(s, entradas(5, 1), comision=0, deslizamiento_bps=0)
    assert ops[0]['motivo'] == 'stop' and ops[0]['precio_salida'] == pytest.approx(98.0)


def test_un_salto_bajo_el_stop_sale_a_la_apertura_disponible():
    s = velas([100.0, 100.0, 100.0, 95.0, 95.0])
    ops, _ = simular(s, entradas(5, 1), comision=0, deslizamiento_bps=0)
    assert ops[0]['motivo'] == 'stop' and ops[0]['precio_salida'] == pytest.approx(95.0)


def test_sin_tocar_stop_ni_objetivo_sale_por_tiempo_en_la_apertura_siguiente():
    s = velas([100.0] * 25)
    ops, _ = simular(s, entradas(25, 1), comision=0, deslizamiento_bps=0, max_velas=16)
    assert ops[0]['motivo'] == 'tiempo' and ops[0]['salida'] == s.open_time[17] and ops[0]['velas'] == 16


def test_las_senales_con_una_posicion_abierta_no_abren_otra():
    s = velas([100.0] * 30)
    ops, _ = simular(s, entradas(30, 1, 2, 3, 5), comision=0, deslizamiento_bps=0, max_velas=16)
    assert len(ops) == 1


def test_la_curva_concilia_con_el_resultado_de_las_operaciones():
    rng = np.random.default_rng(3)
    precios = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
    s = velas(precios, atr=0.008)
    s['high'] = s[['open', 'close']].max(axis=1) * 1.004
    s['low'] = s[['open', 'close']].min(axis=1) * 0.996
    s['open'] = s.close.shift(fill_value=precios[0])
    s['high'] = s[['open', 'high']].max(axis=1)
    s['low'] = s[['open', 'low']].min(axis=1)
    ops, curva = simular(s, pd.Series(rng.random(400) < 0.05), comision=0.0005, deslizamiento_bps=2, capital=10_000)
    assert len(ops) > 3
    assert curva.iloc[-1] == pytest.approx(10_000 + sum(o['resultado'] for o in ops))
    r = resumen(ops, curva, 10_000)
    assert r['operaciones'] == len(ops) and r['resultado_neto'] == pytest.approx(curva.iloc[-1] - 10_000) and 0 <= r['drawdown'] <= 1


def test_la_auditoria_informa_huecos_duplicados_ohlc_y_velas_abiertas():
    s = velas([100.0] * 10)[['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time']]
    s = pd.concat([s, s.iloc[[3]]]).drop(index=5).reset_index(drop=True)  # un duplicado y un hueco
    s.loc[0, 'high'] = 90.0  # high menor que el cierre
    a = auditar(s, fin_ms=int(s.close_time.max()))  # la última vela todavía no cerró
    assert (a['duplicados'], a['huecos'], a['velas_faltantes'], a['ohlc_incoherente'], a['abiertas']) == (1, 1, 1, 1, 1)
