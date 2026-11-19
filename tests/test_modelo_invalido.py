import pandas as pd
import pytest

from bot.data import DataError
from bot.model import Modelo


@pytest.mark.parametrize('pronostico', [float('nan'), float('inf'), -float('inf')])
def test_pronostico_invalido_no_se_convierte_en_senal(pronostico):
    modelo = Modelo(dict(version='prueba', tipo='cero', lookback=1,
                         variables=['ret'], umbral=0, filtro='ninguno',
                         escalador=dict(media=[0], desv=[1])), {})
    with pytest.raises(DataError, match='Pronóstico no finito'):
        modelo.senal(pronostico, pd.DataFrame({'close': [100]}))
