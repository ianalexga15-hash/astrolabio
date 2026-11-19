"""Auditoría, limpieza y partición de velas diarias. Nada aquí mira el futuro ni inventa filas."""
import hashlib

import numpy as np
import pandas as pd

DIA_MS = 86_400_000
COLUMNAS = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume']
PRECIOS = ['open', 'high', 'low', 'close']


class DataError(ValueError):
    """Datos que impiden continuar. El mensaje explica qué revisar."""


def fecha(ms):
    return pd.Timestamp(int(ms), unit='ms', tz='UTC').strftime('%Y-%m-%d')


def frame_from_rows(filas):
    """Convierte las filas de /api/v3/klines en un DataFrame, sin corregir nada todavía."""
    if not filas:
        raise DataError('Conjunto vacío: la fuente no devolvió velas. Revisa símbolo, intervalo y conexión.')
    if len(filas[0]) < len(COLUMNAS):
        raise DataError(f'Fila con {len(filas[0])} columnas; se esperaban {len(COLUMNAS)}: {COLUMNAS}.')
    df = pd.DataFrame([f[:len(COLUMNAS)] for f in filas], columns=COLUMNAS)
    for col in COLUMNAS:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['date'] = pd.to_datetime(df.open_time, unit='ms', utc=True).dt.strftime('%Y-%m-%d')
    return df


def audit(df):
    """Describe los problemas de la serie sin modificarla."""
    invalidos = []
    for col in PRECIOS + ['volume']:
        malos = ~np.isfinite(df[col]) | (df[col] <= 0 if col in PRECIOS else df[col] < 0)
        invalidos += [{'columna': col, 'fecha': d, 'valor': v} for d, v in zip(df.date[malos], df[col][malos])]
    orden = df.drop_duplicates('open_time', keep='last').sort_values('open_time')
    saltos = orden.open_time.diff()
    huecos = [{'desde': a, 'hasta': b, 'dias': float(s) / DIA_MS}
              for a, b, s in zip(orden.date.shift(), orden.date, saltos) if pd.notna(s) and s >= 2 * DIA_MS]
    incoherentes = df[(df.high < df[['open', 'close']].max(axis=1)) | (df.low > df[['open', 'close']].min(axis=1))]
    return {
        'filas': len(df),
        'primera': orden.date.iloc[0],
        'ultima': orden.date.iloc[-1],
        'duplicadas': int(df.open_time.duplicated().sum()),
        'desordenadas': int((df.open_time.diff() < 0).sum()),
        'invalidos': invalidos,
        'huecos': huecos,
        'desalineadas': int((orden.open_time % DIA_MS != 0).sum()),
        'incoherentes': incoherentes.date.tolist(),
    }


def clean(df):
    """Regla documentada: quitar duplicados y filas inválidas, y conservar el tramo continuo más largo.

    No se rellena ningún día. Las velas con otro corte diario quedan fuera porque no miden lo mismo.
    Devuelve el DataFrame y la bitácora de lo que cambió.
    """
    bitacora = []
    inicial = len(df)
    salida = df.sort_values('open_time', kind='stable').drop_duplicates('open_time', keep='last')
    if len(salida) != inicial:
        bitacora.append(f'{inicial - len(salida)} duplicada(s) eliminada(s), se conserva la última versión.')
    validas = np.isfinite(salida[PRECIOS]).all(axis=1) & (salida[PRECIOS] > 0).all(axis=1) & (salida.volume >= 0)
    if (~validas).any():
        bitacora.append(f'{int((~validas).sum())} fila(s) con precio no válido retirada(s): {salida.date[~validas].tolist()}.')
    salida = salida[validas]
    alineadas = salida.open_time % DIA_MS == 0
    if (~alineadas).any():
        bitacora.append(f'{int((~alineadas).sum())} vela(s) con otro corte diario retirada(s).')
    salida = salida[alineadas]
    if salida.empty:
        raise DataError('Después de limpiar no queda ninguna vela válida. Revisa la fuente de datos.')
    tramo = (salida.open_time.diff() != DIA_MS).cumsum()
    mejor = tramo.value_counts().idxmax()
    continuo = salida[tramo == mejor].reset_index(drop=True)
    if len(continuo) != len(salida):
        bitacora.append(f'{len(salida) - len(continuo)} vela(s) fuera del tramo continuo más largo '
                        f'({continuo.date.iloc[0]} a {continuo.date.iloc[-1]}).')
    return continuo, bitacora


def add_target(df):
    """y_t = P_{t+1} / P_t - 1. La última fila queda sin objetivo observable."""
    salida = df.copy()
    salida['y'] = salida.close.shift(-1) / salida.close - 1
    return salida


def dataset_hash(df):
    contenido = df[COLUMNAS].to_csv(index=False).encode()
    return hashlib.sha256(contenido).hexdigest()


def split_indices(n, tr=0.70, va=0.15):
    """Partición cronológica por orden de la fecha objetivo. No hay división aleatoria."""
    n_tr, n_va = int(n * tr), int(n * va)
    if n_tr < 1 or n_va < 1 or n - n_tr - n_va < 1:
        raise DataError(f'Ejemplos insuficientes para TR/VA/TE: {n}.')
    return {'TR': np.arange(0, n_tr), 'VA': np.arange(n_tr, n_tr + n_va), 'TE': np.arange(n_tr + n_va, n)}
