"""Máquina del tiempo: antes de comprar, repasa miles de veces los próximos días con las velas del propio activo."""
import dataclasses

import numpy as np
import pytest

from bot.maquina_tiempo import repasar
from tests.helpers import random_walk
from tests.test_risk import L


def velas(cierres, rango=0.002):
    """Velas diarias (apertura, máximo, mínimo, cierre) que abren en el cierre anterior, con un rango pequeño."""
    filas, previo = [], cierres[0]
    for c in cierres:
        filas.append([previo, max(previo, c) * (1 + rango), min(previo, c) * (1 - rango), c])
        previo = c
    return np.array(filas)


def repaso(v, limites=L):
    return repasar(v, atr_abs=0.03 * v[-1, 3], limites=limites)


def test_si_el_activo_viene_subiendo_llega_primero_al_objetivo_y_gana_en_promedio():
    r = repaso(velas([100 * 1.02 ** i for i in range(80)]))
    assert r['objetivo'] > 0.95 and r['r_medio'] > 1.5


def test_si_el_activo_viene_cayendo_llega_primero_al_stop_y_pierde_en_promedio():
    r = repaso(velas([100 * 0.98 ** i for i in range(80)]))
    assert r['stop'] > 0.95 and r['r_medio'] < -0.9


def test_un_salto_por_debajo_del_stop_sale_a_la_apertura_y_pierde_mas_de_1_r():
    filas, previo = [], 100.0
    for _ in range(80):  # cada día abre 10 % abajo: el stop a 2 ATR (6 %) no alcanza a proteger
        a = previo * 0.9
        filas.append([a, a * 1.001, a * 0.999, a])
        previo = a
    assert repaso(np.array(filas))['r_medio'] < -1.5


def test_es_reproducible_y_las_comisiones_bajan_el_promedio():
    v = velas(random_walk(120, seed=3))
    assert repaso(v) == repaso(v)
    assert repaso(v, dataclasses.replace(L, comision=0.001))['r_medio'] < repaso(v)['r_medio']


def test_sin_historia_suficiente_no_opina():
    assert repaso(velas([100.0] * 60)) is None


def test_repasa_con_el_mismo_objetivo_que_pone_el_bot():
    v = velas([100 * 1.02 ** i for i in range(80)])  # sube siempre: cada repaso sale en el objetivo; riesgo de 2 ATR = 6 %
    assert repaso(v)['r_medio'] == pytest.approx(0.12 / 0.06 - 2 * 5 / 10_000 / 0.06)  # 4 ATR = +12 %
    lim = dataclasses.replace(L, objetivo_pct=0.13, comision_por_par=(('BTCUSDT', 0.0005),))
    r = repaso(v, lim)  # +13 % más la comisión del par, 0.05 %
    assert r['objetivo'] == 1.0 and r['r_medio'] == pytest.approx(0.1305 / 0.06 - 2 * (0.0005 + 5 / 10_000) / 0.06)


def test_con_punto_de_equilibrio_repasa_la_misma_salida_que_paper():
    # Todos los días iguales: abre en el cierre anterior, sube a +5 %, baja a −3 % y cierra en +2 %. Con ATR de 2 % y sin
    # punto de equilibrio, el stop móvil (cierre − 2 ATR) aguanta y el tercer día llega al objetivo a 4 ATR (+8 %).
    filas, previo = [], 100.0
    for _ in range(61):
        filas.append([previo, previo * 1.05, previo * 0.97, previo * 1.02])
        previo *= 1.02
    v = np.array(filas)
    lim = dataclasses.replace(L, stop_atr=2.0, trailing_atr=2.0, objetivo_atr=4.0, objetivo_pct=0.0, comision=0.001, deslizamiento_bps=5.0)
    assert repasar(v, 0.02 * v[-1, 3], lim)['objetivo'] == 1.0
    # Con proteger_atr = 0.5, el primer cierre (+2 %) sube el stop a la entrada más costos, como paper.mover_trailing,
    # y el mínimo del segundo día (−1.06 % desde la entrada) lo toca: todos salen en el stop.
    r = repasar(v, 0.02 * v[-1, 3], dataclasses.replace(lim, proteger_atr=0.5))
    assert r['stop'] == 1.0
    costo = 2 * 0.001 + 5 / 10_000  # el que pasan agent.py y reflejo.py a paper.mover_trailing
    assert r['r_medio'] == pytest.approx(costo / 0.04 - 2 * (0.001 + 5 / 10_000) / 0.04)


def test_los_costos_cuentan_comision_y_deslizamiento_al_entrar_y_al_salir():
    v = velas([100.0] * 80, rango=0.0)  # precio plano: nunca toca stop ni objetivo y cada repaso sigue en la entrada
    r = repaso(v)  # L: comisión 0 y 5 puntos base de deslizamiento por lado; ATR 3, riesgo 6
    assert r['abiertas'] == 1.0 and r['r_medio'] == pytest.approx(-2 * 5 / 10_000 * 100 / 6)

