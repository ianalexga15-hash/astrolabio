import pytest

from bot.paper import Cuenta
from bot.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'b.sqlite3')


def test_transaccion_revierte_todo_si_algo_falla(store):
    with pytest.raises(RuntimeError):
        with store.transaccion():
            store.marcar_procesada('live', 'BTCUSDT', 1, 'procesada')
            store.guardar_orden('live', None, 1, 'comprar', 'ejecutada')
            raise RuntimeError('fallo')
    assert not store.ya_procesada('live', 'BTCUSDT', 1)
    assert not store.ordenes('live')


def test_la_misma_vela_no_se_puede_marcar_dos_veces(store):
    store.marcar_procesada('live', 'BTCUSDT', 1, 'procesada')
    with pytest.raises(Exception):
        store.marcar_procesada('live', 'BTCUSDT', 1, 'procesada')


def test_cuenta_sobrevive_a_un_reinicio(tmp_path):
    a = Store(tmp_path / 'x.sqlite3')
    c = Cuenta(efectivo=10.5, cantidad=0.25, precio_medio=100.0, stop=90.0, objetivo=120.0)
    a.guardar_cuenta('live', c, 1000.0)
    b = Store(tmp_path / 'x.sqlite3')
    assert b.cargar_cuenta('live') == c
    assert b.patrimonio_maximo('live') == 1000.0


def test_el_maximo_de_patrimonio_no_baja(store):
    store.guardar_cuenta('live', Cuenta(efectivo=1.0), 1000.0)
    store.guardar_cuenta('live', Cuenta(efectivo=1.0), 900.0)
    assert store.patrimonio_maximo('live') == 1000.0


def test_estado_del_bot_persiste(tmp_path):
    a = Store(tmp_path / 'x.sqlite3')
    a.guardar_estado('live', 'pausado', 'Ollama detenido', True, 123.0)
    e = Store(tmp_path / 'x.sqlite3').cargar_estado('live')
    assert (e['estado'], e['motivo'], e['por_fallo'], e['proximo_reintento']) == ('pausado', 'Ollama detenido', 1, 123.0)


def test_bitacora_conserva_el_orden(store):
    store.registrar_error('datos', 'uno')
    store.registrar_error('llm', 'dos')
    assert [e['error'] for e in store.errores()] == ['uno', 'dos']


def test_configuracion_devuelve_la_ultima_version(store):
    store.guardar_configuracion({'a': 1})
    store.guardar_configuracion({'a': 2})
    assert store.cargar_configuracion() == {'a': 2}


def test_velas_se_guardan_sin_duplicar_y_en_orden(store):
    fila = [1000, '1', '2', '0.5', '1.5', '10', 2000, '15']
    store.guardar_velas('BTCUSDT', [fila, fila])
    store.guardar_velas('BTCUSDT', [[3000, '1', '2', '0.5', '1.6', '10', 4000, '15'], fila])
    assert [v['open_time'] for v in store.velas('BTCUSDT')] == [1000, 3000]


def test_una_base_vieja_recibe_la_columna_de_costos_sin_perder_ordenes(tmp_path):
    import sqlite3
    ruta = tmp_path / 'vieja.sqlite3'
    con = sqlite3.connect(ruta)
    con.execute('CREATE TABLE ordenes(id INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT NOT NULL, decision_id INTEGER, vela INTEGER, creado TEXT NOT NULL, '
                'lado TEXT, cantidad REAL, precio REAL, comision REAL, estado TEXT NOT NULL, motivo TEXT, resultado REAL)')
    con.execute("INSERT INTO ordenes(run, creado, lado, estado) VALUES('live:BTCUSDT', '2026-11-04', 'comprar', 'ejecutada')")
    con.commit()
    con.close()
    s = Store(ruta)
    s.guardar_orden('live:BTCUSDT', None, 1, 'vender', 'ejecutada', 'stop', 1.0, 100.0, 0.0, 5.0, modelo_costos='mejor compra + 5 pb')
    filas = s.ordenes('live:BTCUSDT')
    assert len(filas) == 2 and filas[0]['modelo_costos'] is None and filas[1]['modelo_costos'] == 'mejor compra + 5 pb'


def test_compras_autorizadas_cuenta_solo_las_compras_aprobadas_del_grupo_en_esa_vela(store):
    for run, fecha, final in [('live:A', '2026-11-12', 'comprar'), ('live:B', '2026-11-12', 'comprar'), ('live:C', '2026-11-12', 'mantener'),
                              ('live:D', '2026-11-11', 'comprar'), ('replay-x:A', '2026-11-12', 'comprar')]:
        store.guardar_decision(run=run, vela=0, fecha_vela=fecha, accion_final=final)
    assert store.compras_autorizadas('live', '2026-11-12') == 2


def test_ultimo_stop_con_perdida_da_el_dia_de_la_vela(store):
    dia = 86_400_000
    assert store.ultimo_stop_con_perdida('r') is None
    store.guardar_orden('r', None, 5 * dia, 'vender', 'ejecutada', 'stop', 1.0, 90.0, 0.0, -10.0)  # replay: vela diaria
    store.guardar_orden('r', None, None, 'vender', 'ejecutada', 'stop', 1.0, 110.0, 0.0, 10.0)  # stop que ganó: no cuenta
    assert store.ultimo_stop_con_perdida('r') == 5 * dia
    store.guardar_orden('r', None, None, 'vender', 'ejecutada', 'stop', 1.0, 90.0, 0.0, -10.0)  # en vivo: sin vela, con hora real
    assert store.ultimo_stop_con_perdida('r') % dia == 0 and store.ultimo_stop_con_perdida('r') > 5 * dia
