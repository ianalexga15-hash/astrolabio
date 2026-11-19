"""Inferencia del modelo aprobado con NumPy. El agente no necesita Keras, GPU ni servicios externos."""
import json
import math
import zipfile
from pathlib import Path

import numpy as np

from bot.data import DataError
from bot.features import Scaler, latest_window

TIPOS = ('cero', 'lineal', 'mlp', 'lstm')
FILTROS = ('ninguno', 'sma20')  # los mismos que evalúa research/lab.py
ACTIVACIONES = {'linear': lambda x: x, 'relu': lambda x: np.maximum(x, 0), 'tanh': np.tanh,
                'sigmoid': lambda x: 1 / (1 + np.exp(-x))}


def _sigmoide(x):
    return 1 / (1 + np.exp(-np.clip(x, -500, 500)))


def _lstm(x, w, wr, b):
    """Celda LSTM con las mismas ecuaciones que Keras. Pesos en orden: entrada, olvido, celda, salida."""
    n, pasos, _ = x.shape
    unidades = wr.shape[0]
    h, c = np.zeros((n, unidades)), np.zeros((n, unidades))
    for t in range(pasos):
        z = x[:, t, :] @ w + h @ wr + b
        zi, zf, zc, zo = np.split(z, 4, axis=1)
        i, f, o = _sigmoide(zi), _sigmoide(zf), _sigmoide(zo)
        c = f * c + i * np.tanh(zc)
        h = o * np.tanh(c)
    return h


def adelante(miembro, pesos, indice, x):
    """Propagación hacia adelante de un miembro. x: (ejemplos, pasos, variables)."""
    salida = x
    for j, capa in enumerate(miembro):
        prefijo = f'm{indice}_c{j}_'
        if capa['tipo'] == 'lstm':
            salida = _lstm(salida, pesos[prefijo + 'w'], pesos[prefijo + 'wr'], pesos[prefijo + 'b'])
        else:
            if salida.ndim == 3:
                salida = salida.reshape(len(salida), -1)
            salida = ACTIVACIONES[capa['activacion']](salida @ pesos[prefijo + 'w'] + pesos[prefijo + 'b'])
    return salida.ravel()


def exportar_keras(red, indice):
    """Convierte una red Keras en lista de capas y pesos NumPy. Dropout no actúa al predecir."""
    miembro, pesos = [], {}
    for capa in red.layers:
        nombre = type(capa).__name__
        if nombre in ('Dropout', 'InputLayer'):
            continue
        j = len(miembro)
        prefijo = f'm{indice}_c{j}_'
        if nombre == 'LSTM':
            w, wr, b = capa.get_weights()
            pesos |= {prefijo + 'w': w, prefijo + 'wr': wr, prefijo + 'b': b}
            miembro.append({'tipo': 'lstm'})
        elif nombre == 'Dense':
            w, b = capa.get_weights()
            pesos |= {prefijo + 'w': w, prefijo + 'b': b}
            miembro.append({'tipo': 'dense', 'activacion': capa.get_config()['activation']})
        else:
            raise DataError(f'Capa {nombre} sin exportación a NumPy.')
    return miembro, pesos


def filtro_efectivo(filtro, minimo=''):
    """El filtro de la regla de VA; si no trae ninguno, el mínimo de config/riesgo.json ('' la deja sin filtro)."""
    return (minimo or filtro) if filtro in (None, 'ninguno') else filtro


class Modelo:
    def __init__(self, contrato, pesos):
        self.contrato, self.pesos = contrato, pesos
        self.version = contrato['version']
        self.tipo = contrato['tipo']
        self.lookback = contrato['lookback']
        self.variables = contrato['variables']
        self.umbral = contrato['umbral']
        self.filtro = contrato['filtro']
        self.escalador = Scaler.from_dict(contrato['escalador'])

    def predecir_x(self, x):
        """Pronóstico en la escala original del rendimiento."""
        if self.tipo == 'cero':
            return np.zeros(len(x))
        escalado = self.escalador.transform(x)
        salidas = [adelante(m, self.pesos, i, escalado) for i, m in enumerate(self.contrato['miembros'])]
        return self.contrato['y_media'] + self.contrato['y_desv'] * np.mean(salidas, axis=0)

    def pronosticar(self, tabla):
        if self.tipo == 'cero':
            return 0.0
        x, _ = latest_window(tabla, self.variables, self.lookback)
        return float(self.predecir_x(x)[0])

    def senal(self, pronostico, tabla, filtro_minimo=''):
        """Regla elegida en VA: comprar si el pronóstico supera el umbral y el filtro técnico lo confirma.
        Si la regla no trae filtro, se usa `filtro_minimo` (decisión de Alex, 2026-11-13: ningún activo compra sin filtro)."""
        if not np.isfinite(pronostico):
            raise DataError('Pronóstico no finito: no se puede convertir en señal de trading.')
        ultima = tabla.iloc[-1]
        filtro = filtro_efectivo(self.filtro, filtro_minimo)
        cumple_umbral = bool(pronostico > self.umbral)
        cumple_filtro = True
        if filtro == 'sma20':
            cumple_filtro = bool(ultima.close > ultima.sma20)
        return cumple_umbral and cumple_filtro, dict(umbral=self.umbral, filtro=filtro, cumple_umbral=cumple_umbral,
                                                     cumple_filtro=cumple_filtro)


class ModeloInvalido:
    """Lo que recibe el agente cuyo modelo no pasó la revisión al cargar: queda en pausa y nunca pronostica."""

    def __init__(self, error):
        self.error = error


def _finito(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _revisar(contrato, pesos, version):
    """Integridad antes de operar: versión, contrato, escalador y pesos coherentes y finitos. Devuelve el problema o None."""
    if not isinstance(contrato.get('version'), str) or (version is not None and contrato['version'] != version):
        return f'la versión del contrato ({contrato.get("version")}) no coincide con la indicada ({version})'
    variables, lookback = contrato.get('variables'), contrato.get('lookback')
    if not (isinstance(variables, list) and variables and all(isinstance(v, str) for v in variables)):
        return 'la lista de variables está vacía o no es válida'
    if not (isinstance(lookback, int) and not isinstance(lookback, bool) and lookback >= 1):
        return f'la ventana (lookback) no es un entero positivo: {lookback}'
    if contrato.get('filtro') not in FILTROS:
        return f'filtro desconocido: {contrato.get("filtro")}'
    for clave in ('umbral', 'y_media', 'y_desv'):
        if not _finito(contrato.get(clave)):
            return f'{clave} no es un número finito: {contrato.get(clave)}'
    if contrato['y_desv'] <= 0:
        return 'y_desv debe ser positivo'
    escalador = contrato.get('escalador') if isinstance(contrato.get('escalador'), dict) else {}
    try:
        media, desv = np.asarray(escalador.get('media'), dtype=float), np.asarray(escalador.get('desv'), dtype=float)
    except (TypeError, ValueError):
        return 'el escalador no es numérico'
    if media.shape != (len(variables),) or desv.shape != media.shape:
        return f'el escalador no trae un valor por variable ({len(variables)})'
    if not (np.isfinite(media).all() and np.isfinite(desv).all() and (desv > 0).all()):
        return 'el escalador tiene valores no finitos o desviaciones no positivas'
    for k, w in pesos.items():
        if not (np.issubdtype(w.dtype, np.number) and np.isfinite(w).all()):
            return f'el peso {k} tiene valores no finitos o no numéricos'
    if contrato['tipo'] == 'cero':
        return None
    if not contrato.get('miembros'):
        return 'el contrato no declara miembros'
    try:  # prueba de humo: toda la red debe dar un número finito con una ventana neutra
        salida = Modelo(contrato, pesos).predecir_x(np.zeros((1, lookback, len(variables))))
    except (KeyError, ValueError, IndexError, TypeError) as e:
        return f'los pesos no encajan con el contrato ({type(e).__name__}: {e})'
    if salida.shape != (1,) or not np.isfinite(salida).all():
        return 'la red no produce un pronóstico finito'
    return None


def cargar(carpeta, version=None):
    """Carga y revisa el modelo. Con `version` (el nombre de ACTIVO.txt o CARTERA.txt), el contrato debe declarar esa misma versión."""
    carpeta = Path(carpeta)
    ruta = carpeta / 'contrato.json'
    if not ruta.exists():
        raise DataError(f'No existe {ruta}: copia ahí el modelo aprobado o genera uno con research/entrenar_cpu.py.')
    try:
        contrato = json.loads(ruta.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise DataError(f'Modelo {carpeta.name} inválido: contrato.json no se puede leer ({type(e).__name__}).') from e
    if not isinstance(contrato, dict):
        raise DataError(f'Modelo {carpeta.name} inválido: contrato.json no es un objeto.')
    if contrato.get('tipo') not in TIPOS:
        raise DataError(f'Tipo de modelo no soportado: {contrato.get("tipo")}. Permitidos: {TIPOS}.')
    pesos = {}
    if contrato['tipo'] != 'cero':
        npz = carpeta / 'modelo.npz'
        if not npz.exists():
            raise DataError(f'Falta {npz}: el contrato pide pesos y no están en la carpeta.')
        try:
            with np.load(npz) as d:
                pesos = {k: d[k] for k in d.files}
        except (OSError, ValueError, EOFError, zipfile.BadZipFile) as e:
            raise DataError(f'Modelo {carpeta.name} inválido: modelo.npz no se puede leer ({type(e).__name__}).') from e
    problema = _revisar(contrato, pesos, version)
    if problema:
        raise DataError(f'Modelo {carpeta.name} inválido: {problema}. No opera hasta reemplazarlo y reiniciar el bot.')
    return Modelo(contrato, pesos)
