"""Eventos reales del sistema. La constelación del panel se mueve solo con esto, no con animación inventada."""
import asyncio
import threading
import time
from collections import deque


class Eventos:
    def __init__(self, historial=300):
        self._lock = threading.Lock()
        self.recientes = deque(maxlen=historial)
        self.ultimo_por_nodo = {}
        self.conteo = {}
        self._colas = []
        self._seq = 0

    def emitir(self, origen, destino, tipo='datos', detalle=''):
        with self._lock:
            self._seq += 1
            e = dict(id=self._seq, ts=time.time(), origen=origen, destino=destino, tipo=tipo, detalle=detalle)
            self.recientes.append(e)
            for nodo in (origen, destino):
                self.ultimo_por_nodo[nodo] = dict(ts=e['ts'], tipo=tipo)
                self.conteo[nodo] = self.conteo.get(nodo, 0) + 1
            colas = list(self._colas)
        for bucle, cola in colas:
            bucle.call_soon_threadsafe(cola.put_nowait, e)
        return e

    def suscribir(self):
        cola = asyncio.Queue(maxsize=500)
        registro = (asyncio.get_running_loop(), cola)
        with self._lock:
            self._colas.append(registro)
        return cola, registro

    def cancelar(self, registro):
        with self._lock:
            self._colas.remove(registro)


class _Nulo:
    def emitir(self, *a, **k):
        return None


NULO = _Nulo()
