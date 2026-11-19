import numpy as np
import pandas as pd
import pytest

from bot import data, features
from tests.helpers import random_walk, rows


def frame(closes):
    return data.frame_from_rows(rows(closes))


def test_ninguna_variable_cambia_si_se_altera_el_futuro():
    closes = random_walk(120, seed=1)
    base = features.add_indicators(frame(closes))
    alterado = closes[:100] + [c * 3 for c in closes[100:]]
    otra = features.add_indicators(frame(alterado))
    columnas = list(features.INDICADORES) + ['ret']
    pd.testing.assert_frame_equal(base.loc[:99, columnas], otra.loc[:99, columnas])


def test_distancia_a_sma20():
    closes = [100.0] * 19 + [120.0]
    df = features.add_indicators(frame(closes))
    assert df.dist_sma20.iloc[-1] == pytest.approx(120 / 101 - 1)


def test_volatilidad_es_desviacion_muestral_de_20_rendimientos_sin_anualizar():
    closes = random_walk(30, seed=2)
    df = features.add_indicators(frame(closes))
    r = np.diff(closes) / np.array(closes[:-1])
    assert df.vol20.iloc[-1] == pytest.approx(np.std(r[-20:], ddof=1))


def test_rsi_sin_perdidas_vale_100_y_sin_movimiento_vale_50():
    assert features.add_indicators(frame([100.0 + i for i in range(40)])).rsi14.iloc[-1] == pytest.approx(100)
    assert features.add_indicators(frame([100.0] * 40)).rsi14.iloc[-1] == pytest.approx(50)


def test_macd_normalizado_usa_12_26_9():
    closes = random_walk(120, seed=3)
    df = features.add_indicators(frame(closes))
    c = pd.Series(closes)
    macd = c.ewm(span=12, adjust=False, min_periods=12).mean() - c.ewm(span=26, adjust=False, min_periods=26).mean()
    hist = macd - macd.ewm(span=9, adjust=False, min_periods=9).mean()
    assert df.macd_hist.iloc[-1] == pytest.approx(hist.iloc[-1] / closes[-1])


def test_atr_usa_rango_verdadero_con_suavizado_de_wilder():
    df = frame(random_walk(60, seed=4))
    salida = features.add_indicators(df)
    previo = df.close.shift()
    tr = pd.concat([df.high - df.low, (df.high - previo).abs(), (df.low - previo).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    assert salida.atr14.iloc[-1] == pytest.approx(atr.iloc[-1] / df.close.iloc[-1])


def test_valores_iniciales_quedan_vacios_no_se_rellenan_hacia_atras():
    df = features.add_indicators(frame(random_walk(60)))
    assert df.dist_sma20.iloc[:19].isna().all() and df.dist_sma20.iloc[19:].notna().all()
    assert df.vol20.iloc[:20].isna().all() and df.vol20.iloc[20:].notna().all()


def test_primera_fecha_valida_se_documenta_por_indicador():
    df = features.add_indicators(frame(random_walk(60)))
    primera = features.first_valid_dates(df)
    assert primera['dist_sma20'] == df.date.iloc[19]
    assert primera['vol20'] == df.date.iloc[20]


def test_ventanas_tienen_forma_y_fechas_correctas():
    df = data.add_target(features.add_indicators(frame(random_walk(80))))
    v = features.make_windows(df, ['ret'], lookback=20)
    assert v.X.shape == (len(v.y), 20, 1)
    ultima = len(df) - 2  # la última fila no tiene objetivo observable
    assert v.emision[-1] == df.date.iloc[ultima]
    assert v.objetivo[-1] == df.date.iloc[ultima + 1]
    assert v.inicio[-1] == df.date.iloc[ultima - 19]
    assert v.X[-1, -1, 0] == pytest.approx(df.ret.iloc[ultima])
    assert v.y[-1] == pytest.approx(df.close.iloc[ultima + 1] / df.close.iloc[ultima] - 1)


def test_ventana_no_contiene_el_objetivo_que_pronostica():
    df = data.add_target(features.add_indicators(frame(random_walk(80, seed=7))))
    v = features.make_windows(df, ['ret'], lookback=20)
    # El rendimiento objetivo de cada ejemplo aparece como entrada solo en ejemplos posteriores.
    assert v.y[0] == pytest.approx(v.X[1, -1, 0])
    assert not np.isclose(v.X[0, :, 0], v.y[0]).any()


def test_ventanas_rechazan_historia_insuficiente():
    df = data.add_target(features.add_indicators(frame(random_walk(10))))
    with pytest.raises(data.DataError, match='insuficiente'):
        features.make_windows(df, ['ret'], lookback=20)


def test_ventanas_rechazan_variable_desconocida():
    df = data.add_target(features.add_indicators(frame(random_walk(40))))
    with pytest.raises(data.DataError, match='no_existe'):
        features.make_windows(df, ['no_existe'], lookback=5)


def test_ultima_ventana_usa_solo_la_ultima_vela_cerrada():
    df = features.add_indicators(frame(random_walk(80, seed=5)))
    x, fecha = features.latest_window(df, ['ret', 'vol20'], lookback=20)
    assert x.shape == (1, 20, 2)
    assert fecha == df.date.iloc[-1]
    assert x[0, -1, 0] == pytest.approx(df.ret.iloc[-1])


def test_ultima_ventana_rechaza_valores_no_finitos():
    df = features.add_indicators(frame(random_walk(30, seed=5)))
    with pytest.raises(data.DataError, match='vol20'):
        features.latest_window(df, ['vol20'], lookback=20)


def test_escalador_se_ajusta_solo_con_entrenamiento_y_no_cambia_al_transformar_otro_conjunto():
    tr = np.array([[[1.0], [3.0]], [[5.0], [7.0]]])
    otro = np.array([[[100.0], [200.0]]])
    s = features.Scaler.fit(tr)
    assert s.media[0] == pytest.approx(4.0)
    antes = (s.media.copy(), s.desv.copy())
    s.transform(otro)
    assert np.array_equal(antes[0], s.media) and np.array_equal(antes[1], s.desv)


def test_escalador_rechaza_dimensiones_incorrectas():
    s = features.Scaler.fit(np.ones((4, 3, 2)) + np.arange(4)[:, None, None])
    with pytest.raises(data.DataError, match='esperada'):
        s.transform(np.ones((4, 3)))
    with pytest.raises(data.DataError, match='esperada'):
        s.transform(np.ones((4, 3, 5)))


def test_escalador_no_divide_entre_cero():
    s = features.Scaler.fit(np.ones((4, 3, 1)))
    assert np.isfinite(s.transform(np.ones((1, 3, 1)))).all()


def test_escalador_se_puede_guardar_y_recuperar():
    s = features.Scaler.fit(np.arange(24.0).reshape(4, 3, 2))
    otro = features.Scaler.from_dict(s.to_dict())
    x = np.arange(6.0).reshape(1, 3, 2)
    assert np.array_equal(s.transform(x), otro.transform(x))
