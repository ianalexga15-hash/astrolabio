"""Candidatas v0.1 de investigación: no autorizan órdenes ni cambian el modelo activo.

Entrada: velas cerradas de 15 minutos de un único activo. Cada señal se conoce
al cierre; su primera ejecución posible corresponde a la vela siguiente.
"""
import numpy as np
import pandas as pd

from bot.features import add_indicators

VERSION = 'intradia-candidatas-0.1'
INTERVALO_MS = 15 * 60_000


def preparar(velas, ahora_ms):
    s = velas.copy().reset_index(drop=True)
    requeridas = ['open_time', 'close_time', 'open', 'high', 'low', 'close', 'volume']
    if not set(requeridas).issubset(s.columns) or len(s) < 60:
        raise ValueError('Se requieren al menos 60 velas OHLCV con tiempos.')
    if not np.isfinite(s[requeridas].to_numpy(dtype=float)).all():
        raise ValueError('Datos no finitos.')
    if (s.close_time >= ahora_ms).any():
        raise ValueError('Solo se aceptan velas cerradas.')
    if not s.open_time.diff().iloc[1:].eq(INTERVALO_MS).all():
        raise ValueError('Velas deben ser continuas, únicas y ordenadas de 15 minutos.')
    if (s.close_time < s.open_time).any() or (s.close_time >= s.open_time + INTERVALO_MS).any():
        raise ValueError('Duración de vela inválida.')
    if (s[['open', 'high', 'low', 'close']] <= 0).any().any() or (s.volume < 0).any():
        raise ValueError('Precio o volumen inválido.')
    if (s.high < s[['open', 'close', 'low']].max(axis=1)).any() or (s.low > s[['open', 'close']].min(axis=1)).any():
        raise ValueError('OHLC incoherente.')
    s = add_indicators(s)
    # VWAP acumulado de sesión UTC aproximado con precio típico OHLCV, no ticks.
    dia = pd.to_datetime(s.open_time, unit='ms', utc=True).dt.floor('D')
    tipico = (s.high + s.low + s.close) / 3
    acumulado = s.volume.groupby(dia).cumsum()
    s['vwap'] = (tipico * s.volume).groupby(dia).cumsum() / acumulado.replace(0, np.nan)
    # Primera sesión truncada no dispone de VWAP de sesión completo.
    if s.open_time.iloc[0] % 86_400_000:
        s.loc[dia == dia.iloc[0], 'vwap'] = np.nan
    s['vol_ratio'] = s.volume / s.volume.shift().rolling(20).mean().replace(0, np.nan)
    s['max20_previo'] = s.high.shift().rolling(20).max()
    return s


def criterios(velas, ahora_ms):
    """Todos los booleanos de cada candidata son obligatorios; no hay votos 3/5."""
    s = preparar(velas, ahora_ms)
    listo = s[['rsi14', 'macd_hist', 'bb_pos', 'atr14', 'vwap', 'vol_ratio']].notna().all(axis=1) & s.atr14.gt(0)
    conjuntos = {
        'tendencia': {
            'rsi': s.rsi14.between(50, 65),
            'macd': s.macd_hist.gt(0) & s.macd_hist.gt(s.macd_hist.shift()),
            'volumen': s.vol_ratio.ge(1),
            'vwap': s.close.gt(s.vwap) & s.close.gt(s.sma20),
            'bollinger': s.bb_pos.between(0, 0.9),
        },
        'recuperacion': {
            'rsi': s.rsi14.shift().lt(30) & s.rsi14.ge(30),
            'macd': s.macd_hist.gt(s.macd_hist.shift()),
            'volumen': s.vol_ratio.ge(1),
            'vwap': s.close.lt(s.vwap),
            'bollinger': s.bb_pos.shift().lt(-1) & s.bb_pos.ge(-1),
        },
        'ruptura': {
            'rsi': s.rsi14.between(50, 70),
            'macd': s.macd_hist.gt(0),
            'volumen': s.vol_ratio.ge(1.5),
            'vwap': s.close.gt(s.vwap),
            'ruptura20': s.close.gt(s.max20_previo),
        },
    }
    resultado = {}
    for nombre, reglas in conjuntos.items():
        tabla = pd.DataFrame(reglas).fillna(False).astype(bool)
        tabla['datos_validos'] = listo
        tabla['cumplidas'] = tabla[list(reglas)].sum(axis=1)
        tabla['senal_cierre'] = listo & tabla[list(reglas)].all(axis=1)
        tabla['entrada_siguiente'] = tabla.senal_cierre.shift(fill_value=False)
        resultado[nombre] = tabla
    return s, resultado
