"""Cartera: organiza varios activos a la vez. Cada uno tiene un cupo igual de capital, su cuenta y su corrida."""
import time
from collections import deque
from dataclasses import replace

import numpy as np

from bot import mexc, paper
from bot.agent import Agente
from bot.events import NULO
from bot.paper import Cuenta
from bot.salidas import ReflejoProtegido as Reflejo

RUN_CARTERA = 'cartera'
HUECO_MAXIMO_MS = 60_000


class Cartera:
    def __init__(self, store, mercado, modelos, proponente, limites, ahora=None, eventos=NULO, espera_reintento_s=300):
        self.store, self.mercado, self.proponente, self.eventos = store, mercado, proponente, eventos
        self.ahora = ahora or (lambda: time.time() * 1000)
        self.limites = limites
        self.sin_modelo = [s for s, m in modelos.items() if m is None]
        con_modelo = {s: m for s, m in modelos.items() if m is not None}
        if not con_modelo:
            raise ValueError('No hay ningún activo con modelo aprobado.')
        cupo = limites.capital_inicial / len(con_modelo)
        self.agentes = {s: Agente(store=store, mercado=mercado, modelo=m, proponente=proponente, limites=replace(limites, simbolo=s, capital_inicial=cupo), run_id=f'live:{s}',
                                  ahora=self.ahora, eventos=eventos, espera_reintento_s=espera_reintento_s, modo_reflejo=True) for s, m in con_modelo.items()}
        self.reflejo = Reflejo(self.agentes, eventos)
        self.error_libro = None
        self.ultimo_libro_ms = None
        self.reloj = time.perf_counter
        self._ciclos_ms, self._intervalos_s, self._inicio_previo = deque(maxlen=3600), deque(maxlen=3600), None  # una hora a un barrido por segundo
        ahora_ms = self.ahora()
        for a in self.agentes.values():  # tras un reinicio, la vela en curso se revisa también con su máximo y mínimo
            a.reflejo_desde_ms = ahora_ms
        self.maximo = store.patrimonio_maximo(RUN_CARTERA) or limites.capital_inicial
        if store.cargar_cuenta(RUN_CARTERA) is None:
            store.guardar_cuenta(RUN_CARTERA, Cuenta(efectivo=limites.capital_inicial), self.maximo)
        self.aviso_capital = self._ajustar_cupos(cupo)
        self._ultimo_guardado = 0.0

    def _ajustar_cupos(self, cupo):
        """Si cambió la lista de activos o el capital, reparte el cupo en las cuentas que nunca operaron. Las que ya operaron no se tocan: se avisa."""
        distintos, alguien_opero = [], False
        for s, a in self.agentes.items():
            operadas = [o for o in self.store.ordenes(a.run_id) if o['estado'] == 'ejecutada']
            alguien_opero = alguien_opero or bool(operadas)
            inicial = a.cuenta.efectivo + a.cuenta.costo_entrada - sum(o['resultado'] or 0 for o in operadas)
            if abs(inicial - cupo) < 0.01:
                continue
            if operadas:
                distintos.append(s)
                continue
            a.cuenta = Cuenta(efectivo=cupo, armada=a.cuenta.armada)
            self.store.guardar_cuenta(a.run_id, a.cuenta)
            self.store.fijar_patrimonio_maximo(a.run_id, cupo)
            self.store.borrar_patrimonio(a.run_id)  # su curva plana con el cupo anterior haría creer que perdió o ganó
        if not alguien_opero:
            self.maximo = self.limites.capital_inicial
            self.store.fijar_patrimonio_maximo(RUN_CARTERA, self.maximo)
        if not distintos:
            return None
        # shortcut: el máximo de la cartera no se recalcula si ya hubo operaciones; se avisa y empezar de cero lo resuelve
        return f'{len(distintos)} activo(s) ya operaron con otro capital ({", ".join(distintos[:5])}). El rendimiento total no es comparable; para empezar de cero, apaga el bot y borra data/bot.sqlite3.'

    # Control humano: aplica a todos los activos
    def iniciar(self):
        inicio = self.ahora()
        for a in self.agentes.values():
            a.iniciar()
            a.reflejo_desde_ms = inicio

    def pausar(self):
        for a in self.agentes.values():
            a.pausar()

    def detener(self):
        for a in self.agentes.values():
            a.detener()

    def estado(self):
        estados = [a.estado for a in self.agentes.values()]
        for candidato in ('activo', 'bloqueado', 'pausado'):
            if candidato in estados:
                return candidato
        return 'detenido'

    def alertas(self):
        return [dict(simbolo=s, estado=a.estado, motivo=a.motivo) for s, a in self.agentes.items() if a.estado in ('pausado', 'bloqueado') and a.motivo != 'Pausa manual']

    def cerrar_posicion(self, simbolo=None):
        """Acción explícita: detener no liquida. Sin símbolo cierra todas las posiciones abiertas."""
        abiertos = [self.agentes[simbolo]] if simbolo else [a for a in self.agentes.values() if a.cuenta.cantidad > 0]
        if not abiertos:
            raise ValueError('No hay ninguna posición abierta que cerrar.')
        cerradas, pendientes = 0, []
        for a in abiertos:
            try:
                a.cerrar_posicion()
                cerradas += 1
            except (paper.OrdenRechazada, mexc.MexcError) as e:  # sin libro o sin precio de MEXC no se declara el cierre; los demás activos siguen
                pendientes.append(f'{a.limites.simbolo} ({e})')
        if pendientes:
            raise ValueError(f'Se cerraron {cerradas}; siguen abiertas sin cierre confirmado: {", ".join(pendientes)}. Reintenta en unos segundos.')
        return cerradas

    def aplicar_limites(self, limites):
        self.limites = limites
        cupo = limites.capital_inicial / len(self.agentes)
        for s, a in self.agentes.items():
            a.limites = replace(limites, simbolo=s, capital_inicial=cupo)
        self.aviso_capital = self._ajustar_cupos(cupo)

    # Cerebro: una vez al día por activo
    def ciclo(self):
        """Procesa la vela cerrada de cada activo, uno a la vez, porque Ollama atiende una consulta por vez."""
        conteo = dict(procesadas=0, fallos=0, sin_velas_nuevas=0, inactivos=0)
        detalle = {}
        for s, a in self.agentes.items():
            try:
                r = a.tick()
            except Exception as e:  # el error de un activo no debe detener la vigilancia de los demás
                self.store.registrar_error('agente', f'{s}: {e}', type(e).__name__, 'Pausar este activo.', 'Sin operaciones.')
                a.pausar(f'Error interno en {s}: {e}')
                r = {'resultado': 'fallo', 'error': str(e)}
            detalle[s] = r
            clave = {'procesada': 'procesadas', 'fallo': 'fallos', 'sin_velas_nuevas': 'sin_velas_nuevas'}.get(r['resultado'], 'inactivos')
            conteo[clave] += 1
        resultado = 'procesada' if conteo['procesadas'] else 'fallo' if conteo['fallos'] else 'sin_velas_nuevas' if conteo['sin_velas_nuevas'] else 'inactivo'
        return dict(resultado=resultado, **conteo, detalle=detalle)

    # Reflejo: cada segundo, todos los activos con una sola consulta
    def barrer(self):
        inicio = self.reloj()
        if self._inicio_previo is not None:
            self._intervalos_s.append(inicio - self._inicio_previo)
        self._inicio_previo = inicio
        try:
            return self._barrer()
        finally:
            self._ciclos_ms.append((self.reloj() - inicio) * 1000)  # con la consulta de red a MEXC incluida

    def medicion(self):
        """Barrido completo con red: duración e intervalo con percentiles, y cuántos se salieron del objetivo de 1 s."""
        def percentiles(valores):
            if not valores:
                return None
            p50, p95, p99 = np.percentile(np.array(valores), [50, 95, 99])
            return dict(p50=float(p50), p95=float(p95), p99=float(p99))
        return dict(barridos=len(self._ciclos_ms), ciclo_ms=percentiles(self._ciclos_ms), intervalo_s=percentiles(self._intervalos_s),
                    ciclos_lentos=sum(d > 1000 for d in self._ciclos_ms), intervalos_largos=sum(i > 2 for i in self._intervalos_s))

    def _barrer(self):
        try:
            libro = self.mercado.libro(list(self.agentes))
        except mexc.MexcError as e:
            self.error_libro = str(e)
            return dict(error=str(e), **self.reflejo.estadisticas())
        self.error_libro = None
        ahora = self.ahora()
        if self.ultimo_libro_ms is not None and ahora - self.ultimo_libro_ms > HUECO_MAXIMO_MS:
            for a in self.agentes.values():  # sin vigilancia en vivo: al cerrar, esta vela se revisa con su máximo y mínimo
                a.reflejo_desde_ms = ahora
        self.ultimo_libro_ms = ahora
        self._revisar_limites_globales(libro)
        e = self.reflejo.barrer(libro, ahora)
        self.eventos.emitir('mexc_ticker', 'reflejo', tipo='datos', detalle=f'{len(libro)} precios')
        self.eventos.emitir('reflejo', 'panel', tipo='datos', detalle=f'{e["latencia_ms"]:.2f} ms')
        return e

    def _valor(self, libro=None):
        total = 0.0
        for s, a in self.agentes.items():
            precio = (libro or {}).get(s)
            if precio:
                total += paper.patrimonio(a.cuenta, precio['bid'])
            else:
                fila = self.reflejo.radar.get(s)
                ref = fila['bid'] if fila and fila.get('bid') else a.cuenta.precio_medio
                total += paper.patrimonio(a.cuenta, ref)
        return total

    def _inicio_dia(self):
        total = 0.0
        for a in self.agentes.values():
            total += self.store.ultimo_patrimonio(a.run_id) or a.limites.capital_inicial
        return total

    def _revisar_limites_globales(self, libro):
        valor = self._valor(libro)
        if valor > self.maximo:
            self.maximo = valor
        if time.time() - self._ultimo_guardado > 60:  # basta guardar el máximo cada minuto
            self.store.guardar_cuenta(RUN_CARTERA, Cuenta(efectivo=valor), self.maximo)
            self._ultimo_guardado = time.time()
        caida = 1 - valor / self.maximo
        if caida >= self.limites.drawdown_max:
            motivo = f'Límite de caída máxima de la cartera alcanzado ({caida:.1%}).'
            self.store.guardar_cuenta(RUN_CARTERA, Cuenta(efectivo=valor), self.maximo)
            for a in self.agentes.values():
                if a.estado == 'activo':
                    a._fijar('bloqueado', motivo)
            self.reflejo.bloqueo_entradas = motivo
            return
        perdida = 1 - valor / self._inicio_dia()
        self.reflejo.bloqueo_entradas = f'Límite de pérdida diaria de la cartera alcanzado ({perdida:.1%}).' if perdida >= self.limites.perdida_diaria_max else None

    def resumen(self):
        valor = self._valor()
        expuesto = 0.0
        posiciones = 0
        armadas = 0
        for s, a in self.agentes.items():
            if a.cuenta.cantidad > 0:
                posiciones += 1
                fila = self.reflejo.radar.get(s)
                expuesto += a.cuenta.cantidad * (fila['bid'] if fila and fila.get('bid') else a.cuenta.precio_medio)
            elif a.cuenta.armada:
                armadas += 1
        return dict(patrimonio=valor, capital_inicial=self.limites.capital_inicial, rendimiento=valor / self.limites.capital_inicial - 1, caida=1 - valor / max(self.maximo, valor), posiciones=posiciones,
                    armadas=armadas, activos=len(self.agentes), exposicion=expuesto / valor if valor else 0.0, efectivo=sum(a.cuenta.efectivo for a in self.agentes.values()),
                    costos=sum(a.cuenta.costos for a in self.agentes.values()), bloqueo_entradas=self.reflejo.bloqueo_entradas, aviso_capital=self.aviso_capital, sin_modelo=self.sin_modelo, cupo=self.limites.capital_inicial / len(self.agentes))
