import pytest

from bot.paper import Cuenta
from bot.report import resumen_grupo, resumen_run, serie_grupo
from bot.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / 'r.sqlite3')
    s.abrir_run('r1', 'replay', 'prueba')
    for i, (efectivo, cantidad, precio) in enumerate([(1000, 0, 100), (0, 10, 110), (1320, 0, 132), (1320, 0, 110)]):
        s.marcar_patrimonio('r1', i, f'2026-01-0{i + 1}', Cuenta(efectivo=efectivo, cantidad=cantidad), precio)
    s.guardar_orden('r1', None, 1, 'comprar', 'ejecutada', 'senal', 10, 100, 1.0)
    s.guardar_orden('r1', None, 2, 'vender', 'ejecutada', 'decision', 10, 132, 1.0, 319.0)
    s.guardar_orden('r1', None, 3, 'comprar', 'rechazada', 'Saldo insuficiente')
    s.guardar_decision(run='r1', vela=1, fecha_vela='2026-01-02', pronostico=0.01, senal=1, aprobada=1, accion_final='comprar', latencia_ms=100.0, origen='llm')
    s.guardar_decision(run='r1', vela=2, fecha_vela='2026-01-03', pronostico=-0.01, senal=0, aprobada=0, accion_final='mantener', latencia_ms=300.0, origen='llm')
    return s


def test_resumen_calcula_rendimiento_drawdown_y_operaciones_cerradas(store):
    r = resumen_run(store, 'r1', capital=1000.0, comision=0.0)
    assert r['rendimiento'] == pytest.approx(0.32)
    assert r['drawdown'] == pytest.approx(0.0)
    assert r['operaciones'] == 1 and r['win_rate'] == 1.0
    assert r['costos'] == 2.0 and r['ordenes_rechazadas'] == 1


def test_resumen_cuenta_acciones_rechazadas_y_latencia(store):
    r = resumen_run(store, 'r1', capital=1000.0, comision=0.0)
    assert r['acciones_rechazadas'] == 1 and r['ciclos'] == 2
    assert r['latencia_media_ms'] == pytest.approx(200.0)


def test_resumen_compara_con_comprar_y_mantener_mismo_periodo(store):
    r = resumen_run(store, 'r1', capital=1000.0, comision=0.001)
    assert r['comprar_y_mantener'] == pytest.approx(1000 / 1.001 / 100 * 110 * 0.999 / 1000 - 1)
    assert r['periodo'] == ['2026-01-01', '2026-01-04']


def test_corrida_sin_datos_no_inventa_resultados(tmp_path):
    s = Store(tmp_path / 'v.sqlite3')
    s.abrir_run('vacia', 'live')
    r = resumen_run(s, 'vacia', capital=1000.0, comision=0.0)
    assert r['rendimiento'] is None and r['win_rate'] is None and r['ciclos'] == 0


@pytest.fixture
def grupo(tmp_path):
    s = Store(tmp_path / 'g.sqlite3')
    s.abrir_run('live:A', 'live', 'A')
    s.abrir_run('live:B', 'live', 'B')
    s.marcar_patrimonio('live:A', 1, '2026-01-01', Cuenta(efectivo=500), 10.0)
    s.marcar_patrimonio('live:A', 2, '2026-01-02', Cuenta(efectivo=600), 20.0)
    s.marcar_patrimonio('live:B', 2, '2026-01-02', Cuenta(efectivo=450), 5.0)
    s.guardar_orden('live:A', None, 2, 'vender', 'ejecutada', 'stop', 1, 10, 0.5, 100.0)
    s.guardar_decision(run='live:A', vela=1, fecha_vela='2026-01-01', aprobada=1, accion_final='comprar', latencia_ms=100.0, origen='llm')
    s.guardar_decision(run='live:B', vela=2, fecha_vela='2026-01-02', aprobada=0, accion_final='mantener', latencia_ms=300.0, origen='llm')
    return s


def test_serie_suma_activos_y_usa_el_cupo_antes_de_la_primera_marca(grupo):
    serie = serie_grupo(grupo, 'live', 1000.0)
    assert [m['patrimonio'] for m in serie] == [1000.0, 1050.0]
    assert serie[0]['precio'] == 100.0 and serie[1]['precio'] == pytest.approx(150.0)


def test_resumen_de_grupo_suma_operaciones_y_rechazos(grupo):
    r = resumen_grupo(grupo, 'live', 1000.0, 0.0, 'Cartera', 'live')
    assert r['activos'] == 2 and r['ciclos'] == 2 and r['operaciones'] == 1 and r['win_rate'] == 1.0 and r['acciones_rechazadas'] == 1
    assert r['rendimiento'] == pytest.approx(0.05) and r['comprar_y_mantener'] == pytest.approx(0.5)
    assert r['latencia_media_ms'] == pytest.approx(200.0) and r['etiqueta'] == 'Cartera'


def test_grupo_sin_corridas_no_inventa_resultados(tmp_path):
    s = Store(tmp_path / 'x.sqlite3')
    r = resumen_grupo(s, 'live', 1000.0, 0.0, 'Cartera', 'live')
    assert r['rendimiento'] is None and r['ciclos'] == 0 and serie_grupo(s, 'live', 1000.0) == []


def test_en_vivo_suma_solo_los_activos_de_la_cartera_actual(grupo):
    grupo.abrir_run('live:C', 'live', 'C')  # salió con su efectivo: ya no es dinero de la cartera
    grupo.marcar_patrimonio('live:C', 1, '2026-01-01', Cuenta(efectivo=480), 1.0)
    grupo.abrir_run('live:D', 'live', 'D')  # salió sin operar: sin marcas, tampoco cuenta su cupo
    actuales = ['live:A', 'live:B']
    assert [m['patrimonio'] for m in serie_grupo(grupo, 'live', 1000.0, runs=actuales)] == [1000.0, 1050.0]
    r = resumen_grupo(grupo, 'live', 1000.0, 0.0, 'Cartera', 'live', runs=actuales)
    assert r['activos'] == 2 and r['patrimonio_final'] == pytest.approx(1050.0) and r['rendimiento'] == pytest.approx(0.05)
