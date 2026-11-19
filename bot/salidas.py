"""Salidas Paper prioritarias: aislamiento por activo y profundidad verificable."""
import math
import time
from concurrent.futures import ThreadPoolExecutor, wait

import httpx

from bot import mexc, paper
from bot.reflejo import Reflejo


def precio_salida(a, cantidad, bid, limite=None):
    """Precio de vender `cantidad` del agente `a` recorriendo el libro visible, sin pasar de `bid`. Sin profundidad completa no hay cierre."""
    if isinstance(a.mercado,mexc.Mexc):
        # Timeout por fase de red, sin reintentos internos ni espera exponencial.
        try:
            r=a.mercado.http.get(mexc.BASE+'/api/v3/depth',params={'symbol':a.limites.simbolo,'limit':50},timeout=1.5)
            r.raise_for_status()
            niveles=mexc._niveles(r.json()['bids'])
        except (httpx.HTTPError,ValueError,KeyError,TypeError) as e:
            raise paper.OrdenRechazada('Libro de salida no disponible.') from e
    elif hasattr(a.mercado,'profundidad'):
        niveles=a.mercado.profundidad(a.limites.simbolo)['bids']
    else:
        raise paper.OrdenRechazada('Sin profundidad: no se puede confirmar un cierre completo.')
    if limite is not None:
        niveles = [(p,q) for p,q in niveles if p >= limite]
    precio,cubierto=paper.precio_por_libro(niveles,cantidad=cantidad)
    if not cubierto or precio is None:
        raise paper.OrdenRechazada('Profundidad visible insuficiente; posición pendiente.')
    return min(precio,bid),'profundidad completa observada (Paper, no fill real)'


class ReflejoProtegido(Reflejo):
    def __init__(self, agentes, eventos):
        super().__init__(agentes, eventos)
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='salidas-paper')
        self.trabajos = {}
        self.salidas = {}
        self._rotacion = 0
        self._cotizacion = {}
        for s, a in agentes.items():
            # La salida pendiente vive en el agente: así la venta diaria rechazada también se entrega al reflejo.
            f = a.store._una('SELECT * FROM salidas_pendientes WHERE run=?', a.run_id)
            if f and a.cuenta.cantidad > 0 and f['entrada'] == a.cuenta.entrada_ms:
                a.salida_pendiente = f

    def cerrar(self):
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _limpiar(self, s, a):
        a.salida_pendiente = None
        a.store._ejecutar('DELETE FROM salidas_pendientes WHERE run=?', a.run_id)

    def _seguro(self, s, a, precio, ahora, inicio):
        # Un LLM/ciclo diario que mantiene el lock no debe detener los demás activos.
        if not a._lock.acquire(blocking=False):
            self.salidas[s] = dict(estado='esperando_agente', motivo='Estado del activo ocupado; reintento en siguiente barrido.')
            return dict(simbolo=s, estado='esperando_agente', cantidad=a.cuenta.cantidad)
        try:
            if a.cuenta.cantidad <= 0:
                self._limpiar(s, a)
            edad_efectiva = ahora + (time.perf_counter()-inicio)*1000
            if precio:
                self._cotizacion[s] = precio['ts_ms']
            if precio and (not all(math.isfinite(precio[k]) and precio[k] > 0 for k in ('bid','ask')) or precio['ask'] < precio['bid']):
                raise paper.OrdenRechazada('Cotización inválida.')
            fila = super()._revisar(a, precio, edad_efectiva)
            if a.cuenta.cantidad > 0 and fila.get('estado') == 'dato_atrasado':
                self.salidas[s] = dict(estado='dato_atrasado', motivo='Sin precio reciente; no se confirma liquidación.')
            return fila
        except Exception as e:
            # No publicar cuerpos de proveedor; preservar cuenta y seguir con otros.
            self.salidas[s] = dict(estado='pendiente', motivo='No se confirmó el cierre; se reintentará con datos válidos.', error=type(e).__name__)
            return dict(simbolo=s, estado='salida_pendiente' if a.cuenta.cantidad else 'error', cantidad=a.cuenta.cantidad,
                        motivo=self.salidas[s]['motivo'])
        finally:
            a._lock.release()

    def barrer(self, libro, ahora_ms):
        inicio = time.perf_counter()
        self._libros_en_barrido = 0
        # Máximo cuatro consultas de salida concurrentes; nunca duplicar trabajo por activo.
        for s, a in self.agentes.items():
            if a.cuenta.cantidad > 0 and s not in self.trabajos:
                self.trabajos[s] = self.pool.submit(self._seguro, s, a, libro.get(s), ahora_ms, inicio)
        if self.trabajos:
            wait(list(self.trabajos.values()), timeout=.8)
        for s, trabajo in list(self.trabajos.items()):
            if trabajo.done():
                self.radar[s] = trabajo.result()
                del self.trabajos[s]
        # No aumentar exposición mientras hay salidas ocupadas, atrasadas o pendientes.
        bloqueada = bool(self.trabajos) or any(a.cuenta.cantidad > 0 and self.salidas.get(s, {}).get('estado') in
                       ('pendiente','esperando_agente','dato_atrasado') for s,a in self.agentes.items())
        planos = [(s,a) for s,a in self.agentes.items() if a.cuenta.cantidad <= 0 and s not in self.trabajos]
        if planos:
            k = self._rotacion % len(planos)
            planos = planos[k:] + planos[:k]
            self._rotacion += 3
        for s,a in planos:
            if bloqueada:
                self.radar[s] = dict(simbolo=s, estado='esperando_salidas', cantidad=0, motivo='Salidas prioritarias pendientes.')
            else:
                self.radar[s] = self._seguro(s,a,libro.get(s),ahora_ms,inicio)
        self.latencias.append((time.perf_counter()-inicio)*1000)
        self.barridos += 1
        self.ultimo_barrido_ms = ahora_ms
        return self.estadisticas()

    def _vigilar_posicion(self, a, c, bid, fila):
        s = a.limites.simbolo
        if a.estado == 'detenido' or (a.estado == 'pausado' and not a.por_fallo):
            self.salidas[s] = dict(estado='desactivada', motivo='Bot detenido: salidas automáticas desactivadas.')
            return super()._vigilar_posicion(a,c,bid,fila)
        pendiente = a.salida_pendiente
        if pendiente and pendiente['entrada'] != c.entrada_ms:
            self._limpiar(s,a)
            pendiente = None
        stop_disparado = c.stop is not None and bid <= c.stop
        motivo = 'stop' if stop_disparado else (pendiente['motivo'] if pendiente else
                  'objetivo' if c.objetivo is not None and bid >= c.objetivo else None)
        if not motivo:
            self.salidas[s] = dict(estado='vigilando', motivo='Stop y objetivo supervisados por reglas.')
            return super()._vigilar_posicion(a,c,bid,fila)
        if not pendiente or pendiente['motivo'] != motivo:
            pendiente = dict(entrada=c.entrada_ms, motivo=motivo, detectado=a.ahora())
            a.store._ejecutar('INSERT OR REPLACE INTO salidas_pendientes VALUES(?,?,?,?)',a.run_id,c.entrada_ms,motivo,pendiente['detectado'])
            a.salida_pendiente = pendiente
        self.salidas[s] = dict(estado='pendiente', motivo=motivo, detectado_ms=pendiente['detectado'])
        limite = c.objetivo if motivo == 'objetivo' and a.limites.espera_max_min > 0 else None
        precio, costos = self._precio_salida(a,c.cantidad,bid,limite)
        if a.ahora()-self._cotizacion.get(s,0) > a.limites.edad_precio_max_s*1000:
            raise paper.OrdenRechazada('Cotización vencida durante la consulta de salida.')
        nueva = paper.Cuenta(**c.__dict__)
        comision, deslizamiento = a.limites.comision_efectiva, a.limites.deslizamiento_bps
        if motivo == 'objetivo' and a.limites.espera_max_min > 0:
            if precio < c.objetivo:
                raise paper.OrdenRechazada('Objetivo pendiente: profundidad no permite el precio límite.')
            precio, comision, deslizamiento = c.objetivo, a.limites.comision_espera, 0.0
            costos = 'orden en espera al objetivo, profundidad completa observada (Paper)'
        e = paper.vender(nueva,precio,a._filtros(),comision,deslizamiento,motivo)
        with a.store.transaccion():
            a.store.guardar_orden(a.run_id,None,None,e.lado,'ejecutada',e.motivo,e.cantidad,e.precio,e.comision,e.resultado,
                modelo_costos=f'{costos}; deslizamiento {deslizamiento:g} pb; comisión {comision:.2%}')
            a.store.guardar_cuenta(a.run_id,nueva)
            a.store._ejecutar('DELETE FROM salidas_pendientes WHERE run=?',a.run_id)
        a.cuenta = nueva
        a.salida_pendiente = None
        self._stop_guardado.pop(a.run_id,None)
        self.salidas[s] = dict(estado='cerrada_paper', motivo=motivo, confirmado_ms=a.ahora(),
                               demora_ms=max(0,a.ahora()-pendiente['detectado']), precio=e.precio)
        self.eventos.emitir('ejecutar','cuenta',tipo='ordenes',detalle=f'{s}: cierre Paper confirmado por {motivo}')
        return fila | dict(estado='sin_senal', cantidad=0, stop=None, objetivo=None, entrada=None,
                           efectivo=nueva.efectivo, valor=nueva.efectivo)

    def _precio_salida(self, a, cantidad, bid, limite=None):
        return precio_salida(a, cantidad, bid, limite)
