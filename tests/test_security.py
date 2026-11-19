"""Comprobaciones locales con claves ficticias y transporte simulado."""
import hashlib
import httpx
import asyncio
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from tests.test_api import raiz, cliente, app_cliente, entrar, ADMIN, LLM, PETICION
from bot.config import RAIZ
from bot.security import LimiteIntentos, Sesiones
from bot.store import Store

CABECERAS = {'x-content-type-options': 'nosniff', 'x-frame-options': 'DENY', 'referrer-policy': 'no-referrer',
             'cross-origin-opener-policy': 'same-origin', 'cross-origin-resource-policy': 'same-origin'}


def revisar_cabeceras(r):
    for nombre, valor in CABECERAS.items():
        assert r.headers.get(nombre) == valor, (r.status_code, nombre)
    csp = r.headers['content-security-policy']
    assert "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp, csp
    for directiva in ("default-src 'self'", "script-src 'self'", "style-src 'self'", "frame-ancestors 'none'", "object-src 'none'", "base-uri 'none'"):
        assert directiva in csp, directiva
    for funcion in ('camera', 'microphone', 'geolocation', 'payment', 'usb', 'serial', 'hid'):
        assert f'{funcion}=()' in r.headers['permissions-policy'], funcion


def test_cabeceras_de_seguridad_en_cada_tipo_de_respuesta(raiz):
    dist = raiz / 'frontend' / 'dist'
    (dist / 'assets').mkdir(parents=True)
    (dist / 'index.html').write_text('<!doctype html><title>Astrolabio</title>', encoding='utf-8')
    (dist / 'assets' / 'app.js').write_text('console.log(1)', encoding='utf-8')
    _, app = app_cliente(raiz)
    c = TestClient(app, raise_server_exceptions=False)
    respuestas = {'panel': c.get('/'), 'archivo': c.get('/assets/app.js'), 'salud': c.get('/api/salud'), 'sin sesión': c.get('/api/estado'),
                  'otro origen': c.post('/api/login', json={'clave': 'x'}, headers={'Origin': 'https://evil.example'}),
                  'no existe': c.get('/api/no-existe'), 'otro método': c.delete('/api/salud'), 'inválida': c.post('/api/login', json={})}
    entrar(c)
    app.state.ctx.store.errores = lambda: 1 / 0  # una falla que nadie previó
    respuestas['falla'] = c.get('/api/errores')
    assert [r.status_code for r in respuestas.values()] == [200, 200, 200, 401, 403, 404, 405, 422, 500]
    for r in respuestas.values():
        revisar_cabeceras(r)


def test_un_error_inesperado_no_muestra_trazas_ni_rutas(raiz):
    _, app = app_cliente(raiz)
    c = TestClient(app, raise_server_exceptions=False)
    entrar(c)

    def falla():
        raise FileNotFoundError(2, 'No such file or directory', str(raiz / 'models' / 'pesos-privados.npz'))
    app.state.ctx.store.errores = falla
    r = c.get('/api/errores')
    assert r.status_code == 500 and set(r.json()) == {'detail'}
    assert 'pesos-privados' not in r.text and 'Traceback' not in r.text and 'FileNotFoundError' not in r.text


def test_los_errores_del_panel_no_muestran_rutas_del_disco(cliente):
    entrar(cliente)
    ruta = RAIZ / 'models' / 'v9' / 'modelo.npz'
    store = cliente.app.state.ctx.store
    store.registrar_error('reflejo', str(FileNotFoundError(2, 'No such file or directory', str(ruta))), 'FileNotFoundError')  # con barras dobles, como repr()
    store.registrar_error('modelo', f'No existe {ruta}: copia ahí el modelo.', 'DataError')
    store.registrar_error('datos', f'Falta {Path.home() / "Downloads" / "velas.csv"}.', 'DataError')
    store.registrar_error('datos', f'Ruta rara "{RAIZ}\\" sin cerrar', 'DataError')  # una barra pegada a unas comillas no debe romper el JSON
    store.registrar_error('datos', '\x1c' + str(RAIZ)[1:], 'DataError')  # en JSON es \u001c: su «c» no puede pasar por la unidad C:
    textos = [f['error'] for f in cliente.get('/api/errores').json()]
    for carpeta in (RAIZ, Path.home()):
        for forma in (str(carpeta), str(carpeta).replace('\\', '\\\\'), str(carpeta).replace('\\', '/')):
            assert not [t for t in textos if forma.lower() in t.lower()], forma
    assert any('modelo.npz' in t for t in textos) and any('velas.csv' in t for t in textos)  # el archivo se sigue nombrando


def test_el_bloqueo_es_por_ip_y_dice_cuanto_esperar(raiz):
    _, app = app_cliente(raiz)
    intruso, alex = TestClient(app, client=('10.0.0.66', 5000)), TestClient(app, client=('127.0.0.1', 5001))
    for _ in range(5):
        assert intruso.post('/api/login', json={'clave': 'mala'}).status_code == 401
    r = intruso.post('/api/login', json={'clave': ADMIN})
    assert r.status_code == 429 and 0 < int(r.headers['retry-after']) <= 30
    assert f"{r.headers['retry-after']} s" in r.json()['detail']
    assert alex.post('/api/login', json={'clave': ADMIN}).status_code == 200  # otra IP sigue entrando


def test_el_servidor_no_cree_en_x_forwarded_for(monkeypatch):
    """Todo cliente llega desde 127.0.0.1: si uvicorn creyera esa cabecera, cambiarla en cada intento se saltaría el límite por IP."""
    from types import SimpleNamespace
    from bot import __main__ as arranque
    llamada = {}
    monkeypatch.setattr(arranque, 'cargar_ajustes', lambda: SimpleNamespace(sin_suspender=False, puerto=8770))
    monkeypatch.setattr(arranque, 'crear_app', lambda ajustes: 'app')
    monkeypatch.setattr(arranque.uvicorn, 'run', lambda app, **opciones: llamada.update(opciones))
    monkeypatch.setattr(arranque.sys, 'argv', ['bot', '--sin-navegador'])
    arranque.main()
    assert llamada['host'] == '127.0.0.1' and llamada.get('proxy_headers') is False


def test_el_bloqueo_vence_y_un_acierto_borra_los_fallos(monkeypatch):
    reloj = [100.0]
    monkeypatch.setattr('bot.security.time.monotonic', lambda: reloj[0])
    limite = LimiteIntentos(maximo=2, bloqueo_s=30)
    assert [limite.registrar('ip'), limite.registrar('ip'), limite.registrar('ip')] == [0, 0, 30]
    reloj[0] = 130.5
    assert limite.registrar('ip') == 0  # el bloqueo venció: empieza otra ronda
    limite.acierto('ip')
    assert [limite.registrar('ip'), limite.registrar('ip'), limite.registrar('ip')] == [0, 0, 30]


def test_intentos_simultaneos_no_se_saltan_el_limite(raiz, monkeypatch):
    _, app = app_cliente(raiz)

    def comprobar_lento(clave, datos):
        time.sleep(0.3)  # como un scrypt lento: los intentos se comprueban todos a la vez
        return False
    monkeypatch.setattr('bot.api.clave_coincide', comprobar_lento)
    with ThreadPoolExecutor(12) as hilos:
        codigos = list(hilos.map(lambda _: TestClient(app).post('/api/login', json={'clave': 'mala'}).status_code, range(12)))
    assert sorted(codigos) == [401] * 5 + [429] * 7


def test_el_mensaje_no_dice_si_hay_contrasena_personal(cliente):
    sin_personal = cliente.post('/api/login', json={'clave': 'mala-1'})
    entrar(cliente)
    assert cliente.put('/api/acceso', json={'actual': ADMIN, 'nueva': 'cielo-de-astrolabio-2026'}).status_code == 200
    cliente.post('/api/logout')
    con_personal = cliente.post('/api/login', json={'clave': 'mala-2'})
    assert (sin_personal.status_code, sin_personal.json()) == (con_personal.status_code, con_personal.json()) == (401, {'detail': 'Clave incorrecta.'})


def test_una_clave_mala_cuesta_lo_mismo_con_o_sin_contrasena_personal(cliente, monkeypatch):
    from bot import api
    comparadas = []
    original = api.clave_coincide
    monkeypatch.setattr('bot.api.clave_coincide', lambda clave, datos: comparadas.append(datos) or original(clave, datos))
    assert cliente.post('/api/login', json={'clave': 'mala'}).status_code == 401
    assert comparadas and comparadas[0] and comparadas[0]['algoritmo'] == 'scrypt'  # sin contraseña personal compara con una huella señuelo


def test_una_ruta_unc_nunca_se_abre_desde_el_servidor(raiz, monkeypatch):
    dist = raiz / 'frontend' / 'dist'
    dist.mkdir(parents=True)
    (dist / 'index.html').write_text('<!doctype html><title>Astrolabio</title>', encoding='utf-8')
    c, _ = app_cliente(raiz)
    tocadas = []
    for metodo in ('resolve', 'is_file', 'exists'):
        monkeypatch.setattr(Path, metodo, lambda self, *a, _o=getattr(Path, metodo), **k: tocadas.append(str(self)) or _o(self, *a, **k))
    r = c.get('/%5C%5Cejemplo.invalid%5Ccarpeta%5Cx.js')  # en Windows, abrir \\host\... manda la huella NTLM a ese host
    assert r.status_code == 200 and 'Astrolabio' in r.text
    assert not [t for t in tocadas if t.startswith(('\\\\', '//'))]


def test_cambiar_la_contrasena_comparte_el_limite_de_intentos(cliente):
    entrar(cliente)
    for _ in range(5):
        assert cliente.put('/api/acceso', json={'actual': 'mala', 'nueva': 'cielo-de-astrolabio-2026'}).status_code == 403
    assert cliente.put('/api/acceso', json={'actual': ADMIN, 'nueva': 'cielo-de-astrolabio-2026'}).status_code == 429
    assert cliente.post('/api/login', json={'clave': ADMIN}).status_code == 429


def estado_con(c, token):
    """Pide el estado con la cookie de sesión indicada, como haría el navegador tras un reinicio."""
    c.cookies.set('bot_sesion', token)
    return c.get('/api/estado').status_code


def filas_sesiones(ruta):
    with closing(sqlite3.connect(ruta)) as db:
        return db.execute('SELECT huella, vence FROM sesiones').fetchall()


def test_la_sesion_sigue_valida_tras_reiniciar(raiz):
    c, _ = app_cliente(raiz)
    entrar(c)
    reiniciado, _ = app_cliente(raiz)  # app nueva sobre la misma base, como tras un reinicio
    assert estado_con(reiniciado, c.cookies.get('bot_sesion')) == 200


def test_cerrar_sesion_la_revoca_tambien_tras_reiniciar(raiz):
    c, _ = app_cliente(raiz)
    entrar(c)
    token = c.cookies.get('bot_sesion')
    c.post('/api/logout')
    reiniciado, _ = app_cliente(raiz)
    assert estado_con(reiniciado, token) == 401


def test_cambiar_contrasena_cierra_las_demas_tambien_tras_reiniciar(raiz):
    _, app = app_cliente(raiz)
    propia, otra = TestClient(app), TestClient(app)
    entrar(propia)
    entrar(otra)
    assert propia.put('/api/acceso', json={'actual': ADMIN, 'nueva': 'cielo-de-astrolabio-2026'}).status_code == 200
    reiniciado, _ = app_cliente(raiz)
    assert [estado_con(reiniciado, c.cookies.get('bot_sesion')) for c in (propia, otra)] == [200, 401]


def test_sesion_restaurada_vence_a_su_hora_y_se_borra_de_la_base(tmp_path, monkeypatch):
    reloj = [100]
    monkeypatch.setattr('bot.security.time.time', lambda: reloj[0])
    base = tmp_path / 'b.sqlite3'
    token = Sesiones(duracion=10, store=Store(base)).crear()
    reloj[0] = 105
    restaurada = Sesiones(duracion=10, store=Store(base))
    assert restaurada.valida(token)
    reloj[0] = 111  # vence a las 110, la hora del login + 10, aunque el reinicio fue a las 105
    assert not restaurada.valida(token)
    assert not Sesiones(duracion=10, store=Store(base)).valida(token)
    assert filas_sesiones(base) == []


def test_la_base_guarda_la_huella_del_token_y_nunca_el_token(raiz):
    c, _ = app_cliente(raiz)
    entrar(c)
    token = c.cookies.get('bot_sesion')
    assert [h for h, _ in filas_sesiones(raiz / 'data' / 'bot.sqlite3')] == [hashlib.sha256(token.encode()).hexdigest()]
    for archivo in (raiz / 'data').glob('bot.sqlite3*'):
        assert token.encode() not in archivo.read_bytes(), archivo.name


def test_logout_revoca_incluso_una_copia_de_la_cookie(cliente):
    entrar(cliente)
    anterior = cliente.cookies.get('bot_sesion')
    cliente.post('/api/logout')
    cliente.cookies.clear()
    cliente.cookies.set('bot_sesion', anterior)
    assert cliente.get('/api/estado').status_code == 401


def test_sesiones_independientes_y_caducidad(monkeypatch):
    monkeypatch.setattr('bot.security.time.time', lambda: 100)
    s = Sesiones(duracion=10)
    a, b = s.crear(), s.crear()
    assert a != b and s.valida(a) and s.valida(b)
    s.revocar(a)
    assert not s.valida(a) and s.valida(b)
    monkeypatch.setattr('bot.security.time.time', lambda: 111)
    assert not s.valida(b)


def test_host_externo_y_origen_cruzado_no_pueden_iniciar(cliente):
    entrar(cliente)
    for headers in ({'Host': 'evil.example'}, {'Origin': 'https://evil.example'}, {'Origin': 'null'}, {'Sec-Fetch-Site': 'cross-site'}, {'Origin': 'http://testserver:9999'}):
        assert cliente.post('/api/control/iniciar', headers=headers).status_code == 403
    assert cliente.get('/api/estado').json()['bot']['estado'] == 'detenido'
    assert cliente.post('/api/control/iniciar', headers={'Origin': 'http://testserver', 'Sec-Fetch-Site': 'same-origin'}).status_code == 200


def test_errores_de_validacion_no_reflejan_claves(cliente):
    r = cliente.post('/api/login', json={'clave': {'secreto': ADMIN}})
    assert r.status_code == 422 and ADMIN not in r.text and 'secreto' not in r.text


def test_error_proveedor_no_refleja_cuerpo(raiz):
    c, _ = app_cliente(raiz, ollama=lambda req: httpx.Response(500, text=LLM))
    r = c.post('/llm/chat', json=PETICION, headers={'X-LLM-Key': LLM})
    assert r.status_code == 502 and LLM not in r.text


def test_cabeceras_y_documentacion_no_publica(cliente):
    r = cliente.get('/api/estado')
    assert r.headers['cache-control'] == 'no-store'
    assert r.headers['x-frame-options'] == 'DENY'
    assert r.headers['x-content-type-options'] == 'nosniff'
    assert "frame-ancestors 'none'" in r.headers['content-security-policy']
    assert cliente.get('/api/openapi.json').status_code == 401  # solo con sesión
    assert cliente.get('/api/docs').status_code == 404


def test_evento_pendiente_no_sale_despues_de_logout(cliente):
    entrar(cliente)
    token = cliente.cookies.get('bot_sesion')
    endpoint = next(r.endpoint for r in cliente.app.routes if r.path == '/api/eventos')

    async def comprobar():
        async def recibir():
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        request = Request({'type': 'http', 'method': 'GET', 'path': '/api/eventos',
                           'headers': [(b'cookie', f'bot_sesion={token}'.encode())]}, receive=recibir)
        respuesta = await endpoint(request)
        pendiente = asyncio.create_task(anext(respuesta.body_iterator))
        # Dejar que el generador se suscriba y espere un evento, sin esperas de reloj.
        for _ in range(20):
            await asyncio.sleep(0)
            if cliente.app.state.ctx.eventos._colas:
                break
        assert cliente.app.state.ctx.eventos._colas
        cliente.post('/api/logout')
        cliente.app.state.ctx.eventos.emitir('prueba', 'panel', detalle='evento privado ficticio')
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(pendiente, timeout=2)
        assert not cliente.app.state.ctx.eventos._colas
    asyncio.run(comprobar())
