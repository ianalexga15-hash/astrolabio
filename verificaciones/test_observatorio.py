from types import SimpleNamespace

import numpy as np
from fastapi.testclient import TestClient

from bot.observatorio import DAY, Observatorio, concentracion, deterioro, salud
from bot.api import crear_app
from tests.test_api import raiz, ajustes, preparar_modelo, Mercado, ADMIN
from tests.test_api import app_cliente


def contexto(tmp_path):
    ahora = [100 * DAY + 10_000]
    modelo = SimpleNamespace(version='v1', pronosticar=lambda tabla: 0.02)
    ctx = SimpleNamespace(aj=SimpleNamespace(db=tmp_path/'datos.db', raiz=tmp_path),
                          ahora=lambda: ahora[0], modelos={'BTCUSDT': modelo}, cartera=None)
    return ctx, ahora


def velas(n=100):
    return [dict(open_time=i*DAY, close_time=(i+1)*DAY-1, open=100+i, high=102+i,
                 low=99+i, close=101+i, volume=1000) for i in range(n)]


def test_sombra_prospectiva_deduplica_y_espera_objetivo(tmp_path):
    ctx, ahora = contexto(tmp_path)
    o = Observatorio(ctx)
    o._sombra({'BTCUSDT': velas()}, ahora[0])
    o._sombra({'BTCUSDT': velas()}, ahora[0])
    assert o.db.execute('SELECT count(*) FROM sombra').fetchone()[0] == 1
    assert o.resumen()['sombra']['pendientes'] == 1
    ahora[0] = 101*DAY+10000
    o._sombra({'BTCUSDT': velas(101)}, ahora[0])
    r = o.resumen()['sombra']
    assert r['comparacion'][0]['n'] == 1
    assert r['pendientes'] == 1
    assert r['comparacion'][0]['candidato'] == 'baseline-cero'
    o.db.close()


def test_no_rellena_historia_ni_evalua_velas_abiertas(tmp_path):
    ctx, ahora = contexto(tmp_path)
    o = Observatorio(ctx)
    o._sombra({'BTCUSDT': velas(99)}, ahora[0])
    assert o.resumen()['sombra']['pendientes'] == 0
    o._sombra({'BTCUSDT': velas()}, ahora[0])
    o._sombra({'BTCUSDT': velas(101)}, ahora[0])
    assert not o.resumen()['sombra']['comparacion']
    o.db.close()


def test_correlacion_alinea_fechas_y_no_acepta_constantes():
    f = velas(80)
    r = concentracion({'A': f, 'B': f[20:], 'C': [{**x, 'close':100} for x in f]}, {'A':20,'B':30},100)
    assert len(r['pares']) == 1
    assert r['pares'][0]['n'] == 59
    assert abs(r['pares'][0]['correlacion']-1)<1e-9
    assert r['exposicion'] == .5


def test_deterioro_exige_dias_y_separa_versiones():
    filas = [dict(simbolo='BTC', version='v1', objetivo=i, prediccion=.01 if i<30 else .1, real=0.) for i in range(60)]
    assert deterioro(filas[:59])[0]['estado'] == 'evidencia_insuficiente'
    assert deterioro(filas)[0]['estado'] == 'revisar'
    filas[-1]['version']='v2'
    assert all(f['estado']=='evidencia_insuficiente' for f in deterioro(filas))


def test_grabacion_deduplicada_sin_secretos_y_replay_no_opera(tmp_path):
    ctx, ahora = contexto(tmp_path)
    ctx.cartera=SimpleNamespace(reflejo=SimpleNamespace(radar={'BTC':dict(bid=1,ask=2,clave='secreto')}),
                               ultimo_libro_ms=ahora[0], resumen=lambda:dict(posiciones=0), medicion=lambda:{})
    o=Observatorio(ctx)
    o.ultimo=ahora[0]  # solo captura, no análisis minuto
    o.ciclo(); o.ciclo()
    filas=o.reproducir()
    assert len(filas)==1 and 'clave' not in filas[0]['radar']['BTC']
    assert o.reproducir(filas[0]['id'])==[]
    assert o.reproducir()==filas
    o.db.close()


def test_salud_no_inventa_diagnostico():
    s=salud([dict(modelo='lineal', RMSE_TR='0.1',RMSE_VA='0.2'),dict(RMSE_TR='nan',RMSE_VA='1')])
    assert len(s['filas'])==1
    assert s['filas'][0]['razon']==2
    assert 'sobreajuste' in s['aviso']


def test_api_privada_sin_modelo_y_cursor_acotado(raiz):
    app=crear_app(ajustes(raiz), mercado=Mercado(), hilos=False, pruebas=True)
    with TestClient(app) as client:
        assert client.get('/api/observatorio').status_code==401
        assert client.get('/api/observatorio/replay').status_code==401
        assert client.post('/api/login',json={'clave':ADMIN}).status_code==200
        assert client.get('/api/observatorio').status_code==200
        assert client.get('/api/observatorio/replay?limite=999').status_code==422
        assert client.get('/api/observatorio/replay').json()==[]


def test_observar_no_modifica_cuentas_estados_ni_ordenes(raiz):
    from dataclasses import asdict
    client, app = app_cliente(raiz)
    ctx=app.state.ctx
    ctx.cartera.barrer()
    def estado():
        return {s:(asdict(a.cuenta),a.estado,ctx.store.ordenes(a.run_id)) for s,a in ctx.cartera.agentes.items()}
    antes=estado()
    for _ in range(3):
        app.state.observatorio.ciclo()
        app.state.observatorio.resumen()
        app.state.observatorio.reproducir()
    assert estado()==antes
