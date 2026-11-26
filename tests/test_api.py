import asyncio
import json
import time

import httpx
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from bot import llm, mexc, model
from bot.api import crear_app
from bot.config import Ajustes
from bot.events import Eventos
from tests.helpers import DAY, START, random_walk, rows

ADMIN, LLM = 'clave-admin-de-prueba-123456', 'clave-llm-de-prueba-1234567'


class Mercado:
    def __init__(self):
        self.filas = rows(random_walk(100, seed=2))
        self.ahora_ms = START + 60 * DAY + 60_000

    def closed_candles(self, simbolo, limit, now_ms):
        return [f for f in self.filas if f[6] <= now_ms][-limit:]

    def filters(self, simbolo):
        return dict(paso_cantidad=0.000001, minimo_quote=1.0, maker=0.0, taker=0.0)

    def ticker(self, simbolo):
        return float(self.filas[60][1])

    def libro(self, simbolos):
        return {s: dict(bid=self.ticker(s), ask=self.ticker(s), ts_ms=self.ahora_ms) for s in simbolos}


class Proponente:
    def proponer(self, contexto, herramientas):
        return llm.Propuesta('comprar', contexto['simbolo'], contexto['fecha_vela'], 'prueba', origen='llm', modelo='falso', latencia_ms=5)


def preparar_modelo(raiz):
    carpeta = raiz / 'models' / 'v1'
    carpeta.mkdir(parents=True)
    contrato = dict(version='v1', tipo='lineal', lookback=5, variables=['ret'], umbral=-1.0, filtro='ninguno', escalador=dict(media=[0.0], desv=[1.0]),
                    y_media=0.0, y_desv=1.0, miembros=[[{'tipo': 'dense', 'activacion': 'linear'}]], valido_para_entrega=False,
                    seleccion=dict(modelo='lineal'))
    (carpeta / 'contrato.json').write_text(json.dumps(contrato), encoding='utf-8')
    import numpy as np
    np.savez(carpeta / 'modelo.npz', m0_c0_w=np.ones((5, 1)), m0_c0_b=np.zeros(1))
    (carpeta / 'experimentos.csv').write_text('capitulo,modelo,RMSE_VA\n7,cero,0.03\n', encoding='utf-8')
    (carpeta / 'diagnostico.json').write_text('[{"modelo": "Base", "mse": 0.1, "varianza": 0.01}]', encoding='utf-8')
    (raiz / 'models' / 'ACTIVO.txt').write_text('v1', encoding='utf-8')


@pytest.fixture
def raiz(tmp_path):
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'riesgo.json').write_text(json.dumps(dict(
        simbolo='BTCUSDT', capital_inicial=50_000.0, comision=0.0, deslizamiento_bps=5.0, exposicion_max=0.8, perdida_diaria_max=0.05, drawdown_max=0.25,
        antiguedad_max_horas=26.0, riesgo_por_operacion=0.02, stop_atr=2.0, objetivo_atr=4.0, trailing_atr=2.0)), encoding='utf-8')
    (tmp_path / 'data').mkdir()
    (tmp_path / 'notas').mkdir()
    return tmp_path


def ajustes(raiz, **kw):
    base = dict(admin_key=ADMIN, llm_key=LLM, raiz=raiz, db=raiz / 'data' / 'bot.sqlite3')
    base.update(kw)
    return Ajustes(**base)


def ollama_falso(req):
    if req.url.path == '/api/chat':
        cuerpo = json.loads(req.content)
        assert cuerpo['stream'] is False and cuerpo['think'] is False
        return httpx.Response(200, json=dict(model=cuerpo['model'], message=dict(role='assistant', content='{"ok": 1}'), total_duration=1_000_000))
    if req.url.path == '/api/version':
        return httpx.Response(200, json=dict(version='0.40.14'))
    if req.url.path == '/api/tags':
        return httpx.Response(200, json=dict(models=[dict(name='qwen3:4b-instruct', digest='abc', size=1)]))
    return httpx.Response(404)


def app_cliente(raiz, con_modelo=True, ollama=ollama_falso, **kw):
    if con_modelo and not (raiz / 'models').exists():
        preparar_modelo(raiz)
    mercado = Mercado()
    app = crear_app(ajustes(raiz, **kw), mercado=mercado, ollama_http=httpx.Client(transport=httpx.MockTransport(ollama)),
                    proponente=Proponente(), hilos=False, pruebas=True, ahora=lambda: mercado.ahora_ms)
    return TestClient(app), app


@pytest.fixture
def cliente(raiz):
    return app_cliente(raiz)[0]


def entrar(c):
    r = c.post('/api/login', json=dict(clave=ADMIN))
    assert r.status_code == 200
    return r


def barrer(c):
    """Un segundo del reflejo, sin hilos de por medio."""
    return c.app.state.ctx.cartera.barrer()


def test_salud_es_publica_y_no_revela_nada(cliente):
    r = cliente.get('/api/salud')
    assert r.status_code == 200 and set(r.json()) == {'ok'}


@pytest.mark.parametrize('metodo,ruta', [('get', '/api/estado'), ('get', '/api/decisiones'), ('get', '/api/ordenes'), ('get', '/api/config'),
                                         ('post', '/api/control/iniciar'), ('post', '/api/control/detener'), ('post', '/api/control/pausar'),
                                         ('post', '/api/control/cerrar-posicion'), ('post', '/api/apagar'), ('put', '/api/config'), ('get', '/api/notas'), ('get', '/api/eventos')])
def test_rutas_protegidas_exigen_sesion(cliente, metodo, ruta):
    assert getattr(cliente, metodo)(ruta).status_code == 401


def test_clave_incorrecta_se_rechaza(cliente):
    assert cliente.post('/api/login', json=dict(clave='mala')).status_code == 401
    assert cliente.post('/api/login', json={}).status_code == 422
    assert cliente.get('/api/estado').status_code == 401


def test_varios_intentos_fallidos_frenan_el_login(cliente):
    for _ in range(5):
        cliente.post('/api/login', json=dict(clave='mala'))
    assert cliente.post('/api/login', json=dict(clave=ADMIN)).status_code == 429


def test_login_correcto_da_cookie_http_only_y_abre_rutas(cliente):
    r = entrar(cliente)
    galleta = r.headers['set-cookie'].lower()
    assert 'httponly' in galleta and 'samesite=strict' in galleta and 'max-age=28800' in galleta and 'path=/' in galleta  # vence a las 8 h
    assert cliente.get('/api/estado').status_code == 200


def test_cerrar_sesion_borra_la_cookie_con_los_mismos_atributos(cliente):
    entrar(cliente)
    galleta = cliente.post('/api/logout').headers['set-cookie'].lower()
    assert 'max-age=0' in galleta and 'httponly' in galleta and 'samesite=strict' in galleta


PUBLICAS = {'/api/salud', '/api/login', '/api/logout'}  # logout solo revoca la cookie que trae: sin sesión no hace nada


def rutas_api(app):
    return [(m, r.path) for r in app.routes if isinstance(r, APIRoute) and r.path.startswith('/api/') for m in r.methods]


def test_toda_ruta_api_pide_sesion_salvo_las_publicas(cliente):
    rutas = rutas_api(cliente.app)
    assert {p for _, p in rutas} >= PUBLICAS and len(rutas) > 30
    abiertas = [(m, p) for m, p in rutas if p not in PUBLICAS and cliente.request(m, p).status_code != 401]
    assert not abiertas


def test_lo_que_cambia_algo_solo_va_por_post_o_put_y_desde_el_panel(cliente):
    entrar(cliente)
    rutas = rutas_api(cliente.app)
    cambian = [(m, p) for m, p in rutas if m not in ('GET', 'HEAD')]
    assert {m for m, _ in cambian} == {'POST', 'PUT'}
    assert {p for _, p in cambian} >= {'/api/control/iniciar', '/api/control/pausar', '/api/control/detener', '/api/control/ciclo',
                                       '/api/control/cerrar-posicion', '/api/apagar', '/api/config', '/api/acceso'}
    for m, p in cambian:
        assert cliente.request(m, p, headers={'Origin': 'https://evil.example', 'Sec-Fetch-Site': 'cross-site'}).status_code == 403, p
    for p in {p for _, p in cambian} - {p for m, p in rutas if m == 'GET'}:
        assert cliente.get(p).status_code == 404, p  # un enlace o una imagen nunca disparan una acción
    assert not cliente.app.state.ctx.parar.is_set() and cliente.get('/api/estado').json()['bot']['estado'] == 'detenido'


def test_cookie_alterada_se_rechaza(cliente):
    entrar(cliente)
    valor = cliente.cookies.get('bot_sesion')
    cliente.cookies.clear()
    cliente.cookies.set('bot_sesion', valor[:-2] + 'xx')
    assert cliente.get('/api/estado').status_code == 401


def test_cerrar_sesion_quita_el_acceso(cliente):
    entrar(cliente)
    cliente.post('/api/logout')
    cliente.cookies.clear()
    assert cliente.get('/api/estado').status_code == 401


def test_iniciar_pausar_y_detener_cambian_el_estado_real(cliente):
    entrar(cliente)
    assert cliente.get('/api/estado').json()['bot']['estado'] == 'detenido'
    assert cliente.post('/api/control/iniciar').json()['estado'] == 'activo'
    assert cliente.post('/api/control/pausar').json()['estado'] == 'pausado'
    assert cliente.post('/api/control/detener').json()['estado'] == 'detenido'


def test_ciclo_manual_no_acelera_ni_duplica_velas(cliente):
    entrar(cliente)
    cliente.post('/api/control/iniciar')
    assert cliente.post('/api/control/ciclo').json()['resultado'] == 'procesada'
    assert cliente.post('/api/control/ciclo').json()['resultado'] == 'sin_velas_nuevas'
    assert cliente.get('/api/ordenes').json() == []  # el ciclo arma la compra; la ejecuta el reflejo
    barrer(cliente)
    barrer(cliente)
    assert len(cliente.get('/api/ordenes').json()) == 1
    assert len(cliente.get('/api/decisiones').json()) == 1


def test_detener_no_liquida_y_cerrar_posicion_es_aparte(cliente):
    entrar(cliente)
    cliente.post('/api/control/iniciar')
    cliente.post('/api/control/ciclo')
    barrer(cliente)
    cliente.post('/api/control/detener')
    assert cliente.get('/api/estado').json()['cuenta']['cantidad'] > 0
    assert cliente.post('/api/control/cerrar-posicion').status_code == 200
    assert cliente.get('/api/estado').json()['cuenta']['cantidad'] == 0
    assert cliente.post('/api/control/cerrar-posicion').status_code == 409


def test_sin_modelo_no_inicia_e_informa(raiz):
    c, _ = app_cliente(raiz, con_modelo=False)
    entrar(c)
    assert c.get('/api/estado').json()['modelo'] is None
    r = c.post('/api/control/iniciar')
    assert r.status_code == 409 and 'modelo' in r.json()['detail']


def test_configuracion_solo_cambia_con_el_bot_detenido(cliente):
    entrar(cliente)
    actual = cliente.get('/api/config').json()
    cliente.post('/api/control/iniciar')
    assert cliente.put('/api/config', json={**actual, 'exposicion_max': 0.5}).status_code == 409
    cliente.post('/api/control/detener')
    assert cliente.put('/api/config', json={**actual, 'exposicion_max': 0.5}).status_code == 200
    assert cliente.get('/api/config').json()['exposicion_max'] == 0.5


def test_configuracion_invalida_se_rechaza(cliente):
    entrar(cliente)
    actual = cliente.get('/api/config').json()
    assert cliente.put('/api/config', json={**actual, 'exposicion_max': 2.0}).status_code == 422
    assert cliente.put('/api/config', json={**actual, 'campo_nuevo': 1}).status_code == 422
    assert cliente.get('/api/config').json()['exposicion_max'] == actual['exposicion_max']


def test_configuracion_cambiada_sobrevive_un_reinicio(raiz):
    c, _ = app_cliente(raiz)
    entrar(c)
    actual = c.get('/api/config').json()
    c.put('/api/config', json={**actual, 'exposicion_max': 0.33})
    c2, _ = app_cliente(raiz)
    entrar(c2)
    assert c2.get('/api/config').json()['exposicion_max'] == 0.33


def test_los_secretos_no_aparecen_en_ninguna_respuesta(cliente):
    entrar(cliente)
    for ruta in ('/api/estado', '/api/config', '/api/sistema', '/api/cerebro', '/api/laboratorio', '/api/errores'):
        texto = cliente.get(ruta).text
        assert ADMIN not in texto and LLM not in texto and 's' * 40 not in texto, ruta


def test_estado_incluye_lo_que_necesita_la_ui(cliente):
    entrar(cliente)
    cliente.post('/api/control/iniciar')
    cliente.post('/api/control/ciclo')
    e = cliente.get('/api/estado').json()
    assert e['modo'] == 'paper' and e['simbolo'] == 'BTCUSDT'
    d = e['ultima_decision']
    assert d['fecha_vela'] and d['pronostico'] is not None and d['accion_final'] and d['justificacion'] is not None
    assert json.loads(d['indicadores'])['rsi14'] is not None
    assert e['cuenta']['patrimonio'] > 0 and 'stop' in e['cuenta']
    assert e['modelo']['valido_para_entrega'] is False


def test_no_existe_ninguna_ruta_de_ordenes_reales(raiz):
    _, app = app_cliente(raiz)
    rutas = [r.path.lower() for r in app.routes]
    assert not [r for r in rutas if 'order' in r or 'real' in r or 'wallet' in r or 'withdraw' in r]


# Gateway privado del LLM
PETICION = dict(model='qwen3:4b-instruct', messages=[dict(role='user', content='hola')])


def test_gateway_rechaza_clave_ausente_o_incorrecta(cliente):
    assert cliente.post('/llm/chat', json=PETICION).status_code == 401
    assert cliente.post('/llm/chat', json=PETICION, headers={'X-LLM-Key': 'mala'}).status_code == 401


def test_la_sesion_del_panel_no_sirve_como_clave_del_llm(cliente):
    entrar(cliente)
    assert cliente.post('/llm/chat', json=PETICION).status_code == 401


def test_gateway_con_clave_correcta_consulta_ollama_local(cliente):
    r = cliente.post('/llm/chat', json=PETICION, headers={'X-LLM-Key': LLM})
    assert r.status_code == 200
    d = r.json()
    assert d['message']['content'] == '{"ok": 1}' and d['modelo'] == 'qwen3:4b-instruct' and d['latencia_ms'] >= 0


@pytest.mark.parametrize('modelo', ['qwen3:cloud', 'gpt-oss:120b-cloud', 'otro-modelo', '../../etc'])
def test_gateway_rechaza_modelos_no_permitidos(cliente, modelo):
    r = cliente.post('/llm/chat', json={**PETICION, 'model': modelo}, headers={'X-LLM-Key': LLM})
    assert r.status_code == 403


def test_gateway_informa_si_ollama_esta_detenido(raiz):
    def caido(req):
        raise httpx.ConnectError('rechazada')

    c, _ = app_cliente(raiz, ollama=caido)
    r = c.post('/llm/chat', json=PETICION, headers={'X-LLM-Key': LLM})
    assert r.status_code == 503 and 'Ollama' in r.json()['detail']


def test_ajustes_rechazan_ollama_fuera_de_la_laptop(raiz):
    with pytest.raises(ValueError, match='local'):
        ajustes(raiz, ollama_url='https://ollama.com').validar()


@pytest.mark.parametrize('campo', ['admin_key', 'llm_key'])
def test_ajustes_exigen_claves_largas(raiz, campo):
    with pytest.raises(ValueError, match=campo):
        ajustes(raiz, **{campo: 'corta'}).validar()


# Datos del panel
def test_cerebro_describe_agentes_reales_con_su_estado(cliente):
    entrar(cliente)
    d = cliente.get('/api/cerebro').json()
    ids = {n['id'] for n in d['nodos']}
    assert {'mexc_velas', 'modelo', 'ollama', 'riesgo', 'reflejo', 'ejecutar', 'cuenta'} <= ids
    assert all(n['estado'] in ('activo', 'atencion', 'detenido', 'reposo') for n in d['nodos'])
    assert all(e['origen'] in ids and e['destino'] in ids for e in d['enlaces'])
    assert {g for g in (n['grupo'] for n in d['nodos'])} >= {'Percepción', 'Modelo', 'Cerebro LLM', 'Núcleo determinista', 'Laboratorio'}


def test_cerebro_marca_ollama_detenido_si_no_responde(raiz):
    def caido(req):
        raise httpx.ConnectError('rechazada')

    c, _ = app_cliente(raiz, ollama=caido)
    entrar(c)
    nodos = {n['id']: n for n in c.get('/api/cerebro').json()['nodos']}
    assert nodos['ollama']['estado'] == 'detenido'


def test_laboratorio_entrega_experimentos_y_diagnostico(cliente):
    entrar(cliente)
    d = cliente.get('/api/laboratorio').json()
    assert d['experimentos'][0]['modelo'] == 'cero' and d['diagnostico'][0]['modelo'] == 'Base'


def test_notas_se_leen_y_se_guardan_desde_el_panel(cliente):
    entrar(cliente)
    r = cliente.post('/api/notas', json=dict(titulo='Una', cuerpo='Ver [[Dos]]', origen='alex', tipo='Decisión', galaxia='Riesgo'))
    assert r.status_code == 200
    cliente.post('/api/notas', json=dict(titulo='Dos', cuerpo='texto', origen='claude', tipo='Código', galaxia='Riesgo'))
    d = cliente.get('/api/notas').json()
    assert len(d['notas']) == 2 and len(d['enlaces']) == 1
    assert d['resumen']['hecho']


def test_notas_rechazan_secretos(cliente):
    entrar(cliente)
    r = cliente.post('/api/notas', json=dict(titulo='Mala', cuerpo='password = hunter2222', origen='alex', tipo='Decisión', galaxia='Riesgo'))
    assert r.status_code == 422


def test_comparacion_resume_cada_corrida(cliente):
    entrar(cliente)
    cliente.post('/api/control/iniciar')
    cliente.post('/api/control/ciclo')
    d = cliente.get('/api/comparacion').json()
    fila = next(r for r in d if r['run'] == 'live')
    assert fila['ciclos'] == 1 and fila['tipo'] == 'live' and 'rendimiento' in fila and 'comprar_y_mantener' in fila


def test_bus_de_eventos_entrega_a_suscriptores_y_cuenta_por_nodo():
    async def prueba():
        ev = Eventos()
        cola, registro = ev.suscribir()
        ev.emitir('modelo', 'analista', tipo='decision', detalle='x')
        e = await asyncio.wait_for(cola.get(), 1)
        ev.cancelar(registro)
        return e, ev

    e, ev = asyncio.run(prueba())
    assert e['origen'] == 'modelo' and e['tipo'] == 'decision'
    assert ev.conteo['analista'] == 1 and ev.ultimo_por_nodo['modelo']['tipo'] == 'decision'


def test_radar_muestra_cada_activo_con_sus_condiciones_y_la_latencia(cliente):
    entrar(cliente)
    cliente.post('/api/control/iniciar')
    cliente.post('/api/control/ciclo')
    assert cliente.get('/api/radar').json()['filas'][0]['simbolo'] == 'BTCUSDT'
    barrer(cliente)
    d = cliente.get('/api/radar').json()
    assert d['filas'][0]['estado'] == 'en_posicion'
    assert d['estadisticas']['barridos'] == 1 and d['estadisticas']['activos'] == 1
    assert d['resumen']['posiciones'] == 1


def test_radar_exige_sesion(cliente):
    assert cliente.get('/api/radar').status_code == 401


def test_universo_reparte_el_capital_entre_sus_activos(raiz):
    (raiz / 'config' / 'universo.json').write_text(json.dumps(dict(simbolos=['BTCUSDT', 'ETHUSDT'])), encoding='utf-8')
    c, app = app_cliente(raiz)
    entrar(c)
    assert list(app.state.ctx.cartera.agentes) == ['BTCUSDT']  # ETH no tiene modelo conjunto: queda fuera y se informa
    assert app.state.ctx.cartera.sin_modelo == ['ETHUSDT']
    assert c.get('/api/estado').json()['cartera']['sin_modelo'] == ['ETHUSDT']


def test_con_modelo_conjunto_entran_todos_los_activos(raiz):
    preparar_modelo(raiz)
    (raiz / 'models' / 'CARTERA.txt').write_text('v1', encoding='utf-8')
    (raiz / 'config' / 'universo.json').write_text(json.dumps(dict(simbolos=['BTCUSDT', 'ETHUSDT'])), encoding='utf-8')
    c, app = app_cliente(raiz)
    entrar(c)
    assert list(app.state.ctx.cartera.agentes) == ['BTCUSDT', 'ETHUSDT']
    e = c.get('/api/estado?simbolo=ETHUSDT').json()
    assert e['simbolo'] == 'ETHUSDT' and e['cuenta']['capital_inicial'] == 25_000 and e['cartera']['patrimonio'] == 50_000
    assert c.post('/api/control/cerrar-posicion?simbolo=NOEXISTE').status_code == 404


def test_estado_de_activo_desconocido_vuelve_al_principal(cliente):
    entrar(cliente)
    assert cliente.get('/api/estado?simbolo=NOEXISTE').json()['simbolo'] == 'BTCUSDT'


def test_hilo_de_velas_pausa_un_par_retirado_sin_repetir_el_error(raiz):
    """MEXC ya no lista DASHUSDT: al arrancar, el hilo de velas lo deja en pausa con su motivo en vez de registrar el fallo cada 6 horas."""
    preparar_modelo(raiz)
    (raiz / 'models' / 'CARTERA.txt').write_text('v1', encoding='utf-8')
    (raiz / 'config' / 'universo.json').write_text(json.dumps(dict(simbolos=['BTCUSDT', 'DASHUSDT'])), encoding='utf-8')
    mercado = Mercado()
    velas = mercado.closed_candles

    def closed_candles(simbolo, limit, now_ms):
        if simbolo == 'DASHUSDT':
            raise mexc.ParRetirado('MEXC ya no lista DASHUSDT: responde «Invalid symbol» (código -1121).')
        return velas(simbolo, limit, now_ms)

    mercado.closed_candles = closed_candles
    app = crear_app(ajustes(raiz), mercado=mercado, ollama_http=httpx.Client(transport=httpx.MockTransport(ollama_falso)), proponente=Proponente(), pruebas=True, ahora=lambda: mercado.ahora_ms)
    ctx = app.state.ctx
    ctx.cartera.iniciar()  # el bot estaba activo antes de reiniciar
    dash = ctx.cartera.agentes['DASHUSDT']
    with TestClient(app):  # arranca los hilos
        limite = time.monotonic() + 10
        while dash.estado != 'pausado' and time.monotonic() < limite:
            time.sleep(0.05)
    assert dash.estado == 'pausado' and 'ya no lista' in dash.motivo
    assert ctx.cartera.agentes['BTCUSDT'].estado == 'activo'
    assert [e['etapa'] for e in ctx.store.errores()] == ['datos']


def test_apagar_con_sesion_detiene_los_hilos_y_cierra_el_proceso(raiz):
    import threading
    cerrado = threading.Event()
    mercado = Mercado()
    if not (raiz / 'models').exists():
        preparar_modelo(raiz)
    app = crear_app(ajustes(raiz), mercado=mercado, ollama_http=httpx.Client(transport=httpx.MockTransport(ollama_falso)), proponente=Proponente(), hilos=False, pruebas=True, ahora=lambda: mercado.ahora_ms, salir=cerrado.set)
    c = TestClient(app)
    entrar(c)
    assert c.post('/api/apagar').status_code == 200
    assert app.state.ctx.parar.is_set()
    assert cerrado.wait(3)


def test_la_api_queda_documentada_solo_para_quien_inicio_sesion(cliente):
    # La API está documentada, pero por seguridad no es pública.
    assert cliente.get('/api/openapi.json').status_code == 401
    entrar(cliente)
    esquema = cliente.get('/api/openapi.json').json()
    rutas = {r.path for r in cliente.app.routes if getattr(r, 'include_in_schema', False) and r.path.startswith(('/api/', '/llm/'))}
    assert len(rutas) > 20 and rutas <= set(esquema['paths'])
    sin_descripcion = [f'{m.upper()} {p}' for p, ops in esquema['paths'].items() for m, op in ops.items() if not op.get('description')]
    assert not sin_descripcion, sin_descripcion


def test_la_base_se_elige_con_bot_db_y_por_defecto_va_en_data(monkeypatch, tmp_path):
    from bot import config
    claves = dict(BOT_ADMIN_KEY=ADMIN, BOT_LLM_KEY=LLM)
    monkeypatch.setattr(config, 'leer_env', lambda: claves)
    assert config.cargar_ajustes().db == config.RAIZ / 'data' / 'bot.sqlite3'
    monkeypatch.setattr(config, 'leer_env', lambda: claves | dict(BOT_DB=str(tmp_path / 'otra.sqlite3')))
    assert config.cargar_ajustes().db == tmp_path / 'otra.sqlite3'
    monkeypatch.setattr(config, 'leer_env', lambda: claves | dict(BOT_DB='data/prueba.sqlite3'))
    assert config.cargar_ajustes().db == config.RAIZ / 'data' / 'prueba.sqlite3'  # relativa a la carpeta del proyecto


def test_sin_hilos_no_se_abre_el_host_de_pruebas(raiz):
    """El host de pruebas solo se acepta si se pide explícitamente, no por apagar los hilos."""
    if not (raiz / 'models').exists():
        preparar_modelo(raiz)
    app = crear_app(ajustes(raiz), mercado=Mercado(), ollama_http=httpx.Client(transport=httpx.MockTransport(ollama_falso)), proponente=Proponente(), hilos=False)
    assert TestClient(app).get('/api/salud').status_code == 403



def test_modelo_danado_pausa_sus_activos_sin_usar_otro_modelo(raiz):
    import numpy as np
    preparar_modelo(raiz)
    danado = raiz / 'models' / 'v2'
    danado.mkdir()
    contrato = json.loads((raiz / 'models' / 'v1' / 'contrato.json').read_text(encoding='utf-8')) | dict(version='v2')
    (danado / 'contrato.json').write_text(json.dumps(contrato), encoding='utf-8')
    np.savez(danado / 'modelo.npz', m0_c0_w=np.full((5, 1), np.nan), m0_c0_b=np.zeros(1))
    (raiz / 'models' / 'ACTIVO.txt').write_text('v2', encoding='utf-8')
    (raiz / 'models' / 'CARTERA.txt').write_text('v1', encoding='utf-8')
    (raiz / 'config' / 'universo.json').write_text(json.dumps(dict(simbolos=['BTCUSDT', 'ETHUSDT'])), encoding='utf-8')
    c, app = app_cliente(raiz)
    entrar(c)
    assert c.post('/api/control/iniciar').status_code == 200
    agentes = app.state.ctx.cartera.agentes
    assert agentes['BTCUSDT'].estado == 'pausado' and 'v2' in agentes['BTCUSDT'].motivo  # no cae en el modelo de la cartera
    assert agentes['ETHUSDT'].estado == 'activo'
    e = c.get('/api/estado').json()
    assert e['modelo'] is None and any('v2' in a['motivo'] for a in e['alertas'])


def test_en_vivo_cuadra_con_la_cartera_aunque_un_activo_haya_salido(raiz):
    from bot.paper import Cuenta
    from bot.store import Store
    viejo = Store(raiz / 'data' / 'bot.sqlite3')
    viejo.abrir_run('live:VIEJOUSDT', 'live', 'VIEJOUSDT')  # salió del universo y conserva su efectivo
    viejo.marcar_patrimonio('live:VIEJOUSDT', 1, '2020-01-01', Cuenta(efectivo=10_000.0), 1.0)
    c, _ = app_cliente(raiz)
    entrar(c)
    c.post('/api/control/iniciar')
    c.post('/api/control/ciclo')
    vivo = next(r for r in c.get('/api/comparacion').json() if r['run'] == 'live')
    patrimonio = c.get('/api/estado').json()['cartera']['patrimonio']
    assert vivo['activos'] == 1 and vivo['patrimonio_final'] == pytest.approx(patrimonio)
    assert c.get('/api/patrimonio').json()[-1]['patrimonio'] == pytest.approx(patrimonio)


def test_en_vivo_dice_que_activo_salio_con_operaciones_cerradas(raiz):
    """Un activo que salió ya no suma al patrimonio; el resumen lo nombra para que Resumen y Operaciones cuadren."""
    from bot.store import Store
    viejo = Store(raiz / 'data' / 'bot.sqlite3')
    viejo.abrir_run('live:VIEJOUSDT', 'live', 'VIEJOUSDT')
    viejo.guardar_orden('live:VIEJOUSDT', None, 1, 'comprar', 'ejecutada', 'senal', 1.0, 10.0, 0.01)
    viejo.guardar_orden('live:VIEJOUSDT', None, 2, 'vender', 'ejecutada', 'stop', 1.0, 9.0, 0.01, -1.02)
    c, _ = app_cliente(raiz)
    entrar(c)
    c.post('/api/control/iniciar')
    vivo = next(r for r in c.get('/api/comparacion').json() if r['run'] == 'live')
    assert vivo['salidos'] == [dict(simbolo='VIEJOUSDT', operaciones=1, resultado=pytest.approx(-1.02))]
