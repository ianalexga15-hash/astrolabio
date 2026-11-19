"""Variables del modelo. La misma definición se usa al entrenar y en el agente.

Cada indicador usa solo historia disponible hasta t. Los primeros valores quedan vacíos.
"""
from collections import namedtuple

import numpy as np
import pandas as pd

from bot.data import DataError

Ventanas = namedtuple('Ventanas', 'X y inicio emision objetivo')

# Qué mide cada indicador y su fórmula; el notebook y el panel muestran esta tabla.
INDICADORES = {
    'dist_sma20': 'Distancia al promedio de 20 cierres: cierre / SMA20 - 1',
    'vol20': 'Desviación muestral de 20 rendimientos diarios, sin anualizar',
    'rsi14': 'RSI de 14 con suavizado de Wilder; 100 sin pérdidas, 50 sin movimiento',
    'macd_hist': 'MACD (EMA12 - EMA26) menos su señal EMA9, dividido entre el cierre',
    'bb_pos': 'Posición en bandas de Bollinger: (cierre - SMA20) / (2 desviaciones de 20 cierres)',
    'atr14': 'ATR de 14 con suavizado de Wilder, dividido entre el cierre',
    'vol_rel': 'Logaritmo del volumen entre su promedio de 20 días',
}


def _wilder(serie, periodo):
    return serie.ewm(alpha=1 / periodo, adjust=False, min_periods=periodo).mean()


def add_indicators(df):
    s = df.copy()
    cierre = s.close
    s['ret'] = cierre.pct_change(fill_method=None)
    s['sma20'] = cierre.rolling(20).mean()
    desv20 = cierre.rolling(20).std(ddof=1)
    s['dist_sma20'] = cierre / s.sma20 - 1
    s['vol20'] = s.ret.rolling(20).std(ddof=1)

    delta = cierre.diff()
    ganancia = _wilder(delta.clip(lower=0), 14)
    perdida = _wilder(-delta.clip(upper=0), 14)
    rsi = 100 - 100 / (1 + ganancia / perdida)
    rsi = rsi.where(perdida != 0, 100.0).where((ganancia != 0) | (perdida != 0), 50.0)
    s['rsi14'] = rsi.where(ganancia.notna())

    macd = cierre.ewm(span=12, adjust=False, min_periods=12).mean() - cierre.ewm(span=26, adjust=False, min_periods=26).mean()
    s['macd_hist'] = (macd - macd.ewm(span=9, adjust=False, min_periods=9).mean()) / cierre
    s['bb_pos'] = ((cierre - s.sma20) / (2 * desv20)).where(desv20 != 0, 0.0).where(s.sma20.notna())

    previo = cierre.shift()
    rango = pd.concat([s.high - s.low, (s.high - previo).abs(), (s.low - previo).abs()], axis=1).max(axis=1)
    s['atr14'] = _wilder(rango, 14) / cierre
    with np.errstate(divide='ignore', invalid='ignore'):
        s['vol_rel'] = np.log(s.volume / s.volume.rolling(20).mean())
    return s


def first_valid_dates(df):
    return {c: df.date[df[c].first_valid_index()] for c in INDICADORES if df[c].first_valid_index() is not None}


def _matriz(df, variables):
    faltantes = [v for v in variables if v not in df.columns]
    if faltantes:
        raise DataError(f'Variables inexistentes: {faltantes}. Disponibles: {list(df.columns)}.')
    return df[variables].to_numpy(dtype=float)


def make_windows(df, variables, lookback):
    """Ejemplos (n, pasos, variables). Cada uno termina en t y su objetivo es el rendimiento de t a t+1."""
    m = _matriz(df, variables)
    if 'y' not in df.columns:
        raise DataError('Falta la columna objetivo y: ejecuta add_target antes de construir ventanas.')
    y = df.y.to_numpy(dtype=float)
    X, Y, inicio, emision, objetivo = [], [], [], [], []
    for t in range(lookback - 1, len(df)):
        ventana = m[t - lookback + 1:t + 1]
        if np.isfinite(ventana).all() and np.isfinite(y[t]):
            X.append(ventana)
            Y.append(y[t])
            inicio.append(df.date.iloc[t - lookback + 1])
            emision.append(df.date.iloc[t])
            objetivo.append(df.date.iloc[t + 1])
    if not X:
        raise DataError(f'Historia insuficiente: {len(df)} filas no alcanzan para una ventana de {lookback} con {variables}.')
    return Ventanas(np.stack(X), np.array(Y), inicio, emision, objetivo)


def latest_window(df, variables, lookback):
    """Ventana de la última vela cerrada, para el pronóstico en vivo. Sin objetivo."""
    m = _matriz(df, variables)
    if len(m) < lookback:
        raise DataError(f'Historia insuficiente: hay {len(m)} velas y la ventana pide {lookback}.')
    x = m[-lookback:]
    if not np.isfinite(x).all():
        malas = [v for i, v in enumerate(variables) if not np.isfinite(x[:, i]).all()]
        raise DataError(f'Valores no finitos en {malas} dentro de la última ventana.')
    return x[None, ...], df.date.iloc[-1]


class Scaler:
    """Estandariza cada variable. Se ajusta solo con TR y después únicamente transforma."""

    def __init__(self, media, desv):
        self.media = np.asarray(media, dtype=float)
        self.desv = np.asarray(desv, dtype=float)

    @classmethod
    def fit(cls, X):
        if X.ndim != 3:
            raise DataError(f'Forma recibida {X.shape}; esperada (ejemplos, pasos, variables).')
        desv = X.std(axis=(0, 1))
        return cls(X.mean(axis=(0, 1)), np.where(desv > 0, desv, 1.0))

    def transform(self, X):
        if X.ndim != 3 or X.shape[2] != len(self.media):
            raise DataError(f'Forma recibida {X.shape}; esperada (ejemplos, pasos, {len(self.media)}).')
        return (X - self.media) / self.desv

    def to_dict(self):
        return {'media': self.media.tolist(), 'desv': self.desv.tolist()}

    @classmethod
    def from_dict(cls, d):
        return cls(d['media'], d['desv'])
