"""Observación prospectiva, sin permisos de ejecución ni acceso a TE.

La captura es una muestra del radar, no un libro completo ni un simulador de fills.
El trabajo pesado vive en un hilo aparte del reflejo. Ninguna alerta cambia órdenes.
"""
import json
import math
import sqlite3
import threading
import time
from datetime import datetime, timezone

import numpy as np

DAY = 86_400_000


def numero(x):
    try:
        return float(x) if math.isfinite(float(x)) else None
    except (TypeError, ValueError):
        return None


def salud(experimentos):
    filas = []
    for e in experimentos:
        tr, va = numero(e.get('RMSE_TR')), numero(e.get('RMSE_VA'))
        if tr is None or va is None:
            continue
        filas.append(dict(modelo=e.get('modelo', ''), tr=tr, va=va,
                          brecha=va - tr, razon=va / tr if tr > 0 else None))
    return dict(estado='observado' if filas else 'sin_datos', filas=filas,
                aviso='Brecha TR/VA orientativa; no prueba por sí sola sobreajuste. VA ya participó en la selección. TE cerrado.')


def concentracion(series, posiciones, patrimonio, minimo=30):
    """Correlación de retornos diarios alineados por fecha, nunca por número de fila."""
    retornos = {}
    for simbolo, filas in series.items():
        validas = sorted(filas, key=lambda f: f['open_time'])
        retornos[simbolo] = {b['open_time']: b['close'] / a['close'] - 1
                            for a, b in zip(validas, validas[1:])
                            if b['open_time'] - a['open_time'] == DAY and a['close'] > 0 and b['close'] > 0}
    pares = []
    simbolos = sorted(retornos)
    for i, a in enumerate(simbolos):
        for b in simbolos[i + 1:]:
            fechas = sorted(retornos[a].keys() & retornos[b].keys())[-90:]
            if len(fechas) < minimo:
                continue
            x, y = [retornos[a][t] for t in fechas], [retornos[b][t] for t in fechas]
            if np.std(x) < 1e-12 or np.std(y) < 1e-12:
                continue
            r = float(np.corrcoef(x, y)[0, 1])
            pares.append(dict(a=a, b=b, correlacion=r, n=len(fechas)))
    pesos = {s: v / patrimonio for s, v in posiciones.items() if patrimonio > 0 and v > 0}
    return dict(pares=sorted(pares, key=lambda p: -p['correlacion'])[:40], pesos=pesos,
                exposicion=sum(pesos.values()), hhi=sum(v*v for v in pesos.values()),
                aviso='Correlaciones descriptivas de hasta 90 retornos diarios. No son límites de compra ni garantías de diversificación.')


def deterioro(evaluadas):
    """Comparar bloques no solapados; alerta descriptiva fijada antes de observar."""
    grupos = {}
    for f in evaluadas:
        if f['real'] is not None:
            grupos.setdefault((f['simbolo'], f['version']), []).append(f)
    salida = []
    for (s, v), filas in grupos.items():
        filas.sort(key=lambda f: f['objetivo'])
        if len(filas) < 60:
            salida.append(dict(simbolo=s, version=v, estado='evidencia_insuficiente', n=len(filas)))
            continue
        errores = [abs(f['prediccion'] - f['real']) for f in filas[-60:]]
        base, reciente = float(np.mean(errores[:30])), float(np.mean(errores[30:]))
        alerta = reciente > max(1e-6, 1.5 * base)
        salida.append(dict(simbolo=s, version=v, estado='revisar' if alerta else 'sin_alerta', n=len(filas),
                           mae_base=base, mae_reciente=reciente))
    return salida


class Observatorio:
    def __init__(self, ctx):
        self.ctx = ctx
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(ctx.aj.db) + '.observatorio.sqlite3', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS capturas(id INTEGER PRIMARY KEY, ts REAL NOT NULL, datos TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sombra(simbolo TEXT, version TEXT, origen INTEGER, objetivo INTEGER,
            emitido REAL, precio REAL, prediccion REAL, candidato REAL, candidato_version TEXT, real REAL,
            PRIMARY KEY(simbolo,version,origen));
        ''')
        self.ultimo = 0
        self.ultimo_ciclo = None
        self.estado = 'esperando'
        self.error = None
        self.concentracion = dict(pares=[], pesos={}, exposicion=0, hhi=0)
        self.candidato = None
        self.candidato_error = None
        # Candidato opcional, cargado una sola vez; nunca reemplaza ACTIVO/CARTERA.
        ruta = ctx.aj.raiz / 'models' / 'SOMBRA.txt'
        if ruta.exists():
            from bot.model import cargar
            destino = (ctx.aj.raiz / 'models' / ruta.read_text(encoding='utf-8').strip()).resolve()
            if destino.is_relative_to((ctx.aj.raiz / 'models').resolve()):
                try:
                    self.candidato = cargar(destino)
                except Exception:
                    self.candidato_error = 'No se pudo cargar el candidato local.'
            else:
                self.candidato_error = 'El candidato debe estar dentro de models/.'

    def ciclo(self):
        c = self.ctx.cartera
        if c is None:
            self.estado = 'sin_modelo'
            return
        ahora = self.ctx.ahora()
        radar = {s: dict(f) for s, f in list(c.reflejo.radar.items())}
        # Solo campos numéricos/estados públicos: nunca contexto de autenticación o LLM.
        campos = ('bid', 'ask', 'spread_bps', 'estado', 'cantidad', 'valor', 'resultado_abierto',
                  'pronostico', 'bot', 'condiciones', 'cumplidas', 'stop', 'objetivo', 'entrada')
        filas = {s: {k: f[k] for k in campos if k in f} for s, f in radar.items()}
        captura = dict(radar=filas, ultimo_libro_ms=c.ultimo_libro_ms,
                       posiciones=c.resumen()['posiciones'], medicion=c.medicion())
        with self.lock:
            if c.ultimo_libro_ms is not None and c.ultimo_libro_ms != self.ultimo_ciclo:
                self.db.execute('INSERT INTO capturas(ts,datos) VALUES(?,?)', (ahora, json.dumps(captura, allow_nan=False)))
                self.ultimo_ciclo = c.ultimo_libro_ms
                # Retención acotada: 86 400 capturas, hasta un día si la frecuencia es 1 Hz.
                self.db.execute('DELETE FROM capturas WHERE id <= (SELECT MAX(id)-86400 FROM capturas)')
                self.db.commit()
        self.estado = 'observando'
        if ahora - self.ultimo < 60_000:
            return
        self.ultimo = ahora
        series = {s: [f for f in self.ctx.store.velas(s, 120) if f['close_time'] < ahora] for s in c.agentes}
        posiciones = {s: a.cuenta.cantidad * (radar.get(s, {}).get('bid') or a.cuenta.precio_medio)
                      for s, a in c.agentes.items()}
        mapa = concentracion(series, posiciones, c.resumen()['patrimonio'])
        with self.lock:
            self.concentracion = mapa
        self._sombra(series, ahora)

    def _sombra(self, series, ahora):
        from bot.features import add_indicators
        import pandas as pd
        for s, filas in series.items():
            if not filas:
                continue
            por_fecha = {f['open_time']: f for f in filas}
            with self.lock:
                pendientes = self.db.execute('SELECT * FROM sombra WHERE simbolo=? AND real IS NULL', (s,)).fetchall()
                for f in pendientes:
                    vela = por_fecha.get(f['objetivo'])
                    if vela and vela['close_time'] < ahora and f['emitido'] < vela['close_time']:
                        self.db.execute('UPDATE sombra SET real=? WHERE simbolo=? AND version=? AND origen=?',
                                        (vela['close'] / f['precio'] - 1, s, f['version'], f['origen']))
                self.db.commit()
            ultima = filas[-1]
            # Solo predicciones prospectivas cercanas al cierre; jamás rellenar pasado.
            if not 0 < ahora - ultima['close_time'] <= 900_000:
                continue
            modelo = self.ctx.modelos.get(s)
            if modelo is None:
                continue
            with self.lock:
                existe = self.db.execute('SELECT 1 FROM sombra WHERE simbolo=? AND version=? AND origen=?',
                                         (s, modelo.version, ultima['open_time'])).fetchone()
            if existe:
                continue
            tabla = add_indicators(pd.DataFrame(filas))
            try:
                pred = numero(modelo.pronosticar(tabla))
                candidato = numero(self.candidato.pronosticar(tabla)) if self.candidato else 0.0
                if pred is None or candidato is None:
                    continue
            except Exception:
                self.candidato_error = 'Inferencia de sombra no disponible para algún activo; no se registró esa pareja.'
                continue
            with self.lock:
                self.db.execute('INSERT OR IGNORE INTO sombra VALUES(?,?,?,?,?,?,?,?,?,NULL)',
                                (s, modelo.version, ultima['open_time'], ultima['open_time'] + DAY,
                                 ahora, ultima['close'], pred, candidato,
                                 self.candidato.version if self.candidato else 'baseline-cero'))
                self.db.commit()

    def bucle(self):
        while not self.ctx.parar.wait(1):
            try:
                self.ciclo()
                self.error = None
            except Exception:
                self.estado = 'error'
                self.error = 'Falló la observación; el ejecutor continúa independiente.'

    def resumen(self):
        with self.lock:
            filas = [dict(f) for f in self.db.execute('SELECT * FROM sombra ORDER BY objetivo')]
            captura = dict(self.db.execute('SELECT COUNT(*) n, MIN(ts) desde, MAX(ts) hasta FROM capturas').fetchone())
            mapa = self.concentracion
        grupos = {}
        for f in filas:
            if f['real'] is not None:
                grupos.setdefault((f['simbolo'], f['version'], f['candidato_version']), []).append(f)
        comparacion = []
        for (s, v, cv), fs in grupos.items():
            comparacion.append(dict(simbolo=s, version=v, candidato=cv, n=len(fs),
                rmse=float(np.sqrt(np.mean([(f['prediccion']-f['real'])**2 for f in fs]))),
                rmse_sombra=float(np.sqrt(np.mean([(f['candidato']-f['real'])**2 for f in fs])))))
        c = self.ctx.cartera
        edad = (self.ctx.ahora() - c.ultimo_libro_ms) / 1000 if c and c.ultimo_libro_ms else None
        return dict(estado=self.estado, error=self.error, captura=captura, concentracion=mapa,
                    sombra=dict(comparacion=comparacion, pendientes=sum(f['real'] is None for f in filas),
                                candidato=self.candidato.version if self.candidato else 'baseline-cero', error=self.candidato_error),
                    deterioro=deterioro(filas), datos=dict(edad_s=edad, alerta=edad is None or edad > 5),
                    politica='Observación: no altera órdenes, no promueve modelos y no abre TE.')

    def reproducir(self, despues=0, limite=100):
        with self.lock:
            filas = self.db.execute('SELECT * FROM capturas WHERE id>? ORDER BY id LIMIT ?', (despues, limite)).fetchall()
        return [dict(id=f['id'], ts=f['ts'], **json.loads(f['datos'])) for f in filas]


def fichas(store, limite=40):
    decisiones = store.grupo('decisiones', 'live', limite)
    ordenes = store.grupo('ordenes', 'live', 3000)
    salida = []
    for d in reversed(decisiones):
        campos = ('id', 'run', 'creado', 'modelo_version', 'pronostico', 'umbral', 'filtro', 'senal', 'aprobada', 'accion_propuesta', 'accion_final', 'motivos')
        ficha = {k: d.get(k) for k in campos}
        ficha['ordenes'] = [{k: o.get(k) for k in ('id','creado','lado','cantidad','precio','comision','estado','motivo','modelo_costos')}
                            for o in ordenes if o['decision_id'] == d['id']]
        salida.append(ficha)
    # Las órdenes del reflejo pueden no tener decision_id: no inventar su asociación.
    huerfanas = [{k:o.get(k) for k in ('id','run','creado','lado','cantidad','precio','comision','estado','motivo','modelo_costos')}
                for o in ordenes if o['decision_id'] is None][-40:]
    return dict(decisiones=salida, ordenes_sin_enlace=huerfanas)
