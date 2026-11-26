"""El reflejo revisa cada segundo las condiciones de compra y venta de cada activo y ejecuta en Paper."""
from dataclasses import replace

import pytest

from bot import mexc
from bot.agent import Agente
from bot.paper import Cuenta
from bot.reflejo import Reflejo, precio_legible
from bot.risk import Limites
from bot.store import Store
from tests.helpers import rows
from tests.test_agent import L, Mercado, Modelo, Proponente

SYM = 'BTCUSDT'


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'r.sqlite3')


def preparar(store, mercado=None, modelo=None, limites=L, proponente=None):
    """Agente activo que ya procesó la vela de hoy, con la compra armada."""
    m = mercado or Mercado()
    a = Agente(store=store, mercado=m, modelo=modelo or Modelo(), proponente=proponente or Proponente('comprar'), limites=limites, run_id=f'live:{SYM}',
               ahora=m.ahora, espera_reintento_s=0, modo_reflejo=True)
    a.iniciar()
    assert a.tick()['resultado'] == 'procesada'
    return m, a, Reflejo({SYM: a})


def libro(precio, spread_bps=1.0, ts=None, m=None):
    ask = precio
    bid = precio * (1 - spread_bps / 10_000)
    return {SYM: dict(bid=bid, ask=ask, ts_ms=ts if ts is not None else m.ahora())}


def ordenes(store, estado='ejecutada'):
    return [o for o in store.ordenes(f'live:{SYM}') if o['estado'] == estado]


def test_el_ciclo_diario_arma_la_compra_pero_no_la_ejecuta(store):
    _, a, _ = preparar(store)
    assert a.cuenta.armada is not None and a.cuenta.cantidad == 0 and not ordenes(store)
    d = store.decisiones(f'live:{SYM}')[0]
    assert d['accion_final'] == 'comprar' and d['aprobada'] == 1


def test_sin_compra_armada_no_compra_aunque_el_precio_se_mueva(store):
    m, a, r = preparar(store, proponente=Proponente('mantener'))
    assert a.cuenta.armada is None
    r.barrer(libro(a.cuenta_precio_cierre if hasattr(a, 'cuenta_precio_cierre') else 100.0, m=m), m.ahora())
    assert not ordenes(store) and r.radar[SYM]['estado'] == 'sin_senal'


def test_cumplidas_las_condiciones_compra_en_automatico_al_precio_de_venta_del_libro(store):
    m, a, r = preparar(store)
    cierre = a.cuenta.armada['cierre']
    r.barrer(libro(cierre, m=m), m.ahora())
    o = ordenes(store)
    assert len(o) == 1 and o[0]['lado'] == 'comprar' and o[0]['precio'] == pytest.approx(cierre)
    assert a.cuenta.cantidad > 0 and a.cuenta.armada is None
    atr = a.cuenta.atr_abs
    assert a.cuenta.stop == pytest.approx(cierre - L.stop_atr * atr)
    assert a.cuenta.objetivo == pytest.approx(cierre + L.objetivo_atr * atr)
    assert r.radar[SYM]['estado'] == 'en_posicion'


def test_no_compra_dos_veces_en_barridos_seguidos(store):
    m, a, r = preparar(store)
    cierre = a.cuenta.armada['cierre']
    for _ in range(5):
        r.barrer(libro(cierre, m=m), m.ahora())
    assert len(ordenes(store)) == 1


def test_spread_amplio_espera_y_sigue_revisando(store):
    m, a, r = preparar(store)
    cierre = a.cuenta.armada['cierre']
    r.barrer(libro(cierre, spread_bps=200, m=m), m.ahora())
    assert not ordenes(store)
    fila = r.radar[SYM]
    assert fila['estado'] == 'armada' and not next(c for c in fila['condiciones'] if c['id'] == 'spread')['cumple']
    r.barrer(libro(cierre, spread_bps=2, m=m), m.ahora())
    assert len(ordenes(store)) == 1


def test_no_persigue_un_precio_que_ya_se_alejo_y_compra_si_regresa(store):
    m, a, r = preparar(store)
    cierre, atr = a.cuenta.armada['cierre'], a.cuenta.armada['atr_abs']
    r.barrer(libro(cierre + (L.extension_max_atr + 0.5) * atr, m=m), m.ahora())
    assert not ordenes(store)
    r.barrer(libro(cierre, m=m), m.ahora())
    assert len(ordenes(store)) == 1


def test_filtro_tecnico_en_vivo_espera_a_que_el_precio_cruce_sma20(store):
    modelo = Modelo()
    modelo.filtro = 'sma20'
    m, a, r = preparar(store, modelo=modelo)
    sma20 = a.cuenta.armada['sma20']
    r.barrer(libro(sma20 * 0.99, m=m), m.ahora())
    assert not ordenes(store)
    assert not next(c for c in r.radar[SYM]['condiciones'] if c['id'] == 'filtro')['cumple']
    r.barrer(libro(sma20 * 1.0005, m=m), m.ahora())
    assert len(ordenes(store)) == 1


def test_filtro_minimo_se_revisa_en_vivo_aunque_la_compra_se_armara_sin_filtro(store):
    """Decisión de Alex (2026-11-13): si la regla de VA no trae filtro, el reflejo exige el de config/riesgo.json."""
    m, a, r = preparar(store, limites=replace(L, filtro_minimo='sma20'))  # el modelo de prueba arma con «ninguno», como antes del cambio
    sma20 = a.cuenta.armada['sma20']
    r.barrer(libro(sma20 * 0.99, m=m), m.ahora())
    filtro = next(c for c in r.radar[SYM]['condiciones'] if c['id'] == 'filtro')
    assert not ordenes(store) and not filtro['cumple'] and f'SMA20 {sma20:g}' in filtro['detalle']
    r.barrer(libro(sma20 * 1.0005, m=m), m.ahora())
    assert len(ordenes(store)) == 1


def test_dato_atrasado_no_opera_y_se_informa(store):
    m, a, r = preparar(store)
    viejo = m.ahora() - (L.edad_precio_max_s + 1) * 1000
    r.barrer(libro(a.cuenta.armada['cierre'], ts=viejo), m.ahora())
    assert not ordenes(store) and r.radar[SYM]['estado'] == 'dato_atrasado'


def test_activo_ausente_del_libro_no_detiene_a_los_demas(store):
    m, a, r = preparar(store)
    r.barrer({}, m.ahora())
    assert r.radar[SYM]['estado'] == 'dato_atrasado'
    r.barrer(libro(a.cuenta.armada['cierre'], m=m), m.ahora())
    assert len(ordenes(store)) == 1


def test_la_compra_armada_expira_al_terminar_su_dia(store):
    m, a, r = preparar(store)
    cierre = a.cuenta.armada['cierre']
    despues = a.cuenta.armada['expira_ms'] + 1
    r.barrer(libro(cierre, ts=despues), despues)
    assert not ordenes(store) and r.radar[SYM]['estado'] == 'sin_senal'


def en_posicion(store, **kw):
    m, a, r = preparar(store, **kw)
    r.barrer(libro(a.cuenta.armada['cierre'], m=m), m.ahora())
    return m, a, r


def test_stop_se_ejecuta_en_el_segundo_que_lo_toca_y_no_recompra(store):
    m, a, r = en_posicion(store)
    stop = a.cuenta.stop
    r.barrer(libro(stop * 0.995, spread_bps=0, m=m), m.ahora())
    ventas = [o for o in ordenes(store) if o['lado'] == 'vender']
    assert len(ventas) == 1 and ventas[0]['motivo'] == 'stop' and ventas[0]['precio'] == pytest.approx(stop * 0.995)
    assert a.cuenta.cantidad == 0
    r.barrer(libro(stop * 1.2, m=m), m.ahora())
    assert len(ordenes(store)) == 2  # compra y venta; no vuelve a entrar sin una decisión nueva


def test_objetivo_se_ejecuta_en_el_segundo_que_lo_toca(store):
    m, a, r = en_posicion(store)
    objetivo = a.cuenta.objetivo
    r.barrer(libro(objetivo * 1.001, spread_bps=0, m=m), m.ahora())
    venta = [o for o in ordenes(store) if o['lado'] == 'vender'][0]
    assert venta['motivo'] == 'objetivo' and a.cuenta.cantidad == 0 and venta['resultado'] > 0


def test_stop_movil_solo_sube_y_se_guarda(store, tmp_path):
    m, a, r = en_posicion(store)
    stop0 = a.cuenta.stop
    alto = a.cuenta.precio_medio + 2 * a.cuenta.atr_abs
    r.barrer(libro(alto, spread_bps=0, m=m), m.ahora())
    stop1 = a.cuenta.stop
    assert stop1 > stop0
    r.barrer(libro(a.cuenta.precio_medio + 0.5 * a.cuenta.atr_abs, spread_bps=0, m=m), m.ahora())  # baja, sin tocar el stop
    assert a.cuenta.stop == stop1
    assert Store(tmp_path / 'r.sqlite3').cargar_cuenta(f'live:{SYM}').stop == stop1


@pytest.mark.parametrize('accion', ['detener', 'pausar'])
def test_detenido_o_en_pausa_manual_no_abre_ni_cierra(store, accion):
    m, a, r = en_posicion(store)
    getattr(a, accion)()
    r.barrer(libro(a.cuenta.stop * 0.5, spread_bps=0, m=m), m.ahora())
    assert a.cuenta.cantidad > 0 and len(ordenes(store)) == 1


def test_detener_con_compra_armada_no_compra(store):
    m, a, r = preparar(store)
    a.detener()
    r.barrer(libro(a.cuenta.armada['cierre'], m=m), m.ahora())
    assert not ordenes(store)


def test_en_pausa_por_fallo_los_stops_siguen_protegiendo_pero_no_abre(store):
    m, a, r = en_posicion(store)
    a._fallo('llm', RuntimeError('Ollama detenido'))
    assert a.estado == 'pausado' and a.por_fallo
    r.barrer(libro(a.cuenta.stop * 0.9, spread_bps=0, m=m), m.ahora())
    assert a.cuenta.cantidad == 0


def test_en_pausa_por_fallo_no_abre_posiciones(store):
    m, a, r = preparar(store)
    a._fallo('llm', RuntimeError('Ollama detenido'))
    r.barrer(libro(a.cuenta.armada['cierre'], m=m), m.ahora())
    assert not ordenes(store)


def test_el_bloqueo_de_la_cartera_impide_abrir_pero_no_cerrar(store):
    m, a, r = preparar(store)
    r.bloqueo_entradas = 'Pérdida diaria de la cartera alcanzada.'
    cierre = a.cuenta.armada['cierre']
    r.barrer(libro(cierre, m=m), m.ahora())
    assert not ordenes(store)
    assert 'cartera' in next(c for c in r.radar[SYM]['condiciones'] if c['id'] == 'riesgo')['detalle']
    r.bloqueo_entradas = None
    r.barrer(libro(cierre, m=m), m.ahora())
    assert len(ordenes(store)) == 1
    r.bloqueo_entradas = 'Pérdida diaria de la cartera alcanzada.'
    r.barrer(libro(a.cuenta.stop * 0.9, spread_bps=0, m=m), m.ahora())
    assert a.cuenta.cantidad == 0


def test_compra_rechazada_por_el_simulador_se_registra_una_sola_vez(store):
    pobre = Limites(**{**L.__dict__, 'capital_inicial': 0.5})
    m, a, r = preparar(store, limites=pobre)
    cierre = a.cuenta.armada['cierre']
    for _ in range(3):
        r.barrer(libro(cierre, m=m), m.ahora())
    rechazos = ordenes(store, 'rechazada')
    assert len(rechazos) == 1 and 'mínimo' in rechazos[0]['motivo']
    assert a.cuenta.armada is None


def test_compra_armada_sobrevive_a_un_reinicio(store, tmp_path):
    m, a, _ = preparar(store)
    cierre = a.cuenta.armada['cierre']
    otro = Store(tmp_path / 'r.sqlite3')
    b = Agente(store=otro, mercado=m, modelo=Modelo(), proponente=Proponente(), limites=L, run_id=f'live:{SYM}', ahora=m.ahora, modo_reflejo=True)
    assert b.cuenta.armada is not None
    Reflejo({SYM: b}).barrer(libro(cierre, m=m), m.ahora())
    assert b.cuenta.cantidad > 0 and len(ordenes(otro)) == 1


def test_radar_cuenta_condiciones_cumplidas_y_mide_la_latencia(store):
    m, a, r = preparar(store)
    cierre = a.cuenta.armada['cierre']
    r.barrer(libro(cierre, spread_bps=200, m=m), m.ahora())
    fila = r.radar[SYM]
    assert len(fila['condiciones']) == 5 and fila['cumplidas'] == 4
    assert fila['pronostico'] == 0.01 and fila['spread_bps'] == pytest.approx(200, rel=1e-3)
    e = r.estadisticas()
    assert e['barridos'] == 1 and e['latencia_ms'] >= 0 and e['p99_ms'] >= 0 and e['activos'] == 1


def test_fallo_al_guardar_no_deja_la_cuenta_cambiada(store, monkeypatch):
    m, a, r = preparar(store)
    cierre = a.cuenta.armada['cierre']
    monkeypatch.setattr(store, 'guardar_orden', lambda *x, **k: (_ for _ in ()).throw(OSError('disco lleno')))
    with pytest.raises(OSError):
        r.barrer(libro(cierre, m=m), m.ahora())
    monkeypatch.undo()
    assert a.cuenta.cantidad == 0 and a.cuenta.armada is not None
    assert store.cargar_cuenta(f'live:{SYM}').cantidad == 0
    assert Cuenta(efectivo=1.0).armada is None


def test_con_modelo_real_el_filtro_tecnico_se_revisa_en_vivo_no_solo_al_cierre(store):
    from bot import model
    contrato = dict(version='v', tipo='cero', lookback=20, variables=['ret'], umbral=-1.0, filtro='sma20', escalador={'media': [0.0], 'desv': [1.0]}, y_media=0.0, y_desv=1.0, miembros=[])
    m = Mercado()
    # La última vela cierra muy por debajo de su SMA20: al cierre el filtro no se cumple.
    fila = m.filas[m.n - 1]
    fila[1], fila[2], fila[3], fila[4] = '50', '51', '49', '50'
    a = Agente(store=store, mercado=m, modelo=model.Modelo(contrato, {}), proponente=Proponente('comprar'), limites=L, run_id=f'live:{SYM}', ahora=m.ahora, modo_reflejo=True)
    a.iniciar()
    a.tick()
    assert a.cuenta.armada is not None and a.cuenta.armada['cierre'] < a.cuenta.armada['sma20']
    r = Reflejo({SYM: a})
    r.barrer(libro(55.0, m=m), m.ahora())
    assert not ordenes(store)
    assert not next(c for c in r.radar[SYM]['condiciones'] if c['id'] == 'filtro')['cumple']


def test_stop_de_la_vela_no_se_aplica_si_el_reflejo_ya_la_vigilo(store):
    m, a, r = en_posicion(store)
    a.reflejo_desde_ms = m.filas[m.n][0] - 1  # el reflejo vigiló toda la vela siguiente
    stop = a.cuenta.stop
    fila = m.filas[m.n]
    fila[1], fila[2], fila[3], fila[4] = str(stop * 1.02), str(stop * 1.03), str(stop * 0.5), str(stop * 1.01)  # mínimo anterior a la entrada o ya atendido
    a.entrada = None
    m.avanzar()
    a.proponente = Proponente('mantener')
    a.tick()
    assert a.cuenta.cantidad > 0


def test_stop_de_la_vela_si_se_aplica_cuando_el_reflejo_no_estuvo_vigilando(store):
    m, a, r = en_posicion(store)
    m.avanzar()
    a.reflejo_desde_ms = m.filas[m.n - 1][0] + 1  # el reflejo volvió cuando la vela ya había abierto
    a.cuenta.entrada_ms = m.filas[m.n - 1][0] - 1
    stop = a.cuenta.stop
    fila = m.filas[m.n - 1]
    fila[1], fila[2], fila[3], fila[4] = str(stop * 1.02), str(stop * 1.03), str(stop * 0.5), str(stop * 1.01)
    a.proponente = Proponente('mantener')
    a.tick()
    assert a.cuenta.cantidad == 0
    assert [o for o in ordenes(store) if o['motivo'] == 'stop']


class MercadoConLibro(Mercado):
    """Mercado falso que además da el libro de órdenes visible."""

    def __init__(self):
        super().__init__()
        self.asks, self.bids, self.falla = [], [], False

    def profundidad(self, simbolo, limite=50):
        self.consultas = getattr(self, 'consultas', 0) + 1
        if self.falla:
            raise mexc.MexcUnavailable('MEXC no respondió en /api/v3/depth.')
        return dict(asks=self.asks, bids=self.bids)


def test_si_recorrer_el_libro_cuesta_demasiado_espera_sin_comprar(store):
    m, a, r = preparar(store, mercado=MercadoConLibro())
    cierre = a.cuenta.armada['cierre']
    m.asks = [(cierre, 0.000001), (cierre * 1.05, 1e6)]
    r.barrer(libro(cierre, m=m), m.ahora())
    fila = r.radar[SYM]
    spread = next(x for x in fila['condiciones'] if x['id'] == 'spread')
    assert not ordenes(store) and a.cuenta.armada is not None and fila['estado'] == 'armada'
    assert not spread['cumple'] and 'libro' in spread['detalle'] and fila['cumplidas'] == len(fila['condiciones']) - 1


def test_con_libro_profundo_compra_al_precio_medio_de_la_orden(store):
    m, a, r = preparar(store, mercado=MercadoConLibro())
    cierre = a.cuenta.armada['cierre']
    m.asks = [(cierre, 0.000001), (cierre * 1.001, 1e6)]
    r.barrer(libro(cierre, m=m), m.ahora())
    compra = ordenes(store)[0]
    assert compra['lado'] == 'comprar' and cierre < compra['precio'] <= cierre * 1.001


def test_sin_libro_no_compra_y_lo_vuelve_a_intentar(store):
    m, a, r = preparar(store, mercado=MercadoConLibro())
    cierre = a.cuenta.armada['cierre']
    m.falla = True
    r.barrer(libro(cierre, m=m), m.ahora())
    assert not ordenes(store) and a.cuenta.armada is not None
    m.falla, m.asks = False, [(cierre, 1e6)]
    r.barrer(libro(cierre, ts=m.ahora() + 6000), m.ahora() + 6000)  # vuelve a mirar el libro pasados unos segundos
    assert len(ordenes(store)) == 1


def test_la_venta_por_stop_recorre_las_compras_del_libro(store):
    m, a, r = preparar(store, mercado=MercadoConLibro())
    cierre = a.cuenta.armada['cierre']
    m.asks = [(cierre, 1e6)]
    r.barrer(libro(cierre, m=m), m.ahora())
    bid = a.cuenta.stop * 0.995
    m.bids = [(bid, a.cuenta.cantidad / 2), (bid * 0.98, 1e6)]
    r.barrer(libro(bid, spread_bps=0, m=m), m.ahora())
    venta = [o for o in ordenes(store) if o['lado'] == 'vender'][0]
    assert venta['motivo'] == 'stop' and venta['precio'] == pytest.approx(bid * 0.99)


def test_si_falla_el_libro_la_venta_por_stop_sale_igual_al_mejor_precio(store):
    m, a, r = preparar(store, mercado=MercadoConLibro())
    cierre = a.cuenta.armada['cierre']
    m.asks = [(cierre, 1e6)]
    r.barrer(libro(cierre, m=m), m.ahora())
    bid = a.cuenta.stop * 0.995
    m.falla = True
    r.barrer(libro(bid, spread_bps=0, m=m), m.ahora())
    venta = [o for o in ordenes(store) if o['lado'] == 'vender'][0]
    assert venta['precio'] == pytest.approx(bid) and a.cuenta.cantidad == 0


def test_mientras_espera_por_el_libro_no_lo_consulta_cada_segundo(store):
    m, a, r = preparar(store, mercado=MercadoConLibro())
    cierre = a.cuenta.armada['cierre']
    m.asks = [(cierre, 0.000001), (cierre * 1.05, 1e6)]
    for segundo in range(4):
        r.barrer(libro(cierre, m=m), m.ahora() + segundo * 1000)
    assert m.consultas == 1 and not ordenes(store)
    detalle = next(x for x in r.radar[SYM]['condiciones'] if x['id'] == 'spread')['detalle']
    assert 'libro leído hace 3 s' in detalle  # el motivo guardado dice qué tan viejo es el libro que lo produjo
    r.barrer(libro(cierre, ts=m.ahora() + 6000), m.ahora() + 6000)
    assert m.consultas == 2


def test_la_compra_que_expira_sin_ejecutarse_queda_registrada_con_lo_que_falto(store):
    """Evidencia para validar las reglas en vivo: qué condición impidió comprar ese día."""
    m, a, r = preparar(store)
    cierre = a.cuenta.armada['cierre']
    r.barrer(libro(cierre, spread_bps=200, m=m), m.ahora())
    despues = a.cuenta.armada['expira_ms'] + 1000
    r.barrer(libro(cierre, ts=despues), despues)
    expiradas = ordenes(store, 'expirada')
    assert len(expiradas) == 1 and 'Spread' in expiradas[0]['motivo'] and expiradas[0]['vela'] is not None
    assert a.cuenta.armada is None and not ordenes(store)



def test_cada_orden_dice_que_supuesto_de_costos_se_aplico(store):
    m, a, r = preparar(store, mercado=MercadoConLibro())
    cierre = a.cuenta.armada['cierre']
    m.asks = [(cierre, 1e6)]
    r.barrer(libro(cierre, m=m), m.ahora())
    m.falla = True
    r.barrer(libro(a.cuenta.stop * 0.995, spread_bps=0, m=m), m.ahora())
    compra, venta = ordenes(store)
    assert 'libro' in compra['modelo_costos'] and 'sin libro' in venta['modelo_costos']


def test_vigilar_una_posicion_sin_stop_ni_objetivo_no_consulta_el_libro(store):
    m, a, r = preparar(store, mercado=MercadoConLibro())
    cierre = a.cuenta.armada['cierre']
    m.asks = [(cierre, 1e6)]
    r.barrer(libro(cierre, m=m), m.ahora())
    assert a.cuenta.cantidad > 0
    antes = m.consultas
    for segundo in range(1, 6):
        r.barrer(libro(cierre, m=m), m.ahora() + segundo * 1000)
    assert m.consultas == antes  # el libro solo se lee para vender de verdad: 11 posiciones no deben costar 11 consultas por segundo


def test_la_compra_cobra_la_comision_real_del_par(store):
    m, a, r = preparar(store, limites=replace(L, comision=0.0, comision_por_par=((SYM, 0.001),)))
    r.barrer(libro(a.cuenta.armada['cierre'], m=m), m.ahora())
    compra = ordenes(store)[0]
    assert compra['comision'] == pytest.approx(compra['cantidad'] * compra['precio'] * 0.001)
    assert 'comisión 0.10%' in compra['modelo_costos']


ESPERA = replace(L, espera_max_min=30.0, comision_espera=0.0, comision=0.001)


@pytest.mark.parametrize('fallo', ['spread', 'filtro'])
def test_cruzar_limite_no_omite_los_demas_criterios(store, fallo):
    m, a, r = preparar(store, limites=ESPERA)
    r.barrer(libro(a.cuenta.armada['cierre'], spread_bps=10, m=m), m.ahora())
    limite = a.cuenta.armada['limite']
    if fallo == 'filtro':
        a.cuenta.armada.update(filtro='sma20', sma20=limite * 1.01)
    r.barrer(libro(limite, spread_bps=200 if fallo == 'spread' else 10, m=m), m.ahora() + 1000)
    assert not ordenes(store)
    assert a.cuenta.cantidad == 0
    assert a.cuenta.armada['limite'] is None
    assert any(not c['cumple'] for c in r.radar[SYM]['condiciones'])


def test_con_espera_la_compra_queda_al_mejor_precio_de_compra_y_no_compra_al_instante(store):
    m, a, r = preparar(store, limites=ESPERA)
    cierre = a.cuenta.armada['cierre']
    r.barrer(libro(cierre, spread_bps=10, m=m), m.ahora())
    assert not ordenes(store)
    assert a.cuenta.armada['limite'] == pytest.approx(cierre * 0.999)
    assert r.radar[SYM]['espera']['precio'] == pytest.approx(cierre * 0.999)


def test_la_compra_en_espera_se_llena_si_el_precio_la_cruza_y_no_paga_comision(store):
    m, a, r = preparar(store, limites=ESPERA)
    r.barrer(libro(a.cuenta.armada['cierre'], spread_bps=10, m=m), m.ahora())
    limite = a.cuenta.armada['limite']
    r.barrer(libro(limite, spread_bps=10, m=m), m.ahora() + 1000)
    compra = ordenes(store)[0]
    assert compra['precio'] == pytest.approx(limite) and compra['comision'] == 0
    assert 'orden en espera' in compra['modelo_costos']


def test_si_el_precio_no_baja_al_terminar_la_espera_compra_al_instante(store):
    m, a, r = preparar(store, limites=ESPERA)
    cierre = a.cuenta.armada['cierre']
    r.barrer(libro(cierre, spread_bps=10, m=m), m.ahora())
    despues = m.ahora() + 31 * 60_000
    r.barrer(libro(cierre, spread_bps=10, ts=despues), despues)
    compra = ordenes(store)[0]
    assert compra['precio'] == pytest.approx(cierre) and compra['comision'] > 0


def test_si_deja_de_cumplirse_una_condicion_la_orden_en_espera_se_cancela(store):
    m, a, r = preparar(store, limites=ESPERA)
    cierre, atr = a.cuenta.armada['cierre'], a.cuenta.armada['atr_abs']
    r.barrer(libro(cierre, spread_bps=10, m=m), m.ahora())
    r.barrer(libro(cierre + 2 * atr, spread_bps=10, m=m), m.ahora() + 1000)
    assert a.cuenta.armada['limite'] is None and not ordenes(store)


def test_el_objetivo_vende_en_espera_a_su_precio_sin_comision(store):
    m, a, r = en_posicion(store)
    a.limites = replace(a.limites, espera_max_min=30.0, comision_espera=0.0, comision=0.001)
    objetivo = a.cuenta.objetivo
    r.barrer(libro(objetivo * 1.002, spread_bps=0, m=m), m.ahora())
    venta = [o for o in ordenes(store) if o['lado'] == 'vender'][0]
    assert venta['motivo'] == 'objetivo' and venta['precio'] == pytest.approx(objetivo) and venta['comision'] == 0


def test_el_stop_no_espera_vende_al_instante_con_comision(store):
    m, a, r = en_posicion(store)
    a.limites = replace(a.limites, espera_max_min=30.0, comision_espera=0.0, comision=0.001)
    r.barrer(libro(a.cuenta.stop * 0.995, spread_bps=0, m=m), m.ahora())
    venta = [o for o in ordenes(store) if o['lado'] == 'vender'][0]
    assert venta['motivo'] == 'stop' and venta['comision'] > 0


# Sin compra armada, el radar muestra las mismas condiciones solo como información: qué tan cerca está cada activo.
def cierre_del_dia(store):
    return store.decisiones(f'live:{SYM}')[-1]['precio']


def test_sin_compra_armada_muestra_que_condiciones_ya_cumple_y_cuales_faltan(store):
    m, a, r = preparar(store, proponente=Proponente('mantener'))
    r.barrer(libro(cierre_del_dia(store), m=m), m.ahora())
    fila = r.radar[SYM]
    assert fila['estado'] == 'sin_senal'
    assert [c['id'] for c in fila['condiciones']] == ['senal', 'filtro', 'spread', 'extension', 'autorizacion']
    assert all(isinstance(c['cumple'], bool) and c['detalle'] for c in fila['condiciones'])
    assert fila['cumplidas'] == 4
    autorizacion = fila['condiciones'][-1]
    assert not autorizacion['cumple'] and 'mantener' in autorizacion['detalle']


def test_sin_senal_del_modelo_la_condicion_dice_el_pronostico_y_el_umbral(store):
    m, a, r = preparar(store, modelo=Modelo(valor=-0.002, senal=False), proponente=Proponente('mantener'))
    r.barrer(libro(cierre_del_dia(store), m=m), m.ahora())
    senal = next(c for c in r.radar[SYM]['condiciones'] if c['id'] == 'senal')
    assert not senal['cumple'] and '-0.200 %' in senal['detalle'] and '+0.100 %' in senal['detalle']


def test_las_condiciones_informativas_muestran_el_filtro_minimo_con_su_valor(store):
    """La decisión guardada dice «ninguno», como las de antes del cambio: el radar ya muestra la SMA20 y si se cumple."""
    m, a, r = preparar(store, limites=replace(L, filtro_minimo='sma20'), proponente=Proponente('mantener'))
    cierre, sma20 = cierre_del_dia(store), a.contexto_vela['sma20']
    r.barrer(libro(cierre, m=m), m.ahora())
    filtro = next(c for c in r.radar[SYM]['condiciones'] if c['id'] == 'filtro')
    assert f'Precio {precio_legible(cierre)} contra SMA20 {precio_legible(sma20)}' in filtro['detalle'] and filtro['cumple'] == (cierre > sma20)


def test_precio_legible_como_en_el_panel():
    """Miles separados, sin notación científica y los decimales que pide la magnitud, como `precio` del panel."""
    assert precio_legible(60672.1) == '60,672.10'
    assert precio_legible(1.237) == '1.237'
    assert precio_legible(0.2436) == '0.2436'
    assert precio_legible(0.00000355) == '0.00000355'


def test_las_condiciones_informativas_no_arman_ni_compran_ni_leen_el_libro(store):
    m, a, r = preparar(store, mercado=MercadoConLibro(), proponente=Proponente('mantener'))
    cierre = cierre_del_dia(store)
    m.asks = [(cierre, 1e6)]
    for segundo in range(3):
        r.barrer(libro(cierre, ts=m.ahora() + segundo * 1000), m.ahora() + segundo * 1000)
    assert r.radar[SYM]['cumplidas'] == 4
    assert not store.ordenes(f'live:{SYM}') and a.cuenta.armada is None and a.cuenta.cantidad == 0
    assert getattr(m, 'consultas', 0) == 0


def test_fila_en_posicion_no_trae_condiciones_de_compra(store):
    m, a, r = en_posicion(store)
    r.barrer(libro(a.cuenta.precio_medio, m=m), m.ahora())
    fila = r.radar[SYM]
    assert fila['estado'] == 'en_posicion' and fila['condiciones'] == [] and fila['cumplidas'] == 0


def test_las_condiciones_informativas_sobreviven_a_un_reinicio(store, tmp_path):
    m, a, r = preparar(store, proponente=Proponente('mantener'))
    precio = libro(cierre_del_dia(store), m=m)
    r.barrer(precio, m.ahora())
    otro = Agente(store=Store(tmp_path / 'r.sqlite3'), mercado=m, modelo=Modelo(), proponente=Proponente('mantener'), limites=L, run_id=f'live:{SYM}',
                  ahora=m.ahora, modo_reflejo=True)
    nuevo = Reflejo({SYM: otro})
    nuevo.barrer(precio, m.ahora())
    assert len(nuevo.radar[SYM]['condiciones']) == 5 and nuevo.radar[SYM]['condiciones'] == r.radar[SYM]['condiciones']


def mercado_que_cae():
    m = Mercado(n=100)
    m.filas = rows([100 * 0.99 ** i for i in range(140)])
    return m


@pytest.mark.parametrize('mercado, texto', [(mercado_que_cae, 'al stop'), (Mercado, 'válido')])  # 60 velas no alcanzan para el repaso
def test_el_repaso_de_la_maquina_del_tiempo_se_muestra_si_existe(store, mercado, texto):
    m, a, r = preparar(store, mercado=mercado(), limites=replace(L, maquina_tiempo=True))
    assert a.cuenta.armada is None
    r.barrer(libro(cierre_del_dia(store), m=m), m.ahora())
    condiciones = {c['id']: c for c in r.radar[SYM]['condiciones']}
    assert not condiciones['maquina']['cumple'] and texto in condiciones['maquina']['detalle']
    assert 'Máquina del tiempo' in condiciones['autorizacion']['detalle']
