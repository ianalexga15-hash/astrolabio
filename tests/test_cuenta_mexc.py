"""Cuenta real de MEXC en solo lectura: firma, rutas permitidas, errores sin secretos y ruta del panel."""
import hashlib
import hmac
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from bot import config
from bot.cuenta_mexc import CuentaMexc, registrar
from bot.mexc import MexcError

CLAVE, SECRETO = 'mx0vglclave-de-prueba-1234', 'secreto-de-prueba-muy-largo-5678'


class Respuesta:
    def __init__(self, estado, datos):
        self.status_code, self._datos = estado, datos

    def json(self):
        return self._datos

    @property
    def text(self):
        return str(self._datos)


class Http:
    """Cliente falso: guarda cada petición y responde la cuenta indicada."""

    def __init__(self, cuenta=None, estado=200, servidor_ms=1):
        self.peticiones = []
        self.cuenta = cuenta if cuenta is not None else {'canTrade': True, 'canWithdraw': True, 'updateTime': 1, 'balances': [
            {'asset': 'USDT', 'free': '120.5', 'locked': '0'}, {'asset': 'BTC', 'free': '0.001', 'locked': '0.0005'},
            {'asset': 'DOGE', 'free': '0', 'locked': '0'}]}
        self.estado, self.servidor_ms = estado, servidor_ms

    def get(self, url, headers=None, **_):
        self.peticiones.append((url, headers or {}))
        if url.endswith('/api/v3/time'):
            return Respuesta(200, {'serverTime': self.servidor_ms})
        return Respuesta(self.estado, self.cuenta)


def cuenta(http, ahora=1_700_000_000.0):
    return CuentaMexc(CLAVE, SECRETO, http=http, reloj=lambda: ahora)


def lecturas(http):
    return [u for u, _ in http.peticiones if '/api/v3/account' in u]


def test_firma_la_lectura_de_la_cuenta_como_pide_mexc():
    http = Http(servidor_ms=1_700_000_003_000)
    cuenta(http).saldos()
    url, cabeceras = http.peticiones[-1]
    partes = urlparse(url)
    assert partes.path == '/api/v3/account'
    consulta, firma = partes.query.rsplit('&signature=', 1)
    assert firma == hmac.new(SECRETO.encode(), consulta.encode(), hashlib.sha256).hexdigest()
    assert parse_qs(consulta)['timestamp'] == ['1700000003000']  # firma con el reloj de MEXC, no con el de la laptop
    assert cabeceras['X-MEXC-APIKEY'] == CLAVE


def test_devuelve_solo_los_saldos_que_no_son_cero():
    s = cuenta(Http()).saldos()
    assert s['saldos'] == [dict(activo='USDT', libre=120.5, bloqueado=0.0), dict(activo='BTC', libre=0.001, bloqueado=0.0005)]


def test_solo_puede_leer_no_existe_ninguna_ruta_de_ordenes():
    with pytest.raises(MexcError, match='solo se lee'):
        cuenta(Http())._get('/api/v3/order')
    assert not hasattr(CuentaMexc, 'comprar') and not hasattr(CuentaMexc, 'vender')


@pytest.mark.parametrize('codigo, texto', [(700002, 'firma'), (10072, 'clave'), (700007, 'permiso'), (700003, 'reloj')])
def test_un_rechazo_de_mexc_se_explica_en_espanol_sin_mostrar_secretos(codigo, texto):
    c = cuenta(Http(cuenta={'code': codigo, 'msg': 'rejected'}, estado=400))
    with pytest.raises(MexcError) as e:
        c.saldos()
    mensaje = str(e.value)
    assert texto in mensaje.lower()
    assert SECRETO not in mensaje and CLAVE not in mensaje and 'signature' not in mensaje
    assert SECRETO not in repr(c) and CLAVE not in repr(c)


def cliente_con(c, cada_s=30):
    app = FastAPI()

    def sesion(request: Request):
        if request.headers.get('x-prueba') != 'si':
            raise HTTPException(401, 'Inicia sesión con la clave del panel.')

    registrar(app, c, sesion, cada_s=cada_s)
    return TestClient(app)


def test_la_ruta_del_panel_pide_sesion_y_explica_si_falta_la_clave():
    cliente = cliente_con(CuentaMexc('', '', http=Http()))
    assert cliente.get('/api/cuenta-mexc').status_code == 401
    r = cliente.get('/api/cuenta-mexc', headers={'x-prueba': 'si'}).json()
    assert r['conectada'] is False and 'MEXC_API_KEY' in r['motivo']


def test_la_ruta_del_panel_muestra_saldos_sin_secretos_y_no_pregunta_a_mexc_en_cada_refresco():
    http = Http()
    cliente = cliente_con(cuenta(http))
    for _ in range(3):
        r = cliente.get('/api/cuenta-mexc', headers={'x-prueba': 'si'})
    datos = r.json()
    assert datos['conectada'] is True and datos['saldos'][0]['activo'] == 'USDT'
    assert len(lecturas(http)) == 1
    assert SECRETO not in r.text and CLAVE not in r.text


def test_un_error_de_mexc_llega_al_panel_explicado():
    http = Http(cuenta={'code': 700002, 'msg': 'rejected'}, estado=400)
    r = cliente_con(cuenta(http)).get('/api/cuenta-mexc', headers={'x-prueba': 'si'}).json()
    assert r['conectada'] is False and 'firma' in r['error'].lower()


def test_las_claves_de_mexc_se_leen_de_env_y_no_se_imprimen(monkeypatch):
    monkeypatch.setattr(config, 'leer_env', lambda: {'BOT_ADMIN_KEY': 'a' * 20, 'BOT_LLM_KEY': 'b' * 20, 'MEXC_API_KEY': CLAVE, 'MEXC_API_SECRET': SECRETO})
    aj = config.cargar_ajustes()
    assert (aj.mexc_clave, aj.mexc_secreto) == (CLAVE, SECRETO)
    assert SECRETO not in repr(aj) and CLAVE not in repr(aj)


def test_lee_la_comision_real_de_un_par_con_la_consulta_firmada():
    http = Http(cuenta={'data': {'makerCommission': 0.0, 'takerCommission': 0.0005}, 'code': 0, 'msg': 'success'})
    assert cuenta(http).comision('BTCUSDT') == dict(maker=0.0, taker=0.0005)
    url, _ = http.peticiones[-1]
    partes = urlparse(url)
    consulta, firma = partes.query.rsplit('&signature=', 1)
    assert partes.path == '/api/v3/tradeFee' and parse_qs(consulta)['symbol'] == ['BTCUSDT']
    assert firma == hmac.new(SECRETO.encode(), consulta.encode(), hashlib.sha256).hexdigest()


def test_sin_dato_de_comision_no_inventa_cero():
    with pytest.raises(MexcError, match='comisión'):
        cuenta(Http(cuenta={'code': 0, 'msg': 'success'})).comision('BTCUSDT')


def test_un_error_desconocido_de_mexc_no_repite_el_texto_del_proveedor():
    http = Http(cuenta={'code': 123456, 'msg': 'MARCADOR-FICTICIO-xyz'}, estado=400)
    r = cliente_con(cuenta(http)).get('/api/cuenta-mexc', headers={'x-prueba': 'si'}).json()
    assert r['conectada'] is False and '123456' in r['error'] and 'MARCADOR' not in r['error']
