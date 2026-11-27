"""La cartera conjunta reparte cada ejemplo en TR, VA o TE por su fecha objetivo; con cortes dados, usa esos y no los de BTC."""
import numpy as np

from bot import data, features
from research import cartera, lab

DIA = 86_400_000
INICIO = 1_672_531_200_000  # 2023-01-01 UTC


def tabla(semilla, dias=420):
    cierres = 100 * np.cumprod(1 + np.random.default_rng(semilla).normal(0.0005, 0.02, dias))
    filas = [[INICIO + i * DIA, str(cierres[i - 1] if i else cierres[0]), str(cierres[i] * 1.01), str(cierres[i] * 0.99), str(cierres[i]), '10', INICIO + (i + 1) * DIA - 1, '100']
             for i in range(dias)]
    return lab.tabla_comun(data.add_target(features.add_indicators(data.frame_from_rows(filas))))


def test_con_cortes_dados_cada_ejemplo_cae_en_su_conjunto_por_fecha_objetivo():
    d = cartera.preparar_conjunto({'BTCUSDT': tabla(1), 'ETHUSDT': tabla(2)}, fin_tr='2023-09-30', fin_va='2023-12-31')
    assert (d['fin_tr'], d['fin_va']) == ('2023-09-30', '2023-12-31')
    assert max(d['objetivo_TR']) <= '2023-09-30' < min(d['objetivo_VA'])
    assert max(d['objetivo_VA']) <= '2023-12-31' < min(d['objetivo_TE'])
    assert set(d['activo_TR']) == set(d['activo_VA']) == {'BTCUSDT', 'ETHUSDT'}


def test_sin_cortes_usa_los_de_btc():
    tablas = {'BTCUSDT': tabla(1), 'ETHUSDT': tabla(2)}
    btc = lab.preparar(tablas['BTCUSDT'], cartera.VARIABLES)
    d = cartera.preparar_conjunto(tablas)
    assert (d['fin_tr'], d['fin_va']) == (btc['objetivo_TR'][-1], btc['objetivo_VA'][-1])
