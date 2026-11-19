"""Auditoría por prefijos: el indicador en vivo debe coincidir con el histórico.

Inspiración metodológica (sin código copiado): Freqtrade lookahead-analysis.
No mide rentabilidad ni inspecciona el conjunto TE del proyecto.
"""
import pandas as pd
import pytest

from bot.data import frame_from_rows
from bot.features import INDICADORES, add_indicators
from tests.helpers import random_walk, rows


@pytest.mark.parametrize('corte', [14, 20, 26, 34, 60, 119])
@pytest.mark.parametrize('semilla', [1, 7, 29])
def test_calculo_en_vivo_coincide_con_historia_completa(corte, semilla):
    tabla = frame_from_rows(rows(random_walk(140, seed=semilla)))
    columnas = ['ret', 'sma20', *INDICADORES]
    completo = add_indicators(tabla)
    parcial = add_indicators(tabla.iloc[:corte].copy())
    pd.testing.assert_frame_equal(
        parcial[columnas], completo.iloc[:corte][columnas],
        check_exact=False, rtol=1e-12, atol=1e-12,
    )
