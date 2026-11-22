"""Sharpe, Sortino, VaR y CVaR con ejemplos resueltos a mano."""
import numpy as np
import pytest

from bot.metricas_riesgo import metricas_riesgo, var_cvar


def patrimonio(rendimientos, inicial=100.0):
    return inicial * np.cumprod(np.r_[1.0, 1 + np.asarray(rendimientos)])


def test_sharpe_y_sortino_diarios_con_tres_rendimientos():
    # media 1 %, desviación muestral 3 %, desviación a la baja sqrt(0.0004 / 3)
    m = metricas_riesgo(patrimonio([-0.02, 0.01, 0.04]), periodos=1)
    assert m['sharpe'] == pytest.approx(1 / 3)
    assert m['sortino'] == pytest.approx(0.01 / np.sqrt(0.0004 / 3))
    assert m['sortino'] == pytest.approx(0.87, abs=0.005)


def test_var_y_cvar_historicos_con_veinte_sesiones_al_90():
    r = np.r_[-0.07, -0.04, -0.03, np.full(17, 0.01)]
    var, cvar = var_cvar(r, c=0.90)
    assert var == pytest.approx(0.03)  # observación 18 de 20 en orden ascendente
    assert cvar == pytest.approx((0.07 + 0.04) / 2)  # la cola tiene 2 observaciones


def test_cvar_con_cola_fraccionaria():
    r = np.r_[-0.08, -0.06, -0.04, np.full(47, 0.005)]
    _, cvar = var_cvar(r, c=0.95)
    assert cvar == pytest.approx((0.08 + 0.06 + 0.5 * 0.04) / 2.5)  # 2.5 observaciones equivalentes


def test_sin_dispersion_sharpe_queda_indefinido_y_con_poca_historia_no_hay_metricas():
    plano = metricas_riesgo([100.0, 100.0, 100.0, 100.0])
    assert plano['sharpe'] is None and plano['sortino'] is None and plano['var'] == 0.0
    assert metricas_riesgo([100.0, 101.0])['volatilidad_anual'] is None


def test_la_tasa_libre_de_riesgo_baja_el_sharpe():
    p = patrimonio(np.tile([0.01, -0.005, 0.002], 40))
    assert metricas_riesgo(p, tasa_anual=0.04)['sharpe'] < metricas_riesgo(p)['sharpe']
