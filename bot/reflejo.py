"""Reflejo: cada segundo revisa las condiciones de compra y venta de cada activo y ejecuta en Paper.

Es determinista y no consulta al LLM. El cerebro (modelo y Ollama) decide una vez al día qué activos quedan autorizados.
"""
import math
import time
from collections import deque

import numpy as np

from bot import mexc, model, paper, risk
from bot.events import NULO
from bot.paper import Cuenta, OrdenRechazada

PERSISTIR_STOP = 0.001  # el stop móvil se guarda al moverse 0.1 %: no hace falta escribir en disco cada segundo
MAX_LIBROS_POR_BARRIDO = 3  # cada libro es una consulta de unos 230 ms: con 3 el barrido queda bajo el segundo
ESPERA_LIBRO_MS = 5_000  # si el libro no alcanza, se vuelve a pedir a los 5 s: cuarenta activos no deben ser cuarenta consultas por segundo


class Reflejo:
    def __init__(self, agentes, eventos=NULO):
        self.agentes = agentes
        self.eventos = eventos
        self.radar = {}
        self.bloqueo_entradas = None
        self.barridos = 0
        self.latencias = deque(maxlen=3600)
        self.ultimo_barrido_ms = None
        self._stop_guardado = {}
        self._libro_espera = {}
        self._libros_en_barrido = 0

    def barrer(self, libro, ahora_ms):
        inicio = time.perf_counter()
        self._libros_en_barrido = 0
        for simbolo, agente in self.agentes.items():
            self.radar[simbolo] = self._revisar(agente, libro.get(simbolo), ahora_ms)
        self.latencias.append((time.perf_counter() - inicio) * 1000)
        self.barridos += 1
        self.ultimo_barrido_ms = ahora_ms
        return self.estadisticas()

    def estadisticas(self):
        datos = np.array(self.latencias) if self.latencias else np.zeros(1)
        return dict(barridos=self.barridos, activos=len(self.agentes), latencia_ms=float(datos[-1]), p99_ms=float(np.percentile(datos, 99)), ultimo_barrido_ms=self.ultimo_barrido_ms)

    def _revisar(self, a, precio, ahora_ms):
        lim = a.limites
        with a._lock:
            c = a.cuenta
            fila = dict(simbolo=lim.simbolo, pronostico=a.pronostico, fecha_vela=a.fecha_ultima, bot=a.estado, motivo=a.motivo, cantidad=c.cantidad, entrada=c.precio_medio or None, stop=c.stop,
                        objetivo=c.objetivo, efectivo=c.efectivo, bid=None, ask=None, spread_bps=None, condiciones=[], cumplidas=0, resultado_abierto=None, valor=c.efectivo)
            if c.armada and ahora_ms > c.armada['expira_ms']:
                previa = self.radar.get(lim.simbolo) or {}  # evidencia para validar las reglas en vivo: qué faltó ese día
                faltaba = '; '.join(f"{x['nombre']}: {x['detalle']}" for x in previa.get('condiciones', []) if not x['cumple'])
                with a.store.transaccion():
                    a.store.guardar_orden(a.run_id, None, c.armada['vela'], 'comprar', 'expirada', faltaba or 'No hubo precio en vivo que revisar.')
                    self._guardar(a, Cuenta(**{**c.__dict__, 'armada': None}))
                c = a.cuenta
            if precio is None or ahora_ms - precio['ts_ms'] > lim.edad_precio_max_s * 1000:
                return fila | dict(estado='dato_atrasado', valor=c.efectivo + c.cantidad * (c.precio_medio or 0))

            bid, ask = precio['bid'], precio['ask']
            medio = (bid + ask) / 2
            fila |= dict(bid=bid, ask=ask, spread_bps=(ask - bid) / ask * 10_000, valor=paper.patrimonio(c, bid))
            if c.cantidad > 0:
                return self._vigilar_posicion(a, c, bid, fila)
            if not c.armada:
                return fila | dict(estado=a.estado if a.estado != 'activo' else 'sin_senal') | self._informativas(a, bid, ask)
            return self._revisar_entrada(a, c, bid, ask, medio, ahora_ms, fila)

    @staticmethod
    def _condiciones_precio(lim, ref, bid, ask):
        """Filtro técnico, spread y sin perseguir con el precio en vivo. `ref` es la compra armada o la última vela decidida."""
        spread = (ask - bid) / ask * 10_000
        extension = (ask - ref['cierre']) / ref['atr_abs'] if ref['atr_abs'] else float('inf')
        sma20 = model.filtro_efectivo(ref.get('filtro'), lim.filtro_minimo) == 'sma20'  # también con una compra o decisión de antes del filtro mínimo
        return [
            dict(id='filtro', nombre='Filtro técnico', cumple=not sma20 or ask > ref['sma20'],
                 detalle=f'Precio {ask:g} contra SMA20 {ref["sma20"]:g} ({ask / ref["sma20"] - 1:+.2%})' if sma20 else 'Sin filtro'),
            dict(id='spread', nombre='Spread y libro', cumple=spread <= lim.spread_max_bps, detalle=f'{spread:.1f} de {lim.spread_max_bps:g} puntos base'),
            dict(id='extension', nombre='Sin perseguir', cumple=extension <= lim.extension_max_atr, detalle=f'{extension:+.2f} ATR desde el cierre; máximo {lim.extension_max_atr:g}'),
        ]

    def _informativas(self, a, bid, ask):
        """Sin compra armada: las mismas condiciones con la última vela decidida, solo para ver qué tan cerca está. No arman ni compran."""
        v = a.contexto_vela
        if v is None:
            return {}
        condiciones = [dict(id='senal', nombre='Señal del día', cumple=v['senal'], detalle=f'Pronóstico {v["pronostico"]:+.3%} contra el umbral {v["umbral"]:+.3%}'),
                       *self._condiciones_precio(a.limites, v, bid, ask)]
        m = v['maquina']
        if m is not None:  # el repaso solo se corre cuando hay señal y la propuesta es comprar
            condiciones.append(dict(id='maquina', nombre='Máquina del tiempo', cumple=m['r_medio'] > 0,
                                    detalle=f'Llega primero al objetivo {m["objetivo"]:.0%} de las veces y al stop {m["stop"]:.0%}; en promedio deja {m["r_medio"]:+.2f} R'
                                    if math.isfinite(m['r_medio']) else 'Sin un repaso válido: falta historia o el resultado no es un número'))
        motivo = ' '.join(v['motivos']) or f'la propuesta fue «{v["propuesta"]}».'
        razon = 'autorizó una compra que ya se usó o venció; decide otra vez al cerrar la próxima vela.' if v['accion'] == 'comprar' else f'no la armó: {motivo}'
        condiciones.append(dict(id='autorizacion', nombre='Autorización del ciclo diario', cumple=False, detalle=f'El ciclo diario de la vela {v["fecha"]} {razon}'))
        return dict(condiciones=condiciones, cumplidas=sum(x['cumple'] for x in condiciones))

    def _vigilar_posicion(self, a, c, bid, fila):
        """Salidas: stop, objetivo y stop móvil. En pausa por fallo y en bloqueo siguen protegiendo; detenido no envía órdenes."""
        lim = a.limites
        if a.estado == 'detenido' or (a.estado == 'pausado' and not a.por_fallo):
            return fila | dict(estado='en_posicion', resultado_abierto=bid / c.precio_medio - 1)
        nueva = Cuenta(**c.__dict__)
        motivo = 'stop' if c.stop is not None and bid <= c.stop else 'objetivo' if c.objetivo is not None and bid >= c.objetivo else None
        if motivo == 'objetivo' and lim.espera_max_min > 0:  # la venta ya esperaba en el libro al precio objetivo: sin comisión ni deslizamiento
            precio_salida, costos, comision, desliz = c.objetivo, 'orden en espera al precio objetivo', lim.comision_espera, 0.0
        else:
            precio_salida, costos = self._precio_salida(a, c.cantidad, bid) if motivo else (bid, '')  # el libro solo se lee para vender de verdad
            comision, desliz = lim.comision_efectiva, lim.deslizamiento_bps
        e = paper.vender(nueva, precio_salida, a._filtros(), comision, desliz, motivo) if motivo else None
        if e:
            with a.store.transaccion():
                a.store.guardar_orden(a.run_id, None, None, e.lado, 'ejecutada', e.motivo, e.cantidad, e.precio, e.comision, e.resultado,
                                      modelo_costos=f'{costos} + {desliz:g} pb, comisión {comision:.2%}')
                a.store.guardar_cuenta(a.run_id, nueva)
            a.cuenta = nueva
            self._stop_guardado.pop(a.run_id, None)
            self.eventos.emitir('reflejo', 'ejecutar', tipo='ordenes', detalle=f'{lim.simbolo} vende por {e.motivo}')
            self.eventos.emitir('ejecutar', 'cuenta', tipo='ordenes', detalle=f'{lim.simbolo} {e.cantidad}')
            return fila | dict(estado='sin_senal', cantidad=0.0, stop=None, objetivo=None, entrada=None, efectivo=nueva.efectivo, valor=nueva.efectivo)
        if c.atr_abs:
            paper.mover_trailing(nueva, bid, c.atr_abs, lim.trailing_atr, lim.proteger_atr, 2 * lim.comision_efectiva + lim.deslizamiento_bps / 10_000)
            base = self._stop_guardado.get(a.run_id, c.stop)
            if nueva.stop != c.stop:
                a.cuenta = nueva
                if nueva.stop >= (base or 0) * (1 + PERSISTIR_STOP):
                    a.store.guardar_cuenta(a.run_id, nueva)
                    self._stop_guardado[a.run_id] = nueva.stop
        return fila | dict(estado='en_posicion', resultado_abierto=bid / c.precio_medio - 1, stop=a.cuenta.stop)

    def _revisar_entrada(self, a, c, bid, ask, medio, ahora_ms, fila):
        lim, arm = a.limites, c.armada
        valor = paper.patrimonio(c, medio)
        ctx = risk.Contexto(estado=a.estado, simbolo=lim.simbolo, edad_horas=(ahora_ms - arm['expira_ms']) / 3_600_000 + 24, senal=True, cuenta=c, precio=ask, atr_abs=arm['atr_abs'],
                            patrimonio=valor, patrimonio_inicio_dia=a.store.ultimo_patrimonio(a.run_id) or lim.capital_inicial,
                            patrimonio_maximo=max(a.store.patrimonio_maximo(a.run_id) or lim.capital_inicial, valor))
        d = risk.evaluar('comprar', ctx, lim)
        motivo_riesgo = self.bloqueo_entradas or ' '.join(d.motivos)
        condiciones = [
            dict(id='senal', nombre='Señal del día', cumple=True, detalle=f'Pronóstico {arm["pronostico"]:+.3%}, propuesta aprobada'),
            *self._condiciones_precio(lim, arm, bid, ask),
            dict(id='riesgo', nombre='Riesgo', cumple=d.aprobada and not self.bloqueo_entradas, detalle=motivo_riesgo or 'Límites dentro de rango'),
        ]
        fila |= dict(estado='armada', condiciones=condiciones, cumplidas=sum(x['cumple'] for x in condiciones))
        limite = arm.get('limite')
        if fila['cumplidas'] < len(condiciones):
            if limite is not None:  # se cancela; vuelve a ponerse cuando todo se cumpla otra vez
                self._guardar(a, Cuenta(**{**c.__dict__, 'armada': {**arm, 'limite': None}}))
            return fila
        if limite is not None and ask <= limite:  # todos los criterios siguen vigentes al simular el llenado
            return self._comprar(a, c, limite, d, ahora_ms, fila, en_espera=True)
        if lim.espera_max_min > 0:
            hasta = arm.get('espera_hasta_ms') or ahora_ms + lim.espera_max_min * 60_000  # el plazo cuenta desde la primera vez
            if ahora_ms < hasta:
                if limite is None:
                    limite = bid
                    self._guardar(a, Cuenta(**{**c.__dict__, 'armada': {**arm, 'limite': bid, 'espera_hasta_ms': hasta}}))
                return fila | dict(espera=dict(precio=limite, hasta_ms=hasta))
        precio, problema = self._precio_entrada(a, ask, d.monto_quote, ahora_ms)
        if problema:  # el libro se revisa solo cuando todo lo demás se cumple: una consulta más, no cuarenta por segundo
            condiciones[2] |= dict(cumple=False, detalle=f'{condiciones[2]["detalle"]}; {problema}')
            fila['cumplidas'] -= 1
            return fila
        return self._comprar(a, c, precio, d, ahora_ms, fila)

    def _precio_entrada(self, a, ask, monto, ahora_ms):
        """Precio medio de la orden completa en el libro visible y el problema que impide comprar, si lo hay."""
        espera = self._libro_espera.get(a.run_id)
        if espera and ahora_ms < espera[0]:
            return ask, f'{espera[1]} (libro leído hace {(ahora_ms - espera[2]) / 1000:.0f} s)'
        if getattr(a.mercado, 'profundidad', None) is not None:
            if self._libros_en_barrido >= MAX_LIBROS_POR_BARRIDO:
                return ask, 'el libro se revisa en el siguiente barrido'  # las ventas de protección no esperan turno
            self._libros_en_barrido += 1
        precio, problema = self._mirar_libro(a, ask, monto)
        if problema:
            self._libro_espera[a.run_id] = (ahora_ms + ESPERA_LIBRO_MS, problema, ahora_ms)
        else:
            self._libro_espera.pop(a.run_id, None)
        return precio, problema

    def _mirar_libro(self, a, ask, monto):
        profundidad = getattr(a.mercado, 'profundidad', None)
        if profundidad is None:  # fuente sin libro, como en algunas pruebas: queda el mejor precio de venta
            return ask, None
        try:
            libro = profundidad(a.limites.simbolo)
        except mexc.MexcError:
            return ask, 'no se pudo leer el libro de órdenes'
        precio, cubierto = paper.precio_por_libro(libro['asks'], monto_quote=monto)
        if not cubierto:
            return ask, f'el libro visible no cubre {monto:.2f} USDT'
        impacto = (precio / ask - 1) * 10_000
        if impacto > a.limites.spread_max_bps:
            return ask, f'recorrer el libro cuesta {impacto:.1f} pb y el máximo es {a.limites.spread_max_bps:g}'
        return precio, None

    def _precio_salida(self, a, cantidad, bid):
        """Precio medio de las compras del libro para vender la posición. Si falla, el mejor precio: salir importa más que el precio exacto."""
        profundidad = getattr(a.mercado, 'profundidad', None)
        if profundidad is None:
            return bid, 'mejor compra'
        try:
            precio, _ = paper.precio_por_libro(profundidad(a.limites.simbolo)['bids'], cantidad=cantidad)
        except mexc.MexcError:
            return bid, 'mejor compra, sin libro'
        return (min(precio, bid), 'precio medio de las compras del libro') if precio else (bid, 'mejor compra, libro vacío')

    def _comprar(self, a, c, ask, d, ahora_ms, fila, en_espera=False):
        lim = a.limites
        comision, desliz = (lim.comision_espera, 0.0) if en_espera else (lim.comision_efectiva, lim.deslizamiento_bps)
        nueva = Cuenta(**c.__dict__)
        arm = c.armada
        nueva.armada = None
        try:
            e = paper.comprar(nueva, ask, d.monto_quote, a._filtros(), comision, desliz, 'senal')
        except OrdenRechazada as error:  # una sola vez: sin decisión nueva no se reintenta cada segundo
            with a.store.transaccion():
                a.store.guardar_orden(a.run_id, None, arm['vela'], 'comprar', 'rechazada', str(error))
                a.store.guardar_cuenta(a.run_id, nueva)
            a.cuenta = nueva
            return fila | dict(estado='sin_senal')
        nueva.stop, nueva.objetivo, nueva.atr_abs, nueva.entrada_ms = d.stop, d.objetivo, arm['atr_abs'], ahora_ms
        with a.store.transaccion():
            costos = ('orden en espera al precio límite' if en_espera else 'precio medio de las ventas del libro' if getattr(a.mercado, 'profundidad', None) is not None
                      else 'mejor venta')
            a.store.guardar_orden(a.run_id, None, arm['vela'], e.lado, 'ejecutada', 'senal', e.cantidad, e.precio, e.comision,
                                  modelo_costos=f'{costos} + {desliz:g} pb, comisión {comision:.2%}')
            a.store.guardar_cuenta(a.run_id, nueva)
        a.cuenta = nueva
        self.eventos.emitir('reflejo', 'ejecutar', tipo='ordenes', detalle=f'{lim.simbolo} compra {e.cantidad}')
        self.eventos.emitir('ejecutar', 'cuenta', tipo='ordenes', detalle=f'{lim.simbolo} {e.cantidad}')
        return fila | dict(estado='en_posicion', cantidad=nueva.cantidad, entrada=e.precio, stop=nueva.stop, objetivo=nueva.objetivo, efectivo=nueva.efectivo, resultado_abierto=0.0)

    def _guardar(self, a, cuenta):
        a.store.guardar_cuenta(a.run_id, cuenta)
        a.cuenta = cuenta
