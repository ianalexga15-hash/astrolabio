import httpx
import pytest

from bot import mexc
from tests.helpers import DAY, START, random_walk, rows


def cliente(handler, esperas=None):
    espera = (esperas.append if esperas is not None else (lambda _: None))
    return mexc.Mexc(http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=espera)


def test_reintenta_con_espera_creciente_y_termina_devolviendo_datos():
    llamadas, esperas = [], []

    def handler(req):
        llamadas.append(req)
        if len(llamadas) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={'price': '100.5', 'symbol': 'BTCUSDT'})

    assert cliente(handler, esperas).ticker('BTCUSDT') == 100.5
    assert len(llamadas) == 3
    assert esperas[1] > esperas[0]


def test_sin_respuesta_agota_reintentos_limitados_y_lanza_error_claro():
    llamadas = []

    def handler(req):
        llamadas.append(req)
        raise httpx.ConnectError('sin red')

    with pytest.raises(mexc.MexcUnavailable, match='api/v3/ticker'):
        cliente(handler).ticker('BTCUSDT')
    assert len(llamadas) == mexc.REINTENTOS


def test_limite_de_solicitudes_respeta_retry_after_y_se_distingue():
    esperas = []

    def handler(req):
        return httpx.Response(429, headers={'Retry-After': '7'})

    with pytest.raises(mexc.MexcRateLimited):
        cliente(handler, esperas).ticker('BTCUSDT')
    assert 7 in esperas


def test_error_definitivo_del_cliente_no_se_reintenta():
    llamadas = []

    def handler(req):
        llamadas.append(req)
        return httpx.Response(400, json={'code': -1121, 'msg': 'Invalid symbol.'})

    with pytest.raises(mexc.MexcError, match='Invalid symbol'):
        cliente(handler).ticker('NOEXISTE')
    assert len(llamadas) == 1


def test_los_errores_no_repiten_el_texto_de_mexc_ni_de_la_red():
    marcador = 'texto-del-proveedor-<b>'

    def errores(handler, *llamadas):
        for llamada in llamadas:
            with pytest.raises(mexc.MexcError) as e:
                llamada(cliente(handler))
            yield str(e.value)

    def sin_red(req):
        raise httpx.ConnectError(marcador)
    textos = [*errores(lambda req: httpx.Response(400, json={'code': 700, 'msg': marcador}), lambda m: m.klines('BTCUSDT')),
              *errores(lambda req: httpx.Response(200, json={'raro': marcador}), lambda m: m.ticker('BTCUSDT'), lambda m: m.klines('BTCUSDT')),
              *errores(sin_red, lambda m: m.ticker('BTCUSDT'), lambda m: m.libro(['BTCUSDT']), lambda m: m.profundidad('BTCUSDT'))]
    assert len(textos) == 6 and not [t for t in textos if marcador in t]
    assert 'HTTP 400' in textos[0] and 'ConnectError' in textos[3]


def test_respuesta_malformada_no_se_toma_como_dato():
    with pytest.raises(mexc.MexcError, match='inesperad'):
        cliente(lambda req: httpx.Response(200, json={'nada': 1})).ticker('BTCUSDT')
    with pytest.raises(mexc.MexcError, match='inesperad'):
        cliente(lambda req: httpx.Response(200, text='<html>')).ticker('BTCUSDT')


def test_historial_pagina_con_inicio_y_fin_juntos_y_no_duplica():
    todas = rows(random_walk(1200))
    pedidas = []

    def handler(req):
        a, b = int(req.url.params['startTime']), int(req.url.params['endTime'])
        pedidas.append((a, b))
        assert b - a <= mexc.VENTANA_MAX_DIAS * DAY  # MEXC ignora el rango si llega solo uno o excede 500
        return httpx.Response(200, json=[r for r in todas if a <= r[0] <= b][:500])

    filas = cliente(handler).history('BTCUSDT', START, START + 1200 * DAY)
    assert len(pedidas) >= 3
    assert [f[0] for f in filas] == [r[0] for r in todas]


def test_velas_cerradas_excluye_la_vela_abierta():
    todas = rows(random_walk(5))
    ahora = START + 4 * DAY + 5  # la quinta vela sigue abierta
    filas = cliente(lambda req: httpx.Response(200, json=todas)).closed_candles('BTCUSDT', limit=5, now_ms=ahora)
    assert [f[0] for f in filas] == [r[0] for r in todas[:4]]


def test_vela_que_termina_exactamente_ahora_ya_cuenta_como_cerrada():
    todas = rows(random_walk(2))
    filas = cliente(lambda req: httpx.Response(200, json=todas)).closed_candles('BTCUSDT', limit=2, now_ms=START + 2 * DAY)
    assert len(filas) == 2


def test_filtros_del_par_salen_de_exchange_info():
    respuesta = {'symbols': [{'symbol': 'BTCUSDT', 'status': '1', 'baseSizePrecision': '0.000001',
                              'quoteAmountPrecision': '1', 'makerCommission': '0', 'takerCommission': '0.0005'}]}
    f = cliente(lambda req: httpx.Response(200, json=respuesta)).filters('BTCUSDT')
    assert f == {'paso_cantidad': 0.000001, 'minimo_quote': 1.0, 'maker': 0.0, 'taker': 0.0005}


@pytest.mark.parametrize('decimales, paso', [(2, 0.01), (0, 1.0)])
def test_si_el_paso_viene_en_cero_se_deduce_de_los_decimales_del_activo(decimales, paso):
    # MEXC manda baseSizePrecision '0' en 10 de los 40 pares (ENA, PEPE, SUI...): dividir entre él rompería la compra.
    respuesta = {'symbols': [{'symbol': 'ENAUSDT', 'status': '1', 'baseSizePrecision': '0', 'baseAssetPrecision': decimales, 'quoteAmountPrecision': '1'}]}
    assert cliente(lambda req: httpx.Response(200, json=respuesta)).filters('ENAUSDT')['paso_cantidad'] == paso


def test_filtros_rechazan_paso_en_cero_sin_decimales_conocidos():
    respuesta = {'symbols': [{'symbol': 'ENAUSDT', 'status': '1', 'baseSizePrecision': '0', 'quoteAmountPrecision': '1'}]}
    with pytest.raises(mexc.MexcError, match='inesperada'):
        cliente(lambda req: httpx.Response(200, json=respuesta)).filters('ENAUSDT')


def test_filtros_rechazan_par_no_operable():
    respuesta = {'symbols': [{'symbol': 'BTCUSDT', 'status': '2', 'baseSizePrecision': '0.000001', 'quoteAmountPrecision': '1'}]}
    with pytest.raises(mexc.MexcError, match='no está disponible'):
        cliente(lambda req: httpx.Response(200, json=respuesta)).filters('BTCUSDT')


def test_par_retirado_se_distingue_y_no_se_reintenta():
    # Desde el 2026-11-13 MEXC ya no lista DASHUSDT: velas y precio responden -1121.
    llamadas = []

    def handler(req):
        llamadas.append(req)
        return httpx.Response(400, json={'msg': 'Invalid symbol.', 'code': -1121, '_extend': None})

    with pytest.raises(mexc.ParRetirado, match='DASHUSDT'):
        cliente(handler).klines('DASHUSDT')
    assert len(llamadas) == 1
    with pytest.raises(mexc.MexcError) as otro:  # otro rechazo del cliente no se confunde con un par retirado
        cliente(lambda req: httpx.Response(400, json={'code': 700002, 'msg': 'Signature for this request is not valid.'})).ticker('BTCUSDT')
    assert not isinstance(otro.value, mexc.ParRetirado)


def test_filtros_de_un_par_retirado_lo_dicen_claro():
    with pytest.raises(mexc.ParRetirado, match='DASHUSDT'):
        cliente(lambda req: httpx.Response(200, json={'symbols': []})).filters('DASHUSDT')


def test_no_existe_ninguna_ruta_de_ordenes_reales():
    assert not hasattr(mexc.Mexc, 'order') and not hasattr(mexc.Mexc, 'place_order')
    assert not [n for n in dir(mexc.Mexc) if 'order' in n.lower()]
    with pytest.raises(mexc.MexcError, match='solo lectura'):
        cliente(lambda req: httpx.Response(200, json={}))._get('/api/v3/order', {})


def test_libro_trae_varios_activos_en_una_sola_consulta_sin_reintentar():
    llamadas = []
    filas = [dict(symbol='BTCUSDT', bidPrice='99.5', askPrice='100'), dict(symbol='ETHUSDT', bidPrice='9', askPrice='10'), dict(symbol='OTRO', bidPrice='1', askPrice='2'), dict(symbol='VACIO', bidPrice='', askPrice='')]

    def handler(req):
        llamadas.append(req)
        return httpx.Response(200, json=filas)

    r = cliente(handler).libro(['BTCUSDT', 'ETHUSDT', 'VACIO'])
    assert set(r) == {'BTCUSDT', 'ETHUSDT'} and r['BTCUSDT']['bid'] == 99.5 and r['BTCUSDT']['ask'] == 100.0 and r['BTCUSDT']['ts_ms'] > 0
    assert len(llamadas) == 1


@pytest.mark.parametrize('respuesta,error', [(lambda req: httpx.Response(429), mexc.MexcRateLimited), (lambda req: httpx.Response(500), mexc.MexcUnavailable),
                                             (lambda req: httpx.Response(200, json=[{'x': 1}]), mexc.MexcError)])
def test_libro_informa_fallos_sin_esperar(respuesta, error):
    esperas = []
    with pytest.raises(error):
        cliente(respuesta, esperas).libro(['BTCUSDT'])
    assert not esperas


def test_profundidad_trae_el_libro_en_una_consulta_sin_reintentar():
    llamadas = []

    def handler(req):
        llamadas.append(req)
        return httpx.Response(200, json=dict(lastUpdateId=1, bids=[['99.5', '2'], ['99', '5']], asks=[['100', '1'], ['101', '3']]))

    d = cliente(handler).profundidad('BTCUSDT')
    assert d['asks'] == [(100.0, 1.0), (101.0, 3.0)] and d['bids'][0] == (99.5, 2.0)
    assert len(llamadas) == 1 and llamadas[0].url.path == '/api/v3/depth' and llamadas[0].url.params['symbol'] == 'BTCUSDT'


def test_profundidad_informa_fallos_sin_esperar():
    esperas = []
    with pytest.raises(mexc.MexcUnavailable):
        cliente(lambda req: httpx.Response(503), esperas).profundidad('BTCUSDT')
    assert not esperas


def test_profundidad_descarta_niveles_sin_precio_o_cantidad_validos():
    libro = dict(bids=[['0', '5'], ['99', '0'], ['NaN', '1'], ['98', '2']], asks=[['100', '-1'], ['101', '3']])
    d = cliente(lambda req: httpx.Response(200, json=libro)).profundidad('BTCUSDT')
    assert d['bids'] == [(98.0, 2.0)] and d['asks'] == [(101.0, 3.0)]

