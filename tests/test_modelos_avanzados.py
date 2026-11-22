"""Modelos de investigación: entorno del agente, objetivo de Double DQN, partición sin TE y una corrida corta de cada uno."""
import numpy as np
import pytest
import torch

from bot import data
from research import modelos_avanzados as ma
from tests.helpers import random_walk, rows


@pytest.fixture(scope='module')
def datos():
    tabla = data.frame_from_rows(rows(random_walk(800, seed=3)))
    fechas = tabla.date.tolist()
    return ma.preparar_datos(tabla, fechas[520], fechas[700], fechas[701]), fechas


def test_el_entorno_cobra_el_gap_con_la_posicion_anterior_y_el_intradia_con_la_nueva():
    factor, recompensa = ma.paso_entorno(0, 1, gap=0.01, intradia=0.02, costo=0.0005)
    assert factor == pytest.approx(1.02 * (1 - 0.0005))  # sin posición no gana el gap; paga el cambio y gana el intradía
    assert recompensa == pytest.approx(100 * (factor - 1))
    assert ma.paso_entorno(1, 1, 0.01, 0.02, 0.0005)[0] == pytest.approx(1.01 * 1.02)  # mantener no cuesta
    assert ma.paso_entorno(1, 0, 0.01, 0.02, 0.0005)[0] == pytest.approx(1.01 * (1 - 0.0005))  # vender en la apertura


def test_double_dqn_elige_con_la_red_online_y_evalua_con_la_target():
    online = torch.tensor([[1.0, 3.0], [5.0, 2.0]])
    target = torch.tensor([[10.0, 20.0], [30.0, 40.0]])
    esperado = ma.objetivo_double_dqn(online, target, torch.tensor([1.0, 2.0]), torch.tensor([0.0, 1.0]), gamma=0.5)
    assert esperado.tolist() == [1 + 0.5 * 20, 2.0]  # la segunda es terminal: no hay valor futuro


def test_la_particion_nunca_llega_a_te_y_respeta_el_orden(datos):
    d, fechas = datos
    assert d['tabla'].date.max() == fechas[701]
    assert max(d['emision_EVAL']) <= fechas[700]
    assert d['emision_TR'][-1] < d['emision_SEL'][0] <= d['emision_SEL'][-1] < d['emision_EVAL'][0]
    assert abs(len(d['y_SEL']) - len(d['y_EVAL'])) <= 1


def test_cada_modelo_corre_y_devuelve_cifras_finitas(datos):
    d, _ = datos
    rec = ma.redes_recurrentes(d, epocas=2)
    assert {f['modelo'] for f in rec['filas']} >= {'Pronóstico cero', 'LSTM', 'GRU', 'LSTM bidireccional'}
    assert all(np.isfinite(f['medicion']['RMSE']) for f in rec['filas'])
    ae = ma.autoencoders(d, epocas=3)
    assert all(np.isfinite(f['mse_reconstruccion_medicion']) for f in ae['filas'])
    gen = ma.generativos(d, epocas_vae=2, epocas_gan=10, por_condicion=2)
    assert [f['fuente'] for f in gen['filas']] == ['Ventanas reales de VA', 'VAE condicional', 'GAN condicional', 'Remuestreo de días de TR']
    assert all(np.isfinite(f['cvar95_16_dias']) for f in gen['filas'])
    agente = ma.agente_double_dqn(d, episodios=1)
    efectivo = next(f for f in agente['filas'] if f['politica'] == 'Siempre en efectivo')
    assert efectivo['rendimiento'] == 0 and efectivo['rotacion'] == 0
