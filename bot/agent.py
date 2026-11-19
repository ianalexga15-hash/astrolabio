"""Ciclo del agente: observar, predecir, proponer, controlar, ejecutar en Paper y registrar."""
import json
import math
import threading
import time

import numpy as np

from bot import data, features, llm, maquina_tiempo, mexc, paper, risk, salidas
from bot.events import NULO
from bot.paper import Cuenta, Filtros, OrdenRechazada

HISTORIA = 120  # velas para calcular indicadores y la ventana del modelo
HORA_MS = 3_600_000
DIA_MS = 86_400_000


def _vela(fila):
    return dict(open_time=int(fila[0]), open=float(fila[1]), high=float(fila[2]), low=float(fila[3]), close=float(fila[4]),
                volume=float(fila[5]), close_time=int(fila[6]))


def _contexto_vela(d, maquina=None):
    """De una decisión guardada, lo que el reflejo usa para mostrar, sin armar nada, qué condiciones de compra ya se cumplen."""
    ind, cierre = json.loads(d['indicadores'] or '{}'), d['precio']
    atr, dist = ind.get('atr14'), ind.get('dist_sma20')  # atr14 y dist_sma20 son relativos al cierre
    return dict(fecha=d['fecha_vela'], cierre=cierre, atr_abs=math.nan if atr is None else atr * cierre, sma20=math.nan if dist is None else cierre / (1 + dist),
                filtro=d['filtro'], umbral=d['umbral'], pronostico=d['pronostico'], senal=bool(d['senal']), propuesta=d['accion_propuesta'],
                accion=d['accion_final'], motivos=json.loads(d['motivos'] or '[]'), maquina=maquina)


class Agente:
    def __init__(self, store, mercado, modelo, proponente, limites, run_id='live', ahora=None, eventos=NULO,
                 espera_reintento_s=300, modo_reflejo=False):
        self.store, self.mercado, self.modelo, self.proponente = store, mercado, modelo, proponente
        self.limites, self.run_id = limites, run_id
        self.ahora = ahora or (lambda: time.time() * 1000)
        self.eventos = eventos
        self.espera_reintento_s = espera_reintento_s
        self.modo_reflejo = modo_reflejo  # con reflejo, el ciclo diario arma la compra y el reflejo la ejecuta en vivo
        self.reflejo_desde_ms = None
        self.salida_pendiente = None  # venta que el reflejo protegido reintenta en cada barrido (tabla salidas_pendientes)
        self.retirado = None  # MEXC ya no lista el par: queda en pausa hasta que se cambie config/universo.json
        self.fecha_ultima = None
        self.filtros = None
        self.pronostico = None
        self.contexto_vela = None  # última decisión: con ella el radar muestra qué condiciones de compra ya se cumplen
        self._lock = threading.RLock()  # protege la cuenta: nunca se retiene mientras se consulta al LLM
        self._ciclo = threading.Lock()  # un solo ciclo a la vez por activo
        store.abrir_run(run_id, 'replay' if run_id.startswith('replay') else 'live', limites.simbolo)
        guardada = store.cargar_cuenta(run_id)
        self.cuenta = guardada or Cuenta(efectivo=limites.capital_inicial)
        if guardada is None:
            store.guardar_cuenta(run_id, self.cuenta, limites.capital_inicial)
        e = store.cargar_estado(run_id)
        self.estado = e['estado'] if e else 'detenido'
        self.motivo = e['motivo'] if e else ''
        self.por_fallo = bool(e['por_fallo']) if e else False
        self.proximo_reintento = e['proximo_reintento'] if e else 0.0
        self.error_modelo = getattr(modelo, 'error', None)  # el modelo no pasó la revisión al cargar
        if self.error_modelo and (self.estado == 'activo' or self.por_fallo):  # detenido o en pausa manual es decisión humana
            self._pausa_por_modelo()
        ultima = store.ultima_decision(run_id) if guardada else None
        if ultima:
            self.pronostico, self.fecha_ultima = ultima['pronostico'], ultima['fecha_vela']
            self.contexto_vela = _contexto_vela(ultima)  # tras un reinicio no hay que esperar a la próxima vela diaria

    # Control humano
    def _fijar(self, estado, motivo='', por_fallo=False):
        self.estado, self.motivo, self.por_fallo = estado, motivo, por_fallo
        self.store.guardar_estado(self.run_id, estado, motivo, por_fallo, self.proximo_reintento)
        self.eventos.emitir('control', 'estado', detalle=f'{estado} {motivo}'.strip())

    def iniciar(self):
        if self.error_modelo:
            return self._pausa_por_modelo()
        if self.retirado:  # sin precios no hay nada que activar
            return self._fallo('datos', self.retirado, reintentar=False)
        self._fijar('activo')

    def _pausa_por_modelo(self):
        """Modelo dañado: no decide ni compra; en pausa por fallo, stops y salidas siguen protegiendo lo abierto."""
        motivo = f'{self.limites.simbolo}, modelo: {self.error_modelo}'
        if motivo != self.motivo:
            self.store.registrar_error('modelo', motivo, 'DataError', 'Pausar el activo hasta reemplazar el modelo y reiniciar.', 'Sin operaciones.')
        self.proximo_reintento = 0.0
        self._fijar('pausado', motivo, por_fallo=True)

    def pausar(self, motivo='Pausa manual'):
        self._fijar('pausado', motivo)

    def detener(self):
        """Bloquea órdenes nuevas. No liquida: la posición sigue visible y cerrarla es otra acción."""
        self._fijar('detenido', 'Detenido por la persona usuaria; la posición abierta no se liquida.')

    def cerrar_posicion(self, precio=None):
        with self._lock:
            if self.cuenta.cantidad <= 0:
                raise ValueError('No hay posición abierta que cerrar.')
            precio = precio if precio is not None else self._precio_cierre(self.cuenta.cantidad, self.mercado.ticker(self.limites.simbolo))
            cuenta = Cuenta(**self.cuenta.__dict__)
            e = paper.vender(cuenta, precio, self._filtros(), self.limites.comision_efectiva, self.limites.deslizamiento_bps, 'manual')
            with self.store.transaccion():
                self.store.guardar_orden(self.run_id, None, None, e.lado, 'ejecutada', e.motivo, e.cantidad, e.precio, e.comision, e.resultado)
                self.store.guardar_cuenta(self.run_id, cuenta)
            self.cuenta = cuenta
        self.eventos.emitir('ejecutar', 'cuenta', tipo='ordenes', detalle=f'{self.limites.simbolo}: cierre manual')
        return e

    def _precio_cierre(self, cantidad, tope):
        """Vender todo recorriendo el libro visible, como el reflejo; sin profundidad completa no se declara el cierre."""
        if not hasattr(self.mercado, 'profundidad'):  # replay y pruebas: solo velas, sin libro
            return tope
        return salidas.precio_salida(self, cantidad, tope)[0]

    def _filtros(self):
        if self.filtros is None:
            self.filtros = Filtros(**{k: v for k, v in self.mercado.filters(self.limites.simbolo).items()
                                      if k in ('paso_cantidad', 'minimo_quote')})
        return self.filtros

    def _fallo(self, etapa, e, reintentar=True):
        """Registra y pausa. Si la causa es externa, el ciclo reintenta solo; nunca opera con datos dudosos."""
        self.proximo_reintento = self.ahora() + self.espera_reintento_s * 1000 if reintentar else 0.0
        accion = 'Pausar decisiones nuevas; reintento automático.' if reintentar else 'Pausar; requiere intervención humana.'
        motivo = f'{self.limites.simbolo}, {etapa}: {e}'
        if motivo != self.motivo:  # el mismo fallo no se repite en la bitácora a cada reintento
            self.store.registrar_error(etapa, motivo, type(e).__name__, accion, 'Sin operaciones.')
        self._fijar('pausado', motivo, por_fallo=reintentar)
        self.eventos.emitir(etapa, 'estado', tipo='error', detalle=str(e)[:200])
        return {'resultado': 'fallo', 'etapa': etapa, 'error': str(e)}

    def retirar(self, e):
        """MEXC ya no lista el par: pausa sin reintentos y sin repetir el error. Detenido o en pausa manual sigue siendo decisión humana."""
        self.retirado = e
        if self.estado == 'activo' or self.por_fallo:
            return self._fallo('datos', e, reintentar=False)
        return {'resultado': 'inactivo', 'estado': self.estado}

    # Ciclo
    def tick(self):
        if not self._ciclo.acquire(blocking=False):
            return {'resultado': 'ocupado'}
        try:
            return self._tick()
        finally:
            self._ciclo.release()

    def _tick(self):
        if self.error_modelo:  # sin modelo válido no hay decisiones: se arregla reemplazándolo y reiniciando
            return {'resultado': 'inactivo', 'estado': self.estado}
        reintento = self.estado == 'pausado' and self.por_fallo and self.ahora() >= self.proximo_reintento
        if self.estado != 'activo' and not reintento:
            return {'resultado': 'inactivo', 'estado': self.estado}
        ultima = self.store.ultima_procesada(self.run_id, self.limites.simbolo)
        if ultima is not None and self.ahora() < ultima + 2 * DIA_MS:  # la siguiente vela aún no cierra: no hace falta consultar
            if self.estado == 'pausado':
                self._fijar('activo')
            return {'resultado': 'sin_velas_nuevas'}
        try:
            filas = self.mercado.closed_candles(self.limites.simbolo, HISTORIA, self.ahora())
            self.eventos.emitir('mexc_velas', 'grabador', tipo='datos', detalle=self.limites.simbolo)
            filas = [f for f in filas if int(f[6]) <= self.ahora()]  # defensa: nunca usar una vela abierta
            df = self._validar(filas)
            filtros = self._filtros()
            precio = self.mercado.ticker(self.limites.simbolo)
        except mexc.ParRetirado as e:
            return self.retirar(e)
        except (mexc.MexcError, data.DataError) as e:
            return self._fallo('datos', e)

        nuevas = [_vela(f) for f in filas if ultima is None or int(f[0]) > ultima]
        if not nuevas:
            if self.estado == 'pausado':
                self._fijar('activo')
            return {'resultado': 'sin_velas_nuevas'}
        vela = nuevas[-1]
        edad = (self.ahora() - vela['close_time']) / HORA_MS
        if edad > self.limites.antiguedad_max_horas:
            return self._fallo('datos', data.DataError(f'Dato atrasado: la última vela cerrada tiene {edad:.1f} h '
                                                       f'(máximo {self.limites.antiguedad_max_horas} h).'))
        self.store.guardar_velas(self.limites.simbolo, filas)
        self.eventos.emitir('grabador', 'validador', tipo='datos', detalle=self.limites.simbolo)
        return self._procesar(df, vela, nuevas[:-1] if ultima is not None else [], precio, filtros, edad)

    def _validar(self, filas):
        df = data.frame_from_rows(filas)
        informe = data.audit(df)
        problemas = {k: informe[k] for k in ('duplicadas', 'desordenadas', 'invalidos', 'huecos', 'desalineadas', 'incoherentes')
                     if informe[k]}
        if problemas:
            raise data.DataError(f'Velas no válidas para decidir: {problemas}.')
        return df

    def _procesar(self, df, vela, omitidas, precio_ejecucion, filtros, edad):
        lim = self.limites
        try:
            tabla = features.add_indicators(df)
            pronostico = float(self.modelo.pronosticar(tabla))
            if not math.isfinite(pronostico):
                raise data.DataError(f'Pronóstico no finito: {pronostico}.')
            senal, regla = self.modelo.senal(pronostico, tabla, lim.filtro_minimo)
            if self.modo_reflejo:  # el filtro técnico se revisa en vivo: puede cumplirse durante el día
                senal = regla.get('cumple_umbral', senal)
        except data.DataError as e:
            return self._fallo('modelo', e)
        self.eventos.emitir('variables', 'modelo', tipo='datos', detalle=lim.simbolo)
        self.eventos.emitir('modelo', 'analista', tipo='decision', detalle=f'{lim.simbolo} {pronostico:+.3%}')

        ultima_fila = tabla.iloc[-1]
        atr_abs = float(ultima_fila.atr14 * vela['close'])
        fecha_vela = data.fecha(vela['open_time'])
        self.fecha_ultima = fecha_vela
        indicadores = {k: (None if not np.isfinite(ultima_fila[k]) else round(float(ultima_fila[k]), 6))
                       for k in features.INDICADORES}
        contexto = dict(simbolo=lim.simbolo, fecha_vela=fecha_vela, pronostico=round(pronostico, 6),
                        umbral=regla.get('umbral'), filtro=regla.get('filtro'), senal_modelo=bool(senal),
                        precio=vela['close'], en_posicion=self.cuenta.cantidad > 0, modelo_version=self.modelo.version)
        herramientas = self._herramientas(indicadores)
        try:  # el LLM tarda segundos: aquí no se retiene la cuenta para que el reflejo siga vigilando
            propuesta = self.proponente.proponer(contexto, herramientas)
        except llm.ClaveInvalida as e:
            return self._fallo('llm', e, reintentar=False)
        except (llm.LLMNoDisponible, llm.PropuestaInvalida) as e:
            return self._fallo('llm', e)
        self.eventos.emitir('analista', 'riesgo', tipo='decision', detalle=f'{lim.simbolo} {propuesta.accion}')

        # Sin mirar la posición: un stop de esta misma vela la cierra más abajo, y esa compra también debe pasar por el repaso y el tope.
        puede_comprar = senal and propuesta.accion == 'comprar'
        maquina = ((maquina_tiempo.repasar(tabla[data.PRECIOS].to_numpy(dtype=float), atr_abs, lim) or dict(r_medio=math.nan))  # sin repaso no hay autorización
                   if lim.maquina_tiempo and puede_comprar else None)
        compras_hoy = self.store.compras_autorizadas(self.run_id.split(':', 1)[0], fecha_vela) if lim.max_compras_dia and puede_comprar else None

        with self._lock:
            cuenta = Cuenta(**self.cuenta.__dict__)
            ejecuciones = []
            for v in omitidas + [vela]:
                vigilada = self.reflejo_desde_ms is not None and self.reflejo_desde_ms <= v['open_time']  # el reflejo ya la vigiló en vivo
                posterior = cuenta.entrada_ms is not None and cuenta.entrada_ms > v['open_time']  # el máximo o mínimo pudo ser anterior a la entrada
                if vigilada or posterior:
                    continue
                e = paper.revisar_stops(cuenta, v, filtros, lim.comision_efectiva, lim.deslizamiento_bps)
                if e:
                    ejecuciones.append((v, e))
            paper.mover_trailing(cuenta, vela['close'], atr_abs, lim.trailing_atr, lim.proteger_atr, 2 * lim.comision_efectiva + lim.deslizamiento_bps / 10_000)
            valor = paper.patrimonio(cuenta, vela['close'])
            pico = max(self.store.patrimonio_maximo(self.run_id) or lim.capital_inicial, valor)
            inicio_dia = self.store.ultimo_patrimonio(self.run_id) or lim.capital_inicial
            estado_efectivo = 'activo' if self.por_fallo else self.estado
            perdida = None
            if lim.pausa_tras_perdida_dias:  # protección tras pérdidas: día del último stop que cerró perdiendo, también en esta vela
                perdidas = [v['open_time'] for v, e in ejecuciones if e.motivo == 'stop' and e.resultado < 0]
                perdida = perdidas[-1] if perdidas else self.store.ultimo_stop_con_perdida(self.run_id)
            ctx = risk.Contexto(estado=estado_efectivo, simbolo=lim.simbolo, edad_horas=edad, senal=bool(senal), cuenta=cuenta,
                                precio=vela['close'], atr_abs=atr_abs, patrimonio=valor, patrimonio_inicio_dia=inicio_dia,
                                patrimonio_maximo=pico, maquina=maquina, compras_hoy=compras_hoy,
                                dias_desde_perdida=None if perdida is None else (vela['open_time'] - perdida) / DIA_MS)
            d = risk.evaluar(propuesta.accion, ctx, lim)

            orden = None
            venta_pendiente = None
            cuenta.armada = None
            if d.accion == 'comprar' and self.modo_reflejo:
                cuenta.armada = dict(vela=vela['open_time'], fecha=fecha_vela, expira_ms=vela['close_time'] + DIA_MS, cierre=vela['close'], atr_abs=atr_abs,
                                     sma20=float(ultima_fila.sma20), filtro=regla.get('filtro'), pronostico=pronostico)
            elif d.accion == 'comprar':
                try:
                    orden = paper.comprar(cuenta, precio_ejecucion, d.monto_quote, filtros, lim.comision_efectiva, lim.deslizamiento_bps, 'senal')
                    cuenta.stop, cuenta.objetivo, cuenta.atr_abs = d.stop, d.objetivo, atr_abs
                    cuenta.entrada_ms = vela['close_time']
                except OrdenRechazada as e:
                    orden = e
            elif d.accion == 'vender':
                try:
                    if self.modo_reflejo:  # en vivo, la venta diaria también recorre el libro
                        precio_ejecucion = self._precio_cierre(cuenta.cantidad, precio_ejecucion)
                    orden = paper.vender(cuenta, precio_ejecucion, filtros, lim.comision_efectiva, lim.deslizamiento_bps, 'decision')
                except OrdenRechazada as e:
                    orden = e
                    if self.modo_reflejo and cuenta.cantidad > 0:  # sin libro suficiente, el reflejo la reintenta en cada barrido
                        venta_pendiente = dict(entrada=cuenta.entrada_ms, motivo='decision', detectado=self.ahora())

            decision = dict(
                run=self.run_id, vela=vela['open_time'], fecha_vela=fecha_vela, modelo_version=self.modelo.version,
                pronostico=pronostico, senal=int(bool(senal)), umbral=regla.get('umbral'), filtro=regla.get('filtro'),
                accion_propuesta=propuesta.accion, justificacion=propuesta.justificacion, origen=propuesta.origen,
                llm_modelo=propuesta.modelo, latencia_ms=propuesta.latencia_ms, herramientas=json.dumps(propuesta.herramientas),
                aprobada=int(d.aprobada), accion_final=d.accion, motivos=json.dumps(d.motivos, ensure_ascii=False),
                precio=vela['close'], indicadores=json.dumps(indicadores))
            with self.store.transaccion():
                decision_id = self.store.guardar_decision(**decision)
                for v, e in ejecuciones:
                    self.store.guardar_orden(self.run_id, decision_id, v['open_time'], e.lado, 'ejecutada', e.motivo, e.cantidad, e.precio, e.comision, e.resultado)
                if isinstance(orden, OrdenRechazada):
                    self.store.guardar_orden(self.run_id, decision_id, vela['open_time'], d.accion, 'rechazada', str(orden))
                    if venta_pendiente:
                        self.store._ejecutar('INSERT OR REPLACE INTO salidas_pendientes VALUES(?,?,?,?)', self.run_id,
                                             venta_pendiente['entrada'], venta_pendiente['motivo'], venta_pendiente['detectado'])
                elif orden:
                    self.store.guardar_orden(self.run_id, decision_id, vela['open_time'], orden.lado, 'ejecutada', orden.motivo, orden.cantidad, orden.precio, orden.comision, orden.resultado)
                for v in omitidas:
                    self.store.marcar_procesada(self.run_id, lim.simbolo, v['open_time'], 'omitida')
                    self.store.marcar_patrimonio(self.run_id, v['open_time'], data.fecha(v['open_time']), cuenta, v['close'])
                self.store.marcar_procesada(self.run_id, lim.simbolo, vela['open_time'], 'procesada')
                marca = precio_ejecucion if orden and not isinstance(orden, OrdenRechazada) else vela['close']
                self.store.marcar_patrimonio(self.run_id, vela['open_time'], fecha_vela, cuenta, marca)
                self.store.guardar_cuenta(self.run_id, cuenta, max(pico, paper.patrimonio(cuenta, marca)))
            self.cuenta = cuenta
            self.pronostico = pronostico
            self.contexto_vela = _contexto_vela(decision, maquina)  # el repaso no se guarda en la base: solo existe hasta reiniciar
            if venta_pendiente:
                self.salida_pendiente = venta_pendiente

        self.eventos.emitir('riesgo', 'ejecutar', tipo='autorizacion' if d.aprobada else 'bloqueo', detalle=f'{lim.simbolo} {d.accion}')
        if orden and not isinstance(orden, OrdenRechazada):
            self.eventos.emitir('ejecutar', 'cuenta', tipo='ordenes', detalle=f'{lim.simbolo} {orden.lado} {orden.cantidad}')
        self.eventos.emitir('ejecutar', 'registro', tipo='datos', detalle=lim.simbolo)
        if d.bloquear:
            self.proximo_reintento = 0.0
            self._fijar('bloqueado', ' '.join(d.motivos))
        elif self.estado == 'pausado':
            self._fijar('activo')
        return {'resultado': 'procesada', 'accion': d.accion, 'aprobada': d.aprobada, 'pronostico': pronostico}

    def _herramientas(self, indicadores):
        """Herramientas de solo lectura para el LLM. Ninguna escribe ni revela claves."""
        lim = self.limites
        return {
            'consultar_cuenta': lambda: dict(efectivo=round(self.cuenta.efectivo, 2), cantidad=self.cuenta.cantidad, stop=self.cuenta.stop, objetivo=self.cuenta.objetivo),
            'consultar_indicadores': lambda: indicadores,
            'consultar_limites': lambda: dict(exposicion_max=lim.exposicion_max, perdida_diaria_max=lim.perdida_diaria_max,
                                              drawdown_max=lim.drawdown_max, riesgo_por_operacion=lim.riesgo_por_operacion),
            'consultar_historial': lambda: [dict(fecha=d['fecha_vela'], accion=d['accion_final'], pronostico=d['pronostico'])
                                            for d in self.store.decisiones(self.run_id)[-5:]],
        }

    # Replay: repetición histórica, separada de la conexión actual
    def replay(self, desde, hasta, filas):
        """Procesa filas[desde:hasta] con historia previa. Ejecuta en la apertura siguiente. Se identifica como replay."""
        self.store.abrir_run(self.run_id, 'replay')
        self.estado = 'activo'
        self.por_fallo = False
        ciclos = 0
        filtros = self._filtros()
        for i in range(desde, hasta):
            historia = filas[max(0, i - HISTORIA + 1):i + 1]
            df = self._validar(historia)
            vela = _vela(filas[i])
            self.ahora = lambda v=vela: v['close_time'] + 60_000
            r = self._procesar(df, vela, [], float(filas[i + 1][1]), filtros, 0.0)
            if r['resultado'] == 'fallo':
                raise RuntimeError(f'Replay detenido en {data.fecha(vela["open_time"])}: {r["error"]}')
            ciclos += 1
        return {'ciclos': ciclos, 'run': self.run_id}
