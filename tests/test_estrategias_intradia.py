import numpy as np
import pandas as pd
import pytest

from research.estrategias_intradia import criterios, preparar, INTERVALO_MS


def velas(n=200):
    t = np.arange(n)
    cierre = 100 + t * .03 + np.sin(t / 4)
    return pd.DataFrame(dict(open_time=t * INTERVALO_MS, close_time=(t + 1) * INTERVALO_MS - 1,
                             open=cierre, close=cierre, high=cierre + .5, low=cierre - .5, volume=100 + t % 11))


def test_futuro_no_cambia_criterios_pasados():
    s = velas()
    _, completo = criterios(s, 201 * INTERVALO_MS)
    _, prefijo = criterios(s.iloc[:120], 201 * INTERVALO_MS)
    for nombre in completo:
        pd.testing.assert_frame_equal(completo[nombre].iloc[:120], prefijo[nombre])
        tabla = completo[nombre]
        assert tabla.entrada_siguiente.equals(tabla.senal_cierre.shift(fill_value=False))
        assert not tabla.senal_cierre.iloc[:20].any()


def test_vwap_reinicia_en_sesion_utc():
    s = preparar(velas(), 201 * INTERVALO_MS)
    assert s.vwap.iloc[96] == pytest.approx((s.high.iloc[96] + s.low.iloc[96] + s.close.iloc[96]) / 3)


@pytest.mark.parametrize('fallo', ['abierta', 'hueco', 'duplicada', 'ohlc', 'nan'])
def test_datos_invalidos_bloquean(fallo):
    s = velas()
    ahora = 201 * INTERVALO_MS
    if fallo == 'abierta': ahora = s.close_time.iloc[-1]
    elif fallo == 'hueco': s = s.drop(80)
    elif fallo == 'duplicada': s.loc[80, 'open_time'] = s.open_time.iloc[79]
    elif fallo == 'ohlc': s.loc[80, 'high'] = 1
    elif fallo == 'nan': s.loc[80, 'close'] = np.nan
    with pytest.raises(ValueError): criterios(s, ahora)


def test_volumen_cero_no_produce_senales():
    s = velas()
    s.volume = 0
    _, tablas = criterios(s, 201 * INTERVALO_MS)
    assert all(not t.senal_cierre.any() for t in tablas.values())
