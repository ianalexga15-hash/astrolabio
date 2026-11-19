"""Historial de operaciones: cada compra con su venta y si se compró en alta o en baja respecto al día anterior."""
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from bot.historial import DIA_MS, historial, registrar
from bot.store import Store

T0 = 1_762_000_000_000 - 1_762_000_000_000 % DIA_MS  # inicio de un día UTC
VELAS = {'BTCUSDT': [dict(open_time=T0, high=100.0, low=90.0, close=95.0)]}  # el día anterior a las compras


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def orden(id, simbolo, ms, lado, precio, resultado=None, motivo='senal', estado='ejecutada'):
    return dict(id=id, run=f'live:{simbolo}', creado=iso(ms), lado=lado, estado=estado, precio=precio, cantidad=1.0, comision=0.0,
                resultado=resultado, motivo=motivo, modelo_costos=None)


def test_cada_compra_con_su_venta_y_su_altura_en_el_rango_del_dia_anterior():
    h = historial([orden(1, 'BTCUSDT', T0 + DIA_MS + 3_600_000, 'comprar', 98.0),
                   orden(2, 'BTCUSDT', T0 + DIA_MS + 7 * 3_600_000, 'vender', 102.0, resultado=3.8, motivo='objetivo')], VELAS)
    o = h[0]
    assert (o['simbolo'], o['estado'], o['etiqueta'], o['motivo_venta']) == ('BTCUSDT', 'cerrada', 'en alta', 'objetivo')
    assert o['altura'] == pytest.approx(0.8) and o['resultado'] == pytest.approx(3.8) and o['horas'] == pytest.approx(6.0)
    assert o['rendimiento'] == pytest.approx(102 / 98 - 1)


@pytest.mark.parametrize('precio, etiqueta', [(105.0, 'sobre el máximo del día anterior'), (99.0, 'en alta'), (95.0, 'a media altura'),
                                              (91.0, 'en baja'), (85.0, 'bajo el mínimo del día anterior')])
def test_la_etiqueta_dice_a_que_altura_compro(precio, etiqueta):
    h = historial([orden(1, 'BTCUSDT', T0 + DIA_MS + 60_000, 'comprar', precio)], VELAS)
    assert h[0]['etiqueta'] == etiqueta and h[0]['estado'] == 'abierta'


def test_sin_vela_del_dia_anterior_no_inventa_la_altura():
    h = historial([orden(1, 'ETHUSDT', T0 + DIA_MS, 'comprar', 10.0)], VELAS)
    assert h[0]['altura'] is None and h[0]['etiqueta'] == 'sin dato'


def test_va_de_la_mas_reciente_a_la_mas_antigua_e_ignora_lo_no_ejecutado():
    h = historial([orden(1, 'BTCUSDT', T0 + DIA_MS + 60_000, 'comprar', 95.0),
                   orden(2, 'BTCUSDT', T0 + DIA_MS + 120_000, 'vender', 96.0, resultado=1.0),
                   orden(3, 'BTCUSDT', T0 + DIA_MS + 180_000, 'comprar', 97.0, estado='expirada'),
                   orden(4, 'BTCUSDT', T0 + DIA_MS + 240_000, 'comprar', 94.0)], VELAS)
    assert [(o['precio_compra'], o['estado']) for o in h] == [(94.0, 'abierta'), (95.0, 'cerrada')]


def test_la_ruta_del_panel_pide_sesion(tmp_path):
    store = Store(tmp_path / 'bot.sqlite3')
    store.guardar_orden('live:BTCUSDT', None, 1, 'comprar', 'ejecutada', 'senal', 1.0, 95.0, 0.0)
    app = FastAPI()

    def sesion(request: Request):
        if request.headers.get('x-prueba') != 'si':
            raise HTTPException(401, 'Inicia sesión con la clave del panel.')

    registrar(app, store, sesion)
    cliente = TestClient(app)
    assert cliente.get('/api/historial').status_code == 401
    datos = cliente.get('/api/historial', headers={'x-prueba': 'si'}).json()
    assert len(datos) == 1 and datos[0]['simbolo'] == 'BTCUSDT' and datos[0]['etiqueta'] == 'sin dato'
