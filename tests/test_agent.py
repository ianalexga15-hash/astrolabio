"""Ciclo del agente y sus escenarios de error."""
import dataclasses

import numpy as np
import pytest

from bot import llm, mexc
from bot.agent import Agente
from bot.paper import Filtros, OrdenRechazada
from bot.risk import Limites
from bot.store import Store
from tests.helpers import DAY, START, random_walk, rows

L = Limites(simbolo='BTCUSDT', capital_inicial=50_000.0, comision=0.0, deslizamiento_bps=0.0, exposicion_max=0.8,
            perdida_diaria_max=0.05, drawdown_max=0.25, antiguedad_max_horas=26.0, riesgo_por_operacion=0.02,
            stop_atr=2.0, objetivo_atr=4.0, trailing_atr=2.0)
N = 60


class Mercado:
    def __init__(self, n=N, seed=1):
        self.filas = rows(random_walk(n + 40, seed=seed))
        self.n = n
        self.fallo = None
        self.precio = None

    def ahora(self):
        return START + self.n * DAY + 60_000  # un minuto después del cierre de la vela n-1

    def closed_candles(self, simbolo, limit, now_ms):
        if self.fallo:
            raise self.fallo
        return [f for f in self.filas[:self.n] if f[6] <= now_ms][-limit:]

    def filters(self, simbolo):
        return dict(paso_cantidad=0.000001, minimo_quote=1.0, maker=0.0, taker=0.0)

    def ticker(self, simbolo):
        if self.fallo:
            raise self.fallo
        return self.precio or float(self.filas[self.n][1])

    def avanzar(self, dias=1):
        self.n += dias


class Modelo:
    version = 'prueba'
    lookback = 20
    variables = ['ret']

    def __init__(self, valor=0.01, senal=True):
        self.valor, self.senal_fija = valor, senal
        self.umbral, self.filtro = 0.001, 'ninguno'

    def pronosticar(self, df):
        return self.valor

    def senal(self, pronostico, df, filtro_minimo=''):  # arma con su propio filtro, como una compra armada antes del filtro mínimo
        return self.senal_fija, dict(umbral=self.umbral, filtro=self.filtro)


class Proponente:
    def __init__(self, accion='comprar', error=None):
        self.accion, self.error, self.llamadas = accion, error, 0

    def proponer(self, contexto, herramientas):
        self.llamadas += 1
        if self.error:
            raise self.error
        return llm.Propuesta(accion=self.accion, simbolo=contexto['simbolo'], fecha_vela=contexto['fecha_vela'],
                             justificacion='prueba', origen='llm', modelo='falso', latencia_ms=1, herramientas=[])


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'bot.sqlite3')


def agente(store, mercado, modelo=None, proponente=None, limites=L, run='live'):
    a = Agente(store=store, mercado=mercado, modelo=modelo or Modelo(), proponente=proponente or Proponente(),
               limites=limites, run_id=run, ahora=mercado.ahora, espera_reintento_s=0)
    return a


def ordenes(store, run='live', estado='ejecutada'):
    return [o for o in store.ordenes(run) if o['estado'] == estado]


def test_arranca_detenido_y_no_opera_hasta_que_lo_inicien(store):
    m = Mercado()
    a = agente(store, m)
    assert a.estado == 'detenido'
    assert a.tick()['resultado'] == 'inactivo'
    assert not store.ordenes('live')


def test_ciclo_completo_observa_predice_propone_controla_ejecuta_y_registra(store):
    m = Mercado()
    p = Proponente('comprar')
    a = agente(store, m, proponente=p)
    a.iniciar()
    r = a.tick()
    assert r['resultado'] == 'procesada'
    d = store.decisiones('live')[0]
    assert d['pronostico'] == 0.01 and d['senal'] == 1 and d['accion_propuesta'] == 'comprar'
    assert d['accion_final'] == 'comprar' and d['aprobada'] == 1 and d['origen'] == 'llm'
    o = ordenes(store)[0]
    assert o['lado'] == 'comprar' and o['decision_id'] == d['id']
    cuenta = store.cargar_cuenta('live')
    assert cuenta.cantidad > 0 and cuenta.stop is not None and cuenta.objetivo is not None
    assert store.patrimonio('live')[-1]['patrimonio'] == pytest.approx(cuenta.efectivo + cuenta.cantidad * o['precio'])


def test_capital_inicial_sale_de_la_configuracion(store):
    a = agente(store, Mercado())
    assert a.cuenta.efectivo == 50_000.0 and a.cuenta.cantidad == 0.0


def test_evento_duplicado_no_opera_dos_veces_la_misma_vela(store):
    m = Mercado()
    p = Proponente('comprar')
    a = agente(store, m, proponente=p)
    a.iniciar()
    a.tick()
    assert a.tick()['resultado'] == 'sin_velas_nuevas'
    assert p.llamadas == 1 and len(ordenes(store)) == 1 and len(store.decisiones('live')) == 1


def test_reinicio_del_backend_recupera_estado_sin_duplicar(store, tmp_path):
    m = Mercado()
    a = agente(store, m)
    a.iniciar()
    a.tick()
    antes = store.cargar_cuenta('live')
    otro = Store(tmp_path / 'bot.sqlite3')
    p = Proponente('comprar')
    b = agente(otro, m, proponente=p)
    assert b.estado == 'activo'  # sigue como estaba
    assert b.cuenta == antes
    assert b.tick()['resultado'] == 'sin_velas_nuevas'
    assert p.llamadas == 0 and len(ordenes(otro)) == 1


def test_fallo_a_mitad_del_guardado_no_deja_estado_a_medias(store, monkeypatch):
    m = Mercado()
    a = agente(store, m)
    a.iniciar()
    monkeypatch.setattr(store, 'marcar_patrimonio', lambda *x, **k: (_ for _ in ()).throw(OSError('disco lleno')))
    with pytest.raises(OSError):
        a.tick()
    monkeypatch.undo()
    assert not store.ordenes('live') and not store.decisiones('live')
    assert store.cargar_cuenta('live') is None or store.cargar_cuenta('live').cantidad == 0
    assert not store.ya_procesada('live', 'BTCUSDT', m.filas[m.n - 1][0])


@pytest.mark.parametrize('fallo', [mexc.MexcUnavailable('sin respuesta'), mexc.MexcRateLimited('límite de solicitudes')])
def test_api_sin_respuesta_o_con_limite_pausa_registra_y_no_opera(store, fallo):
    m = Mercado()
    m.fallo = fallo
    p = Proponente()
    a = agente(store, m, proponente=p)
    a.iniciar()
    r = a.tick()
    assert r['resultado'] == 'fallo' and a.estado == 'pausado'
    assert str(fallo) in a.motivo
    assert p.llamadas == 0 and not store.ordenes('live')
    assert store.errores()[-1]['etapa'] == 'datos'


RETIRADO = mexc.ParRetirado('MEXC ya no lista BTCUSDT: responde «Invalid symbol» (código -1121).')


def test_par_retirado_queda_en_pausa_sin_reintentos_ni_errores_repetidos(store):
    m = Mercado()
    m.fallo = RETIRADO
    p = Proponente()
    a = agente(store, m, proponente=p)
    a.iniciar()
    assert a.tick()['resultado'] == 'fallo' and a.estado == 'pausado' and 'ya no lista' in a.motivo
    m.avanzar(3)  # pasan los días: un par retirado no se vuelve a consultar
    assert a.tick()['resultado'] == 'inactivo'
    a.iniciar()  # «Activar bot» no lo reactiva: sin precios no hay nada que activar
    assert a.estado == 'pausado' and 'ya no lista' in a.motivo
    b = agente(store, m, proponente=p)  # tras reiniciar, el hilo de velas lo vuelve a encontrar retirado
    b.retirar(RETIRADO)
    b.iniciar()
    assert b.estado == 'pausado' and len(store.errores()) == 1 and p.llamadas == 0


def test_par_retirado_con_el_bot_detenido_respeta_la_decision_humana(store):
    a = agente(store, Mercado())
    a.retirar(RETIRADO)  # el hilo de velas lo detecta con el bot detenido
    assert a.estado == 'detenido' and not store.errores()
    a.iniciar()
    assert a.estado == 'pausado' and 'ya no lista' in a.motivo and len(store.errores()) == 1


def test_dato_atrasado_pausa_y_no_opera(store):
    m = Mercado()
    p = Proponente()
    a = agente(store, m, proponente=p)
    a.ahora = lambda: m.ahora() + 30 * 3_600_000
    a.iniciar()
    r = a.tick()
    assert r['resultado'] == 'fallo' and 'atrasado' in a.motivo
    assert p.llamadas == 0 and not ordenes(store)


def test_vela_abierta_nunca_se_usa_como_definitiva(store):
    m = Mercado()
    a = agente(store, m)
    a.iniciar()
    m.closed_candles = lambda simbolo, limit, now_ms: m.filas[:m.n + 1]  # el proveedor incluye la vela abierta
    r = a.tick()
    assert r['resultado'] == 'procesada'
    assert store.decisiones('live')[0]['vela'] == m.filas[m.n - 1][0]


def test_velas_desordenadas_o_duplicadas_detienen_el_ciclo(store):
    m = Mercado()
    a = agente(store, m)
    a.iniciar()
    m.closed_candles = lambda simbolo, limit, now_ms: m.filas[:30] + m.filas[29:m.n]
    r = a.tick()
    assert r['resultado'] == 'fallo' and a.estado == 'pausado' and not store.ordenes('live')


def test_ollama_detenido_pausa_nuevas_decisiones_sin_operar_ni_consumir_la_vela(store):
    m = Mercado()
    p = Proponente(error=llm.LLMNoDisponible('Ollama detenido'))
    a = agente(store, m, proponente=p)
    a.iniciar()
    r = a.tick()
    assert r['resultado'] == 'fallo' and a.estado == 'pausado' and 'Ollama' in a.motivo
    assert not store.ordenes('live') and not store.ya_procesada('live', 'BTCUSDT', m.filas[m.n - 1][0])
    assert store.errores()[-1]['etapa'] == 'llm'


def test_cuando_ollama_regresa_el_agente_se_recupera_solo_y_procesa_la_vela(store):
    m = Mercado()
    p = Proponente(error=llm.LLMNoDisponible('Ollama detenido'))
    a = agente(store, m, proponente=p)
    a.iniciar()
    a.tick()
    p.error = None
    r = a.tick()
    assert r['resultado'] == 'procesada' and a.estado == 'activo' and len(ordenes(store)) == 1


def test_json_invalido_no_opera(store):
    m = Mercado()
    a = agente(store, m, proponente=Proponente(error=llm.PropuestaInvalida('JSON inválido')))
    a.iniciar()
    assert a.tick()['resultado'] == 'fallo' and 'JSON' in a.motivo
    assert not store.ordenes('live')


def test_clave_incorrecta_del_gateway_pausa_sin_reintento_automatico(store):
    m = Mercado()
    p = Proponente(error=llm.ClaveInvalida('clave rechazada'))
    a = agente(store, m, proponente=p)
    a.iniciar()
    a.tick()
    assert a.estado == 'pausado'
    p.error = None
    assert a.tick()['resultado'] == 'inactivo'  # requiere intervención humana
    assert p.llamadas == 1


def test_saldo_insuficiente_rechaza_y_registra_sin_cambiar_la_cuenta(store):
    m = Mercado()
    pobre = Limites(**{**L.__dict__, 'capital_inicial': 0.5})
    a = agente(store, m, limites=pobre)
    a.iniciar()
    assert a.tick()['resultado'] == 'procesada'
    rechazos = ordenes(store, estado='rechazada')
    assert rechazos and 'mínimo' in rechazos[0]['motivo']
    assert store.cargar_cuenta('live').cantidad == 0
    assert store.cargar_cuenta('live').efectivo == 0.5


def test_boton_detener_bloquea_ordenes_sin_liquidar_la_posicion(store):
    m = Mercado()
    a = agente(store, m)
    a.iniciar()
    a.tick()
    cantidad = store.cargar_cuenta('live').cantidad
    a.detener()
    m.avanzar()
    assert a.tick()['resultado'] == 'inactivo'
    assert store.cargar_cuenta('live').cantidad == cantidad and len(ordenes(store)) == 1
    assert a.estado == 'detenido'


def test_cerrar_posicion_es_una_accion_explicita_y_separada(store):
    m = Mercado()
    a = agente(store, m)
    a.iniciar()
    a.tick()
    a.detener()
    e = a.cerrar_posicion()
    assert e.motivo == 'manual' and store.cargar_cuenta('live').cantidad == 0
    assert [o['lado'] for o in ordenes(store)] == ['comprar', 'vender']


def test_cerrar_posicion_sin_posicion_informa_y_no_opera(store):
    a = agente(store, Mercado())
    with pytest.raises(ValueError, match='posición'):
        a.cerrar_posicion()


def test_pausa_manual_no_se_reanuda_sola(store):
    m = Mercado()
    p = Proponente()
    a = agente(store, m, proponente=p)
    a.iniciar()
    a.pausar()
    assert a.tick()['resultado'] == 'inactivo' and p.llamadas == 0
    a.iniciar()
    assert a.tick()['resultado'] == 'procesada'


def test_propuesta_rechazada_por_riesgo_queda_registrada_y_no_opera(store):
    m = Mercado()
    a = agente(store, m, modelo=Modelo(senal=False), proponente=Proponente('comprar'))
    a.iniciar()
    a.tick()
    d = store.decisiones('live')[0]
    assert d['aprobada'] == 0 and d['accion_final'] == 'mantener' and 'señal' in d['motivos']
    assert not store.ordenes('live')


def test_stop_loss_se_ejecuta_antes_de_decidir_sobre_la_vela_nueva(store):
    m = Mercado()
    a = agente(store, m, proponente=Proponente('comprar'))
    a.iniciar()
    a.tick()
    stop = store.cargar_cuenta('live').stop
    fila = m.filas[m.n]
    fila[1], fila[2], fila[3], fila[4] = str(stop * 1.01), str(stop * 1.02), str(stop * 0.9), str(stop * 0.95)
    m.avanzar()
    a.proponente = Proponente('mantener')
    a.modelo = Modelo(senal=False)
    a.tick()
    ventas = [o for o in ordenes(store) if o['lado'] == 'vender']
    assert len(ventas) == 1 and ventas[0]['motivo'] == 'stop'
    assert ventas[0]['precio'] == pytest.approx(stop)


def test_velas_perdidas_solo_revisan_stops_y_decide_sobre_la_ultima(store):
    m = Mercado()
    p = Proponente('mantener')
    a = agente(store, m, proponente=p)
    a.iniciar()
    a.tick()
    m.avanzar(3)
    a.tick()
    assert p.llamadas == 2
    assert len(store.decisiones('live')) == 2
    estados = store.procesadas('live')
    assert [e['estado'] for e in estados[-3:]] == ['omitida', 'omitida', 'procesada']
    assert len(store.patrimonio('live')) == 4


def test_caida_maxima_bloquea_el_bot_hasta_intervencion_humana(store):
    m = Mercado()
    a = agente(store, m)
    a.iniciar()
    a.pico_forzado = 1e9
    store.fijar_patrimonio_maximo('live', 1e9)
    a.tick()
    assert a.estado == 'bloqueado' and 'caída máxima' in a.motivo
    m.avanzar()
    assert a.tick()['resultado'] == 'inactivo'


def test_replay_queda_aislado_de_la_cuenta_en_vivo(store):
    m = Mercado()
    vivo = agente(store, m, run='live')
    vivo.iniciar()
    vivo.tick()
    antes = store.cargar_cuenta('live')
    r = agente(store, m, proponente=Proponente('comprar'), run='replay-1')
    resultado = r.replay(desde=m.n - 10, hasta=m.n - 1, filas=m.filas[:m.n])
    assert resultado['ciclos'] == 9
    assert store.cargar_cuenta('live') == antes
    assert store.run('replay-1')['tipo'] == 'replay'
    assert len(store.decisiones('replay-1')) == 9


def test_replay_ejecuta_en_la_apertura_siguiente_no_en_el_cierre(store):
    m = Mercado()
    r = agente(store, m, proponente=Proponente('comprar'), run='replay-2')
    r.replay(desde=m.n - 5, hasta=m.n - 3, filas=m.filas[:m.n])
    o = ordenes(store, run='replay-2')[0]
    vela = store.decisiones('replay-2')[0]['vela']
    siguiente = next(f for f in m.filas if f[0] == vela + DAY)
    assert o['precio'] == pytest.approx(float(siguiente[1]))


def test_el_contexto_al_llm_no_lleva_secretos_ni_futuro(store):
    m = Mercado()
    vistos = []

    class Espia(Proponente):
        def proponer(self, contexto, herramientas):
            vistos.append((contexto, herramientas))
            return super().proponer(contexto, herramientas)

    a = agente(store, m, proponente=Espia('mantener'))
    a.iniciar()
    a.tick()
    contexto, herramientas = vistos[0]
    assert contexto['fecha_vela'] == a.fecha_ultima
    assert not any('clave' in k.lower() or 'key' in k.lower() for k in contexto)
    assert set(herramientas) == {'consultar_cuenta', 'consultar_indicadores', 'consultar_limites', 'consultar_historial'}
    assert np.isfinite(herramientas['consultar_cuenta']()['efectivo'])


def test_consultar_al_llm_no_retiene_la_cuenta_para_que_el_reflejo_siga(store):
    m = Mercado()
    libre = []

    class Mira(Proponente):
        def proponer(self, contexto, herramientas):
            libre.append(a._lock.acquire(blocking=False))
            a._lock.release()
            return super().proponer(contexto, herramientas)

    import threading
    a = agente(store, m, proponente=Mira('mantener'))
    a._lock = threading.Lock()  # sin reentrada: si el ciclo la retuviera, la prueba lo detecta
    a.iniciar()
    a.tick()
    assert libre == [True]


def test_si_la_siguiente_vela_no_ha_cerrado_no_consulta_a_mexc(store):
    m = Mercado()
    a = agente(store, m)
    a.iniciar()
    a.tick()
    consultas = []
    m.closed_candles = lambda *x, **k: consultas.append(1) or []
    assert a.tick()['resultado'] == 'sin_velas_nuevas' and not consultas


def test_el_mismo_fallo_no_llena_la_bitacora_en_cada_reintento(store):
    m = Mercado()
    p = Proponente(error=llm.LLMNoDisponible('Ollama detenido'))
    a = agente(store, m, proponente=p)
    a.iniciar()
    for _ in range(5):
        a.tick()
    assert p.llamadas == 5 and len(store.errores()) == 1


@pytest.mark.parametrize('senal, tipo', [(True, 'autorizacion'), (False, 'bloqueo')])
def test_el_evento_de_riesgo_distingue_autorizacion_y_bloqueo(store, senal, tipo):
    from bot.events import Eventos
    a = agente(store, Mercado(), modelo=Modelo(senal=senal), proponente=Proponente('comprar'))
    a.eventos = Eventos()
    a.iniciar()
    a.tick()
    assert [e['tipo'] for e in a.eventos.recientes if e['origen'] == 'riesgo'] == [tipo]


def test_el_ciclo_diario_cobra_la_comision_real_del_par(store):
    from dataclasses import replace
    a = agente(store, Mercado(), proponente=Proponente('comprar'), limites=replace(L, comision=0.0, comision_por_par=(('BTCUSDT', 0.001),)))
    a.iniciar()
    a.tick()
    o = ordenes(store)[0]
    assert o['comision'] == pytest.approx(o['cantidad'] * o['precio'] * 0.001)


def test_maquina_del_tiempo_no_autoriza_comprar_lo_que_viene_cayendo_y_si_lo_que_viene_subiendo(store):
    lim = dataclasses.replace(L, maquina_tiempo=True)
    for run, paso, compra in (('cae', 0.99, False), ('sube', 1.01, True)):
        m = Mercado(n=100)
        m.filas = rows([100 * paso ** i for i in range(140)])
        a = agente(store, m, limites=lim, run=run)
        a.iniciar()
        assert a.tick()['resultado'] == 'procesada'
        d = store.decisiones(run)[0]
        assert (d['accion_final'] == 'comprar') is compra
        assert ('Máquina del tiempo' in d['motivos']) is not compra
        assert bool(ordenes(store, run)) is compra


def test_tope_diario_deja_comprar_solo_a_los_primeros_activos_de_la_cartera(store):
    lim = dataclasses.replace(L, max_compras_dia=1)
    for run, compra in (('live:A', True), ('live:B', False)):
        a = agente(store, Mercado(), limites=lim, run=run)
        a.iniciar()
        assert a.tick()['resultado'] == 'procesada'
        d = store.decisiones(run)[0]
        assert (d['accion_final'] == 'comprar') is compra
        assert ('Tope diario' in d['motivos']) is not compra


def test_maquina_del_tiempo_sin_historia_suficiente_no_autoriza_la_compra(store):
    a = agente(store, Mercado(), limites=dataclasses.replace(L, maquina_tiempo=True))  # 60 velas: el repaso pide 61
    a.iniciar()
    assert a.tick()['resultado'] == 'procesada'
    d = store.decisiones('live')[0]
    assert d['accion_final'] != 'comprar' and 'sin un repaso válido' in d['motivos']
    assert not ordenes(store)


class MercadoConLibro(Mercado):
    """Como en vivo: además del precio, un libro de compras visible."""

    def __init__(self, bids, **kw):
        super().__init__(**kw)
        self.bids = bids

    def profundidad(self, simbolo, limite=50):
        return {'bids': self.bids, 'asks': []}


def test_cierre_manual_recorre_el_libro_y_sin_profundidad_completa_no_declara_el_cierre(store):
    m = MercadoConLibro(bids=[])
    a = agente(store, m)
    a.iniciar()
    a.tick()
    cantidad = a.cuenta.cantidad
    assert cantidad > 0
    with pytest.raises(OrdenRechazada, match='[Pp]rofundidad'):
        a.cerrar_posicion()
    assert a.cuenta.cantidad == cantidad  # sigue abierta: no se declara un cierre que el libro no cubre
    tope = m.ticker('BTCUSDT')
    m.bids = [(tope * 0.99, cantidad * 10)]
    e = a.cerrar_posicion()
    assert a.cuenta.cantidad == 0 and e.precio == pytest.approx(tope * 0.99)


def test_venta_diaria_en_vivo_sin_libro_suficiente_queda_rechazada_y_pendiente_para_el_reflejo(store):
    m = MercadoConLibro(bids=[])
    a = agente(store, m)
    a.iniciar()
    a.tick()
    a.cuenta.stop, a.cuenta.objetivo = 1e-9, 1e12  # que no salga por stop ni objetivo en la vela siguiente
    a.modo_reflejo, a.proponente = True, Proponente('vender')
    m.avanzar()
    assert a.tick()['resultado'] == 'procesada'
    assert a.cuenta.cantidad > 0
    assert [o['lado'] for o in ordenes(store, estado='rechazada')] == ['vender']
    fila = store._una('SELECT * FROM salidas_pendientes WHERE run=?', 'live')  # sobrevive a un reinicio
    assert fila['motivo'] == 'decision' and fila['entrada'] == a.cuenta.entrada_ms
    assert a.salida_pendiente['motivo'] == 'decision'



def test_modelo_invalido_pausa_el_agente_lo_registra_y_no_opera(store):
    from bot.model import ModeloInvalido
    m = Mercado()
    agente(store, m).iniciar()  # operaba antes del reinicio
    a = agente(store, m, modelo=ModeloInvalido('Modelo v1 inválido: el peso m0_c0_w tiene valores no finitos.'))
    assert a.estado == 'pausado' and a.por_fallo and 'inválido' in a.motivo  # en pausa por fallo los stops siguen protegiendo
    assert any('inválido' in e['error'] for e in store.errores())
    a.iniciar()
    assert a.estado == 'pausado' and a.tick()['resultado'] == 'inactivo'
    assert not store.decisiones('live') and not store.ordenes('live')


def test_modelo_invalido_respeta_un_bot_detenido_hasta_que_lo_inicien(store):
    from bot.model import ModeloInvalido
    a = agente(store, Mercado(), modelo=ModeloInvalido('Modelo v1 inválido: el escalador tiene desviaciones no positivas.'))
    assert a.estado == 'detenido'  # detener es decisión humana: no se cambia por una pausa con salidas automáticas
    a.iniciar()
    assert a.estado == 'pausado' and 'inválido' in a.motivo


def test_tras_un_stop_con_perdida_el_activo_no_compra_durante_la_pausa(store):
    m = Mercado()
    a = agente(store, m, limites=dataclasses.replace(L, pausa_tras_perdida_dias=3))
    a.iniciar()
    m.precio = m.ticker('BTCUSDT') * 1.05  # compra 5 % cara: el stop siguiente cierra con pérdida, sin tocar la caída máxima
    a.tick()
    m.precio, a.cuenta.stop = None, 1e12  # el stop salta en la vela siguiente
    for _ in range(4):
        m.avanzar()
        a.tick()
    stops = [o for o in ordenes(store) if o['motivo'] == 'stop']
    assert len(stops) == 1 and stops[0]['resultado'] < 0
    decisiones = store.decisiones('live')[1:]
    assert [d['accion_final'] for d in decisiones] == ['mantener', 'mantener', 'mantener', 'comprar']
    assert 'Pausa tras pérdida' in decisiones[0]['motivos']


@pytest.mark.parametrize('minimo, compra', [('sma20', False), ('', True)])
def test_si_la_regla_de_va_no_trae_filtro_el_filtro_minimo_frena_la_compra(store, minimo, compra):
    """Decisión de Alex (2026-11-13), en el replay (sin reflejo): la compra exige el cierre sobre su SMA20. Con '' compra como antes."""
    from bot import model
    contrato = dict(version='v', tipo='cero', lookback=20, variables=['ret'], umbral=-1.0, filtro='ninguno', escalador={'media': [0.0], 'desv': [1.0]},
                    y_media=0.0, y_desv=1.0, miembros=[])
    m = Mercado()
    fila = m.filas[m.n - 1]
    fila[1], fila[2], fila[3], fila[4] = '50', '51', '49', '50'  # la última vela cierra muy por debajo de su SMA20
    a = agente(store, m, modelo=model.Modelo(contrato, {}), limites=dataclasses.replace(L, filtro_minimo=minimo))
    a.iniciar()
    a.tick()
    assert store.decisiones('live')[0]['filtro'] == (minimo or 'ninguno')
    assert bool(ordenes(store)) is compra


def test_tras_un_stop_en_la_misma_vela_la_compra_tambien_respeta_el_tope_diario(store):
    m = Mercado()
    b = agente(store, m, run='live:B')
    b.iniciar()
    b.tick()  # compra sin tope
    b.limites, b.cuenta.stop = dataclasses.replace(L, max_compras_dia=1), 1e12  # el stop salta en la vela siguiente
    m.avanzar()
    a = agente(store, m, limites=dataclasses.replace(L, max_compras_dia=1), run='live:A')
    a.iniciar()
    assert a.tick()['accion'] == 'comprar'  # A usa el único cupo de la vela
    b.tick()
    assert [o['motivo'] for o in ordenes(store, run='live:B') if o['lado'] == 'vender'] == ['stop']
    d = store.decisiones('live:B')[-1]
    assert d['accion_final'] != 'comprar' and 'Tope diario' in d['motivos']
