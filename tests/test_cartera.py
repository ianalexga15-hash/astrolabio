"""La cartera organiza hasta 40 activos a la vez, con un cupo de capital igual para cada uno."""
import pytest

from bot import llm, mexc
from bot.cartera import Cartera
from bot.store import Store
from tests.helpers import DAY, START, random_walk, rows
from tests.test_agent import L, Modelo, Proponente

SIMBOLOS = [f'A{i}USDT' for i in range(40)]


class MercadoVarios:
    def __init__(self, simbolos=SIMBOLOS, n=60):
        self.filas = {s: rows(random_walk(n + 20, seed=i + 1)) for i, s in enumerate(simbolos)}
        self.n = n
        self.fallan = set()

    def ahora(self):
        return START + self.n * DAY + 60_000

    def closed_candles(self, simbolo, limit, now_ms):
        if simbolo in self.fallan:
            raise mexc.MexcUnavailable(f'{simbolo} no responde')
        return [f for f in self.filas[simbolo][:self.n] if f[6] <= now_ms][-limit:]

    def filters(self, simbolo):
        return dict(paso_cantidad=0.000001, minimo_quote=1.0, maker=0.0, taker=0.0)

    def ticker(self, simbolo):
        return float(self.filas[simbolo][self.n][1])

    def libro(self, simbolos):
        return {s: dict(bid=self.ticker(s), ask=self.ticker(s), ts_ms=self.ahora()) for s in simbolos}


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'c.sqlite3')


def crear(store, simbolos=SIMBOLOS, proponente=None, modelos=None):
    m = MercadoVarios(simbolos)
    c = Cartera(store=store, mercado=m, modelos=modelos or {s: Modelo() for s in simbolos}, proponente=proponente or Proponente('comprar'), limites=L, ahora=m.ahora, espera_reintento_s=0)
    return m, c


def test_reparte_el_capital_en_cupos_iguales(store):
    _, c = crear(store)
    assert len(c.agentes) == 40
    assert all(a.limites.capital_inicial == pytest.approx(50_000 / 40) for a in c.agentes.values())
    assert {a.limites.simbolo for a in c.agentes.values()} == set(SIMBOLOS)
    assert c.resumen()['patrimonio'] == pytest.approx(50_000)


def test_cada_activo_tiene_su_propia_cuenta_y_corrida(store):
    _, c = crear(store)
    assert c.agentes['A1USDT'].run_id == 'live:A1USDT'
    assert c.agentes['A1USDT'].cuenta is not c.agentes['A2USDT'].cuenta


def test_activos_sin_modelo_quedan_fuera_y_se_informan(store):
    simbolos = ['A1USDT', 'A2USDT']
    _, c = crear(store, simbolos, modelos={'A1USDT': Modelo(), 'A2USDT': None})
    assert list(c.agentes) == ['A1USDT'] and c.sin_modelo == ['A2USDT']


def test_cartera_vacia_se_informa(store):
    with pytest.raises(ValueError, match='ningún activo'):
        Cartera(store=store, mercado=MercadoVarios([]), modelos={}, proponente=Proponente(), limites=L, ahora=lambda: 0)


def test_controles_aplican_a_todos_los_activos(store):
    _, c = crear(store, SIMBOLOS[:3])
    c.iniciar()
    assert c.estado() == 'activo' and all(a.estado == 'activo' for a in c.agentes.values())
    c.pausar()
    assert c.estado() == 'pausado'
    c.detener()
    assert c.estado() == 'detenido'


def test_ciclo_diario_procesa_todos_y_arma_compras(store):
    _, c = crear(store, SIMBOLOS[:5])
    c.iniciar()
    r = c.ciclo()
    assert r['resultado'] == 'procesada' and r['procesadas'] == 5
    assert all(a.cuenta.armada for a in c.agentes.values())
    assert c.ciclo()['resultado'] == 'sin_velas_nuevas'


def test_fallo_de_un_activo_no_detiene_a_los_demas(store):
    m, c = crear(store, SIMBOLOS[:3])
    m.fallan.add(SIMBOLOS[1])
    c.iniciar()
    r = c.ciclo()
    assert r['procesadas'] == 2 and r['fallos'] == 1
    assert c.agentes[SIMBOLOS[1]].estado == 'pausado'
    assert c.agentes[SIMBOLOS[0]].estado == 'activo'
    alertas = c.alertas()
    assert [a['simbolo'] for a in alertas] == [SIMBOLOS[1]] and 'no responde' in alertas[0]['motivo']
    assert c.estado() == 'activo'


def test_error_inesperado_de_un_activo_lo_pausa_y_registra(store):
    class Roto(Proponente):
        def proponer(self, contexto, herramientas):
            raise KeyError('inesperado')

    _, c = crear(store, SIMBOLOS[:2], proponente=Roto())
    c.iniciar()
    c.ciclo()
    assert all(a.estado == 'pausado' for a in c.agentes.values())
    assert store.errores()[-1]['etapa'] == 'agente'


def test_ollama_detenido_pausa_decisiones_pero_el_reflejo_sigue(store):
    m, c = crear(store, SIMBOLOS[:2], proponente=Proponente(error=llm.LLMNoDisponible('Ollama detenido')))
    c.iniciar()
    assert c.ciclo()['fallos'] == 2
    assert 'Ollama' in c.alertas()[0]['motivo']
    assert c.barrer()['barridos'] == 1


def test_barrer_revisa_todo_con_una_sola_consulta_al_libro(store):
    m, c = crear(store)
    llamadas = []
    original = m.libro

    def contar(simbolos):
        llamadas.append(len(simbolos))
        return original(simbolos)

    m.libro = contar
    c.iniciar()
    for a in c.agentes.values():
        a.tick()
    c.barrer()
    assert llamadas == [40]
    assert len(c.reflejo.radar) == 40
    assert sum(a.cuenta.cantidad > 0 for a in c.agentes.values()) == 40
    assert c.resumen()['posiciones'] == 40


def test_posiciones_y_exposicion_se_suman_en_el_resumen(store):
    m, c = crear(store, SIMBOLOS[:4])
    c.iniciar()
    c.ciclo()
    c.barrer()
    r = c.resumen()
    assert r['posiciones'] == 4 and 0 < r['exposicion'] <= L.exposicion_max
    assert r['patrimonio'] == pytest.approx(50_000, rel=1e-3)


def test_perdida_diaria_de_la_cartera_bloquea_entradas(store):
    m, c = crear(store, SIMBOLOS[:2])
    c.iniciar()
    c.ciclo()
    for a in c.agentes.values():
        a.cuenta.efectivo *= 0.93  # caída mayor al límite diario de 5 % y menor a la caída máxima de 25 %
    c.barrer()
    assert c.reflejo.bloqueo_entradas and 'pérdida diaria' in c.reflejo.bloqueo_entradas
    assert not store.ordenes('live:' + SIMBOLOS[0])


def test_caida_maxima_de_la_cartera_bloquea_todo_hasta_intervencion(store):
    m, c = crear(store, SIMBOLOS[:2])
    c.iniciar()
    c.ciclo()
    for a in c.agentes.values():
        a.cuenta.efectivo *= 0.5
    c.barrer()
    assert c.estado() == 'bloqueado' and all(a.estado == 'bloqueado' for a in c.agentes.values())
    assert 'caída máxima' in c.agentes[SIMBOLOS[0]].motivo


def test_maximo_de_patrimonio_de_la_cartera_sobrevive_al_reinicio(store, tmp_path):
    m, c = crear(store, SIMBOLOS[:2])
    c.barrer()
    otro = Store(tmp_path / 'c.sqlite3')
    c2 = Cartera(store=otro, mercado=m, modelos={s: Modelo() for s in SIMBOLOS[:2]}, proponente=Proponente(), limites=L, ahora=m.ahora)
    assert c2.maximo == pytest.approx(50_000)


def test_cerrar_todo_es_explicito_y_cierra_solo_lo_abierto(store):
    m, c = crear(store, SIMBOLOS[:3])
    c.iniciar()
    c.ciclo()
    c.barrer()
    c.agentes[SIMBOLOS[0]].cerrar_posicion()
    assert c.cerrar_posicion() == 2
    assert c.resumen()['posiciones'] == 0
    with pytest.raises(ValueError, match='posición'):
        c.cerrar_posicion()


def test_cerrar_todo_sigue_con_los_demas_si_mexc_no_da_el_precio_de_uno(store):
    m, c = crear(store, SIMBOLOS[:3])
    c.iniciar()
    c.ciclo()
    c.barrer()
    precio = m.ticker

    def ticker(simbolo):
        if simbolo == SIMBOLOS[1]:
            raise mexc.MexcUnavailable('MEXC no respondió')
        return precio(simbolo)

    m.ticker = ticker
    with pytest.raises(ValueError, match=f'Se cerraron 2.*{SIMBOLOS[1]}'):
        c.cerrar_posicion()
    assert [c.agentes[s].cuenta.cantidad > 0 for s in SIMBOLOS[:3]] == [False, True, False]


def test_cerrar_un_solo_activo(store):
    m, c = crear(store, SIMBOLOS[:2])
    c.iniciar()
    c.ciclo()
    c.barrer()
    assert c.cerrar_posicion(SIMBOLOS[0]) == 1
    assert c.agentes[SIMBOLOS[0]].cuenta.cantidad == 0 and c.agentes[SIMBOLOS[1]].cuenta.cantidad > 0


def test_cambiar_limites_recalcula_cupos(store):
    _, c = crear(store, SIMBOLOS[:2])
    c.aplicar_limites(L.__class__(**{**L.__dict__, 'exposicion_max': 0.5, 'capital_inicial': 50_000.0}))
    assert all(a.limites.exposicion_max == 0.5 and a.limites.simbolo in SIMBOLOS[:2] for a in c.agentes.values())


def test_error_al_consultar_el_libro_no_detiene_y_se_informa(store):
    m, c = crear(store, SIMBOLOS[:2])

    def falla(simbolos):
        raise mexc.MexcUnavailable('sin red')

    m.libro = falla
    c.iniciar()
    assert c.barrer()['error'] == 'sin red'
    assert c.error_libro == 'sin red'
    m.libro = lambda simbolos: {}
    c.barrer()
    assert c.error_libro is None


def test_un_hueco_largo_sin_precios_hace_revisar_la_vela_con_su_minimo(store):
    m, c = crear(store, SIMBOLOS[:1])
    c.barrer()
    antes = c.agentes[SIMBOLOS[0]].reflejo_desde_ms
    ahora = m.ahora()
    c.ahora = lambda: ahora + 120_000
    c.barrer()
    assert c.agentes[SIMBOLOS[0]].reflejo_desde_ms == ahora + 120_000 > antes


def test_tras_reiniciar_se_sabe_desde_cuando_vigila_el_reflejo(store):
    m, c = crear(store, SIMBOLOS[:1])
    assert c.agentes[SIMBOLOS[0]].reflejo_desde_ms == m.ahora()


def test_cambiar_la_lista_de_activos_ajusta_cupos_de_cuentas_sin_actividad(store):
    Cartera(store=store, mercado=MercadoVarios(['A1USDT']), modelos={'A1USDT': Modelo()}, proponente=Proponente(), limites=L, ahora=lambda: 0)
    assert store.cargar_cuenta('live:A1USDT').efectivo == 50_000
    m = MercadoVarios(SIMBOLOS[:40])
    c = Cartera(store=store, mercado=m, modelos={s: Modelo() for s in SIMBOLOS[:40]}, proponente=Proponente(), limites=L, ahora=m.ahora)
    assert c.agentes['A1USDT'].cuenta.efectivo == pytest.approx(1_250)
    assert store.cargar_cuenta('live:A1USDT').efectivo == pytest.approx(1_250)
    assert c.resumen()['patrimonio'] == pytest.approx(50_000) and c.aviso_capital is None


def test_cuentas_con_actividad_no_se_tocan_al_cambiar_la_lista_y_se_avisa(store):
    m1 = MercadoVarios(['A1USDT'])
    c1 = Cartera(store=store, mercado=m1, modelos={'A1USDT': Modelo()}, proponente=Proponente('comprar'), limites=L, ahora=m1.ahora)
    c1.iniciar()
    c1.ciclo()
    c1.barrer()
    cantidad = c1.agentes['A1USDT'].cuenta.cantidad
    assert cantidad > 0
    m2 = MercadoVarios(SIMBOLOS[:3])
    c2 = Cartera(store=store, mercado=m2, modelos={s: Modelo() for s in ['A1USDT', 'A2USDT']}, proponente=Proponente(), limites=L, ahora=m2.ahora)
    assert c2.agentes['A1USDT'].cuenta.cantidad == cantidad
    assert c2.aviso_capital and 'A1USDT' in c2.aviso_capital
    assert c2.resumen()['aviso_capital'] == c2.aviso_capital


def test_reiniciar_tras_una_operacion_cerrada_no_da_aviso_falso(store):
    m, c = crear(store, ['A1USDT', 'A2USDT'])
    c.iniciar()
    c.ciclo()
    c.barrer()
    precio = m.ticker('A1USDT')
    m.ticker = lambda s: precio * 1.02
    c.cerrar_posicion('A1USDT')
    assert c.agentes['A1USDT'].cuenta.efectivo > 25_000  # el escenario necesita una ganancia realizada
    otra = Cartera(store=store, mercado=m, modelos={s: Modelo() for s in ['A1USDT', 'A2USDT']}, proponente=Proponente(), limites=L, ahora=m.ahora)
    assert otra.aviso_capital is None


def test_un_maximo_anterior_no_bloquea_si_nadie_opero(store):
    from bot.paper import Cuenta
    Cartera(store=store, mercado=MercadoVarios(['A1USDT']), modelos={'A1USDT': Modelo()}, proponente=Proponente(), limites=L, ahora=lambda: 0)
    store.guardar_cuenta('cartera', Cuenta(efectivo=98_750.0), 98_750.0)  # lo que dejó el cupo inflado
    m = MercadoVarios(SIMBOLOS[:40])
    c = Cartera(store=store, mercado=m, modelos={s: Modelo() for s in SIMBOLOS[:40]}, proponente=Proponente(), limites=L, ahora=m.ahora)
    c.iniciar()
    c.barrer()
    assert c.estado() == 'activo' and c.resumen()['caida'] == pytest.approx(0)


@pytest.mark.parametrize('capital', [100_000.0, 25_000.0])
def test_cambiar_el_capital_reparte_el_nuevo_cupo_si_nadie_opero(store, capital):
    _, c = crear(store, ['A1USDT', 'A2USDT'], proponente=Proponente())
    c.iniciar()
    c.ciclo()  # ya hay decisiones y una curva de patrimonio con el cupo anterior, pero ninguna orden
    c.detener()
    c.aplicar_limites(L.__class__(**{**L.__dict__, 'capital_inicial': capital}))
    assert store.cargar_cuenta('live:A1USDT').efectivo == pytest.approx(capital / 2)
    assert c.resumen()['patrimonio'] == pytest.approx(capital) and c.aviso_capital is None
    c.iniciar()
    c.barrer()
    assert c.estado() == 'activo' and c.reflejo.bloqueo_entradas is None and c.resumen()['rendimiento'] == pytest.approx(0)


class MercadoConLibros(MercadoVarios):
    """Libros profundos: toda compra cabe. Cuenta cuántos libros se piden."""
    consultas = 0

    def profundidad(self, simbolo, limite=50):
        self.consultas += 1
        return dict(asks=[(self.ticker(simbolo), 1e9)], bids=[(self.ticker(simbolo), 1e9)])


def test_cada_barrido_mira_pocos_libros_para_no_frenar_al_reflejo(store):
    simbolos = SIMBOLOS[:12]
    m = MercadoConLibros(simbolos)
    c = Cartera(store=store, mercado=m, modelos={s: Modelo() for s in simbolos}, proponente=Proponente('comprar'), limites=L, ahora=m.ahora)
    c.iniciar()
    c.ciclo()
    c.barrer()
    assert m.consultas == 3 and c.resumen()['posiciones'] == 3
    for _ in range(3):
        c.barrer()
    assert c.resumen()['posiciones'] == 12



def test_mide_el_barrido_completo_con_la_red_y_el_intervalo_entre_barridos(store):
    _, c = crear(store, SIMBOLOS[:3], proponente=Proponente())
    tiempos = iter([0.0, 0.25, 1.0, 1.4, 2.0, 3.6])  # inicio y fin de cada barrido, en segundos
    c.reloj = lambda: next(tiempos)
    for _ in range(3):
        c.barrer()
    r = c.medicion()
    assert r['barridos'] == 3 and r['ciclo_ms']['p50'] == pytest.approx(400.0) and r['ciclos_lentos'] == 1
    assert r['intervalo_s']['p50'] == pytest.approx(1.0) and r['intervalos_largos'] == 0
