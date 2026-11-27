"""Cartera Real: apagada por defecto, la enciende Alex, repite lo que Paper ejecuta dentro de sus topes y nunca duplica órdenes."""
import hashlib
import hmac
from pathlib import Path
from urllib.parse import urlparse

import pytest

from bot import real
from bot.mexc import MexcError, MexcUnavailable
from bot.real import CONFIRMACION, CarteraReal, ClienteOrdenes
from bot.store import Store


class Cliente:
    """Cuenta falsa de MEXC con BTC a 100 al comprar y a 90 al vender."""
    configurada = True

    def __init__(self, usdt=100.0, fallo=None):
        self.usdt, self.btc = usdt, 0.0
        self.enviadas, self.probadas, self.consultas = [], [], []
        self.fallo = fallo  # excepción de la próxima orden real
        self.registradas = {}  # id de cliente -> lo que MEXC diría al consultarla

    def saldos(self):
        return dict(saldos=[dict(activo='USDT', libre=self.usdt, bloqueado=0.0), dict(activo='BTC', libre=self.btc, bloqueado=0.0)])

    def orden_prueba(self, p):
        self.probadas.append(p)
        return {}

    def orden(self, p):
        self.enviadas.append(p)
        if self.fallo:
            error, self.fallo = self.fallo, None
            if isinstance(error, MexcUnavailable):  # llegó a MEXC aunque la respuesta se perdió
                self._ejecutar(p)
            raise error
        return self._ejecutar(p)

    def _ejecutar(self, p):
        if p['side'] == 'BUY':
            cotizado = float(p['quoteOrderQty'])
            cantidad = cotizado / 100
            self.usdt, self.btc = self.usdt - cotizado, self.btc + cantidad
        else:
            cantidad = float(p['quantity'])
            cotizado = cantidad * 90
            self.usdt, self.btc = self.usdt + cotizado, self.btc - cantidad
        r = dict(orderId=f'm{len(self.registradas) + 1}', status='FILLED', executedQty=str(cantidad), cummulativeQuoteQty=str(cotizado))
        self.registradas[p['newClientOrderId']] = r
        return dict(orderId=r['orderId'])

    def consultar(self, simbolo, cliente_id):
        self.consultas.append(cliente_id)
        if cliente_id not in self.registradas:
            raise MexcError('MEXC no tiene esa orden.')
        return self.registradas[cliente_id]


class Mercado:
    def filters(self, simbolo):
        return dict(paso_cantidad=0.0001, minimo_quote=5.0, base='BTC', maker=0.0, taker=0.0005)


@pytest.fixture(autouse=True)
def real_desbloqueada(monkeypatch):
    """Estas pruebas revisan la lógica de la cartera Real; la entrega la deja bloqueada en Paper (tests/test_solo_paper.py)."""
    monkeypatch.setattr(real, 'SOLO_PAPER', False)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'bot.sqlite3')


def paper(store, lado, simbolo='BTCUSDT', estado='ejecutada'):
    store.guardar_orden(f'live:{simbolo}', None, 1, lado, estado, 'prueba', 1.0, 100.0, 0.0)


def cartera(store, cliente=None, **topes):
    return CarteraReal(store, cliente or Cliente(), Mercado(), topes=topes or None)


def test_arranca_apagada_y_no_envia_nada(store):
    c = cartera(store)
    paper(store, 'comprar')
    c.paso()
    assert c.estado()['modo'] == 'apagada'
    assert not c.cliente.enviadas and not c.cliente.probadas


def test_encender_la_real_pide_la_confirmacion_escrita(store):
    c = cartera(store)
    for confirmacion in ('', 'activar'):
        with pytest.raises(PermissionError):
            c.cambiar_modo('real', confirmacion)
    c.cambiar_modo('real', CONFIRMACION)
    assert c.estado()['modo'] == 'real'


def test_solo_repite_lo_que_paper_ejecuta_despues_de_encenderla(store):
    paper(store, 'comprar', 'ETHUSDT')  # anterior a encenderla: nunca se repite
    c = cartera(store)
    c.cambiar_modo('real', CONFIRMACION)
    paper(store, 'comprar', estado='rechazada')  # solo cuentan las ejecutadas
    paper(store, 'comprar')
    c.paso()
    assert [p['symbol'] for p in c.cliente.enviadas] == ['BTCUSDT']


def test_sombra_valida_cada_orden_sin_ejecutarla(store):
    c = cartera(store)
    c.cambiar_modo('sombra')
    paper(store, 'comprar')
    c.paso()
    assert len(c.cliente.probadas) == 1 and not c.cliente.enviadas
    assert c.ordenes()[0]['estado'] == 'probada'


def test_compra_dentro_de_sus_topes_y_sin_duplicar(store):
    c = cartera(store, max_orden_usdt=10.0, tope_total_usdt=15.0)
    c.cambiar_modo('real', CONFIRMACION)
    paper(store, 'comprar')
    c.paso()
    c.paso()  # la misma orden de Paper nunca se repite dos veces
    [p] = c.cliente.enviadas
    assert (p['type'], p['side'], float(p['quoteOrderQty'])) == ('MARKET', 'BUY', 10.0)
    assert p['newClientOrderId'].startswith('astro')
    paper(store, 'comprar')  # quedan 5 USDT de tope: justo el mínimo de MEXC
    c.paso()
    assert float(c.cliente.enviadas[-1]['quoteOrderQty']) == 5.0
    paper(store, 'comprar')
    c.paso()
    assert len(c.cliente.enviadas) == 2 and 'tope' in c.ordenes()[0]['motivo']


def test_sin_saldo_no_se_envia_nada(store):
    c = cartera(store, Cliente(usdt=0.0))
    c.cambiar_modo('real', CONFIRMACION)
    paper(store, 'comprar')
    c.paso()
    assert not c.cliente.enviadas
    assert c.ordenes()[0]['estado'] == 'omitida' and 'saldo' in c.ordenes()[0]['motivo']


def test_la_venta_sale_de_lo_que_compro_la_real(store):
    c = cartera(store)
    c.cambiar_modo('real', CONFIRMACION)
    paper(store, 'comprar')
    c.paso()  # 10 USDT a 100: 0.1 BTC
    assert c.posiciones()[0]['cantidad'] == pytest.approx(0.1)
    paper(store, 'vender')
    c.paso()
    venta = c.cliente.enviadas[-1]
    assert venta['side'] == 'SELL' and float(venta['quantity']) == pytest.approx(0.1)
    assert c.posiciones() == []
    assert c.ordenes()[0]['resultado'] == pytest.approx(-1.0)  # vendió en 9 lo que costó 10


def test_sin_permiso_de_trade_bloquea_compras_pero_no_ventas(store):
    cliente = Cliente(fallo=MexcError('La clave no tiene permiso de Trade.'))
    c = cartera(store, cliente)
    c.cambiar_modo('real', CONFIRMACION)
    paper(store, 'comprar')
    c.paso()
    e = c.estado()
    assert e['compras_bloqueadas'] and 'Trade' in e['motivo']
    paper(store, 'comprar')
    c.paso()
    assert len(cliente.enviadas) == 1
    assert any(r['etapa'] == 'real' for r in store.errores())


def test_una_orden_sin_respuesta_se_consulta_antes_de_reintentar(store):
    cliente = Cliente(fallo=MexcUnavailable('MEXC no respondió.'))
    c = cartera(store, cliente)
    c.cambiar_modo('real', CONFIRMACION)
    paper(store, 'comprar')
    c.paso()
    assert c.ordenes()[0]['estado'] == 'enviando'
    c.paso()
    assert len(cliente.enviadas) == 1 and cliente.consultas  # nunca la manda dos veces
    assert c.ordenes()[0]['estado'] == 'ejecutada' and c.posiciones()[0]['cantidad'] == pytest.approx(0.1)


class Respuesta:
    def __init__(self, estado, datos):
        self.status_code, self._datos = estado, datos

    def json(self):
        return self._datos


class Http:
    def __init__(self):
        self.peticiones = []

    def get(self, url, **_):  # solo la hora del servidor
        return Respuesta(200, {'serverTime': 1_700_000_000_000})

    def request(self, metodo, url, headers=None, **_):
        self.peticiones.append((metodo, url, headers or {}))
        return Respuesta(200, {'orderId': '1'})


def test_el_cliente_firma_y_solo_conoce_las_rutas_de_ordenes():
    http = Http()
    c = ClienteOrdenes('clave', 'secreto', http=http, reloj=lambda: 1_700_000_000.0)
    c.orden_prueba(dict(symbol='BTCUSDT', side='BUY', type='MARKET', quoteOrderQty='10', newClientOrderId='astro1'))
    metodo, url, cabeceras = http.peticiones[-1]
    assert metodo == 'POST' and urlparse(url).path == '/api/v3/order/test' and cabeceras['X-MEXC-APIKEY'] == 'clave'
    consulta, firma = urlparse(url).query.rsplit('&signature=', 1)
    assert firma == hmac.new(b'secreto', consulta.encode(), hashlib.sha256).hexdigest()
    with pytest.raises(MexcError):
        c._orden('POST', '/api/v3/capital/withdraw', {})


def test_solo_el_modulo_real_conoce_la_ruta_de_ordenes():
    bot = Path(__file__).resolve().parents[1] / 'bot'
    assert sorted(p.name for p in bot.glob('*.py') if '/api/v3/order' in p.read_text(encoding='utf-8')) == ['real.py']
