"""Velas de 5 min, 1 h y diarias (con la del día en curso) para Mercado: solo lectura de MEXC, con sesión, validación y caché de 30 s."""
from bot import mexc
import pytest
from tests.helpers import START
from tests.test_api import app_cliente, entrar, raiz  # noqa: F401  (raiz es un fixture)


class MercadoVelas:
    """MEXC falso: anota cada consulta y devuelve velas con el formato de /api/v3/klines (precios en texto)."""
    def __init__(self):
        self.pedidas = []
        self.falla = None
        self.filas = None

    def klines(self, simbolo, inicio_ms=None, fin_ms=None, limit=500, intervalo='1d'):
        self.pedidas.append((simbolo, intervalo, limit))
        if self.falla:
            raise self.falla
        return self.filas or [[START + i * 300_000, '100.0', '101.5', '99.0', '100.5', '7', START + (i + 1) * 300_000 - 1, '700'] for i in range(limit)]


def preparar(raiz):
    c, app = app_cliente(raiz)
    falso, reloj = MercadoVelas(), [START]
    app.state.ctx.mercado = falso
    app.state.ctx.ahora = lambda: reloj[0]
    return c, falso, reloj


def test_pide_sesion(raiz):
    c, falso, _ = preparar(raiz)
    assert c.get('/api/velas-intradia?simbolo=BTCUSDT&intervalo=5m').status_code == 401
    assert falso.pedidas == []


def test_valida_activo_e_intervalo_sin_consultar_a_mexc(raiz):
    c, falso, _ = preparar(raiz)
    entrar(c)
    for consulta in ('simbolo=BTCUSDT&intervalo=1m', 'simbolo=BTCUSDT&intervalo=1w','simbolo=ETHUSDT&intervalo=5m', 'simbolo=btcusdt&intervalo=5m', 'intervalo=5m'):
        assert c.get(f'/api/velas-intradia?{consulta}').status_code == 422, consulta
    assert falso.pedidas == []


def test_devuelve_200_velas_con_numeros(raiz):
    c, falso, _ = preparar(raiz)
    entrar(c)
    velas = c.get('/api/velas-intradia?simbolo=BTCUSDT&intervalo=60m').json()
    assert falso.pedidas == [('BTCUSDT', '60m', 200)]  # el panel muestra 100; las otras calientan los indicadores
    assert len(velas) == 200 and velas[0] == dict(open_time=START, open=100.0, high=101.5, low=99.0, close=100.5)


def test_cache_de_30_s_por_activo_e_intervalo(raiz):
    c, falso, reloj = preparar(raiz)
    entrar(c)
    ruta = '/api/velas-intradia?simbolo=BTCUSDT&intervalo=5m'
    c.get(ruta)
    reloj[0] += 29_000
    c.get(ruta)
    assert len(falso.pedidas) == 1  # dentro de 30 s no vuelve a MEXC
    c.get('/api/velas-intradia?simbolo=BTCUSDT&intervalo=60m')
    reloj[0] += 1_000
    c.get(ruta)
    assert [p[1] for p in falso.pedidas] == ['5m', '60m', '5m']


def test_errores_de_mexc_se_explican_y_no_se_guardan(raiz):
    c, falso, _ = preparar(raiz)
    entrar(c)
    ruta = '/api/velas-intradia?simbolo=BTCUSDT&intervalo=5m'
    falso.falla = mexc.MexcUnavailable('MEXC no respondió.')
    r = c.get(ruta)
    assert r.status_code == 503 and 'MEXC no respondió' in r.json()['detail']
    falso.falla, falso.filas = None, [[START, 'no-es-numero', '1', '1', '1']]
    assert c.get(ruta).status_code == 502
    falso.filas = None
    assert c.get(ruta).status_code == 200 and len(falso.pedidas) == 3  # el error no quedó en el caché


@pytest.mark.parametrize('precios', [
    ['nan', '101', '99', '100'], ['100', 'inf', '99', '100'],
    ['100', '101', '-1', '100'], ['100', '99', '101', '100'],
    ['102', '101', '99', '100'], ['100', '101', '99', '102'],
])
def test_ohlc_invalido_no_contamina_cache(raiz, precios):
    c, falso, _ = preparar(raiz)
    entrar(c)
    ruta = '/api/velas-intradia?simbolo=BTCUSDT&intervalo=5m'
    falso.filas = [[START, *precios]]
    assert c.get(ruta).status_code == 502
    falso.filas = None
    assert c.get(ruta).status_code == 200
    assert len(falso.pedidas) == 2
