"""Contraseña personal del panel: se guarda solo su huella y la clave de .env queda como recuperación."""
import json

from fastapi.testclient import TestClient

from tests.test_api import ADMIN, app_cliente, cliente, entrar, raiz  # noqa: F401

NUEVA = 'cielo-de-astrolabio-2026'


def test_sin_contrasena_personal_solo_entra_la_clave_del_env(cliente):
    assert cliente.post('/api/login', json={'clave': NUEVA}).status_code == 401
    entrar(cliente)
    assert cliente.get('/api/acceso').json()['personal'] is False


def test_configurarla_exige_sesion_y_la_clave_actual(cliente):
    assert cliente.put('/api/acceso', json={'actual': ADMIN, 'nueva': NUEVA}).status_code == 401
    entrar(cliente)
    r = cliente.put('/api/acceso', json={'actual': 'no-es-la-clave', 'nueva': NUEVA})
    assert r.status_code == 403 and NUEVA not in r.text
    assert cliente.get('/api/acceso').json()['personal'] is False


def test_una_contrasena_corta_se_rechaza_sin_reflejarla(cliente):
    entrar(cliente)
    r = cliente.put('/api/acceso', json={'actual': ADMIN, 'nueva': 'abc123xyz'})
    assert r.status_code == 422 and 'abc123xyz' not in r.text


def test_tras_reiniciar_entran_la_contrasena_y_la_clave_de_recuperacion(raiz):
    c, _ = app_cliente(raiz)
    entrar(c)
    r = c.put('/api/acceso', json={'actual': ADMIN, 'nueva': NUEVA})
    assert r.status_code == 200 and c.get('/api/acceso').json()['personal'] is True
    reiniciado, _ = app_cliente(raiz)  # misma base, sesiones nuevas
    assert reiniciado.post('/api/login', json={'clave': NUEVA}).status_code == 200
    assert reiniciado.post('/api/login', json={'clave': ADMIN}).status_code == 200
    assert reiniciado.post('/api/login', json={'clave': 'cielo-de-astrolabio-2025'}).status_code == 401


def test_se_puede_cambiar_usando_la_contrasena_personal(cliente):
    entrar(cliente)
    cliente.put('/api/acceso', json={'actual': ADMIN, 'nueva': NUEVA})
    assert cliente.put('/api/acceso', json={'actual': NUEVA, 'nueva': NUEVA + '-b'}).status_code == 200
    assert cliente.post('/api/login', json={'clave': NUEVA}).status_code == 401
    assert cliente.post('/api/login', json={'clave': NUEVA + '-b'}).status_code == 200


def test_la_base_guarda_una_huella_con_sal_y_nunca_la_contrasena(raiz):
    c, app = app_cliente(raiz)
    entrar(c)
    c.put('/api/acceso', json={'actual': ADMIN, 'nueva': NUEVA})
    datos = app.state.ctx.store.cargar_acceso()
    assert datos['algoritmo'] == 'scrypt' and len(bytes.fromhex(datos['sal'])) == 16
    assert NUEVA not in json.dumps(datos)
    for archivo in (raiz / 'data').glob('bot.sqlite3*'):
        assert NUEVA.encode() not in archivo.read_bytes(), archivo.name


def test_cambiarla_cierra_las_demas_sesiones(raiz):
    _, app = app_cliente(raiz)
    propia, otra = TestClient(app), TestClient(app)
    entrar(propia)
    entrar(otra)
    assert propia.put('/api/acceso', json={'actual': ADMIN, 'nueva': NUEVA}).status_code == 200
    assert propia.get('/api/estado').status_code == 200
    assert otra.get('/api/estado').status_code == 401
