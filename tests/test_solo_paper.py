"""La entrega solo opera en Paper (rúbrica del curso, 2026-11-26): la app rechaza el endpoint real de MEXC y nadie enciende la cartera Real.

Sombra sigue disponible: MEXC valida cada orden con /api/v3/order/test sin ejecutarla. tests/test_real.py revisa la lógica de la
cartera Real con el bloqueo levantado; aquí se prueba la versión que se entrega.
"""
from urllib.parse import urlparse

import pytest

from bot import real
from bot.real import CONFIRMACION, ClienteOrdenes
from tests.test_api import app_cliente, entrar, raiz  # noqa: F401  (raiz es un fixture)
from tests.test_real import Http, cartera, paper, store  # noqa: F401  (store es un fixture)

COMPRA = dict(symbol='BTCUSDT', side='BUY', type='MARKET', quoteOrderQty='10', newClientOrderId='astro1')


def test_la_entrega_viene_bloqueada_en_paper():
    assert real.SOLO_PAPER is True


def test_el_cliente_rechaza_el_endpoint_real_sin_llamar_a_mexc():
    http = Http()
    c = ClienteOrdenes('clave', 'secreto', http=http, reloj=lambda: 1_700_000_000.0)
    with pytest.raises(PermissionError, match='solo opera en Paper'):
        c.orden(COMPRA)
    with pytest.raises(PermissionError, match='solo opera en Paper'):
        c._orden('POST', '/api/v3/order', COMPRA)  # ni por la ruta interna
    assert http.peticiones == []
    c.orden_prueba(COMPRA)  # sombra sí: MEXC valida sin ejecutar
    assert [(m, urlparse(u).path) for m, u, _ in http.peticiones] == [('POST', '/api/v3/order/test')]


def test_nadie_enciende_la_real_ni_con_la_confirmacion(store):
    c = cartera(store)
    with pytest.raises(PermissionError, match='solo opera en Paper'):
        c.cambiar_modo('real', CONFIRMACION)
    assert c.estado()['modo'] == 'apagada'
    assert c.cambiar_modo('sombra')['modo'] == 'sombra'


def test_un_modo_real_guardado_antes_se_lee_apagado_y_no_envia_nada(store):
    c = cartera(store)
    c._guardar(modo='real', desde_orden=0)
    paper(store, 'comprar')
    c.paso()
    assert c.estado()['modo'] == 'apagada'
    assert not c.cliente.enviadas and not c.cliente.probadas


def test_la_api_rechaza_encender_la_real(raiz):
    c, _ = app_cliente(raiz)
    entrar(c)
    r = c.post('/api/real/modo', json={'modo': 'real', 'confirmacion': CONFIRMACION})
    assert r.status_code == 403 and 'solo opera en Paper' in r.json()['detail']
    assert c.get('/api/real').json()['modo'] == 'apagada'
