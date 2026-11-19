"""Exportación de los registros a CSV."""
import csv

from bot.paper import Cuenta
import pytest

from bot.report import exportar_registros, metricas_operaciones
from bot.security import huella_clave
from bot.store import Store


def test_exporta_cada_tabla_de_evidencia_con_encabezados_y_nunca_el_acceso(tmp_path):
    store = Store(tmp_path / 'bot.sqlite3')
    store.abrir_run('live:BTCUSDT', 'live', 'En vivo')
    store.guardar_orden('live:BTCUSDT', None, 1, 'comprar', 'ejecutada', 'senal', 0.01, 100.0, 0.0)
    store.marcar_patrimonio('live:BTCUSDT', 1, '2026-11-04', Cuenta(efectivo=1250.0), 100.0)
    store.registrar_error('datos', 'Dato atrasado', 'vela vieja', 'pausar', 'sin operar')
    acceso = huella_clave('una-contrasena-larga')
    store.guardar_acceso(acceso)
    sesion = 'a1' * 32  # huella SHA-256 de un token del panel
    store.guardar_sesiones({sesion: 9e9})

    resumen = exportar_registros(tmp_path / 'bot.sqlite3', tmp_path / 'salida')

    assert resumen['ordenes'] == 1 and resumen['patrimonio'] == 1 and resumen['errores'] == 1 and resumen['decisiones'] == 0
    with open(tmp_path / 'salida' / 'ordenes.csv', encoding='utf-8') as f:
        filas = list(csv.DictReader(f))
    assert filas[0]['lado'] == 'comprar' and float(filas[0]['precio']) == 100.0
    assert not (tmp_path / 'salida' / 'acceso.csv').exists() and not (tmp_path / 'salida' / 'sesiones.csv').exists()
    for archivo in (tmp_path / 'salida').iterdir():
        texto = archivo.read_text(encoding='utf-8')
        assert acceso['huella'] not in texto and sesion not in texto, archivo.name


def test_resume_los_ciclos_en_vivo_por_vela_sin_contar_replays(tmp_path):
    store = Store(tmp_path / 'bot.sqlite3')
    for run in ('live:BTCUSDT', 'live:ETHUSDT', 'replay-VA-regla-BTCUSDT-1'):
        store.guardar_decision(run=run, vela=1, fecha_vela='2026-11-04', aprobada=1, accion_final='mantener', latencia_ms=7000.0)
    store.guardar_orden('live:BTCUSDT', None, 1, 'comprar', 'expirada', 'Spread y libro: 30 de 25 puntos base')
    exportar_registros(tmp_path / 'bot.sqlite3', tmp_path / 'salida')
    texto = (tmp_path / 'salida' / 'resumen_en_vivo.md').read_text(encoding='utf-8')
    assert '| 2026-11-04 | 2 | 2 | 0 | 7.0 s |' in texto
    assert 'Ciclos en vivo: 2.' in texto and 'expiradas: 1' in texto and 'Errores registrados: 0.' in texto



def orden(id, run, creado, lado, cantidad, precio, comision, resultado=None, estado='ejecutada'):
    return dict(id=id, run=run, creado=creado, lado=lado, estado=estado, cantidad=cantidad, precio=precio, comision=comision, resultado=resultado)


def test_metricas_de_operaciones_cerradas_contrastadas_con_cada_par_compra_venta():
    m = metricas_operaciones([
        orden(1, 'live:AUSDT', '2026-11-06T04:00:00+00:00', 'comprar', 10, 100.0, 1.0),
        orden(2, 'live:BUSDT', '2026-11-06T05:00:00+00:00', 'comprar', 5, 200.0, 1.0),
        orden(3, 'live:AUSDT', '2026-11-06T10:00:00+00:00', 'vender', 10, 110.0, 1.1, 97.9),
        orden(4, 'live:BUSDT', '2026-11-07T05:00:00+00:00', 'vender', 5, 190.0, 0.95, -51.95),
        orden(5, 'live:CUSDT', '2026-11-07T06:00:00+00:00', 'comprar', 1, 50.0, 0.0),
        orden(6, 'live:DUSDT', '2026-11-07T06:00:00+00:00', 'comprar', None, None, None, estado='expirada'),
    ])
    assert (m['cerradas'], m['abiertas'], m['descuadres'], m['acierto']) == (2, 1, 0, 0.5)
    assert m['factor_beneficio'] == pytest.approx(97.9 / 51.95)
    assert m['resultado_neto'] == pytest.approx(45.95)
    assert m['duracion_media_h'] == pytest.approx((6 + 24) / 2)


def test_un_resultado_que_no_cuadra_con_sus_precios_y_comisiones_se_marca():
    m = metricas_operaciones([orden(1, 'live:AUSDT', '2026-11-06T04:00:00+00:00', 'comprar', 10, 100.0, 1.0),
                              orden(2, 'live:AUSDT', '2026-11-06T05:00:00+00:00', 'vender', 10, 110.0, 1.1, 120.0)])
    assert m['descuadres'] == 1


def test_sin_operaciones_cerradas_no_inventa_cifras():
    m = metricas_operaciones([orden(1, 'live:AUSDT', '2026-11-06T04:00:00+00:00', 'comprar', 10, 100.0, 1.0)])
    assert m == dict(cerradas=0, abiertas=1, acierto=None, factor_beneficio=None, resultado_neto=0.0, duracion_media_h=None, descuadres=0)


def test_el_resumen_en_vivo_incluye_las_operaciones_cerradas(tmp_path):
    store = Store(tmp_path / 'bot.sqlite3')
    store.guardar_orden('live:BTCUSDT', None, 1, 'comprar', 'ejecutada', 'senal', 10, 100.0, 1.0)
    store.guardar_orden('live:BTCUSDT', None, 2, 'vender', 'ejecutada', 'objetivo', 10, 110.0, 1.1, 97.9)
    exportar_registros(tmp_path / 'bot.sqlite3', tmp_path / 'salida')
    texto = (tmp_path / 'salida' / 'resumen_en_vivo.md').read_text(encoding='utf-8')
    assert 'Operaciones cerradas: 1; acierto 100 %' in texto and 'resultado neto 97.90 USDT' in texto and 'descuadres: 0' in texto
