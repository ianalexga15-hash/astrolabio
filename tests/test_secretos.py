"""Ninguna clave de .env ni huella del panel aparece en lo que git versionaría."""
import sqlite3
import subprocess
from pathlib import Path

import pytest

from scripts.revisar_secretos import hallazgos, secretos

RAIZ = Path(__file__).resolve().parent.parent


def archivos_con(valores, archivos):
    return [str(a) for a in archivos if a.is_file() and any(v in a.read_bytes() for v in valores)]


def test_detecta_una_clave_copiada_en_un_archivo(tmp_path):
    claves = secretos(env={'BOT_ADMIN_KEY': 'clave-de-prueba-larga-123', 'BOT_PORT': '8770'}, base=tmp_path / 'sin-base.sqlite3')
    limpio, sucio = tmp_path / 'a.txt', tmp_path / 'b.txt'
    limpio.write_text('nada', encoding='utf-8')
    sucio.write_text('x clave-de-prueba-larga-123 x', encoding='utf-8')
    assert claves == {'BOT_ADMIN_KEY': b'clave-de-prueba-larga-123'}
    assert archivos_con(claves.values(), [limpio, sucio]) == [str(sucio)]


def test_tambien_vigila_las_claves_de_la_cuenta_mexc_y_las_huellas_del_panel(tmp_path):
    base = tmp_path / 'bot.sqlite3'
    db = sqlite3.connect(base)
    db.executescript("""CREATE TABLE acceso(id INTEGER PRIMARY KEY, creado TEXT, datos TEXT);
        CREATE TABLE sesiones(huella TEXT PRIMARY KEY, vence REAL);
        INSERT INTO acceso VALUES(1, 'hoy', '{"sal": "ab12", "huella": "cd34"}');
        INSERT INTO sesiones VALUES('ef56', 1);""")
    db.close()
    env = {'MEXC_API_KEY': 'mx0vglclave-de-prueba-1234', 'MEXC_API_SECRET': 'secreto-de-prueba-larga-5678'}
    assert secretos(env=env, base=base) == {'MEXC_API_KEY': b'mx0vglclave-de-prueba-1234', 'MEXC_API_SECRET': b'secreto-de-prueba-larga-5678',
                                           'huella de la contraseña': b'cd34', 'sal de la contraseña': b'ab12',
                                           'huella de sesión 1': b'ef56'}


def test_ninguna_clave_ni_huella_esta_en_archivos_versionables():
    if not (RAIZ / '.env').exists():
        pytest.skip('Esta copia del proyecto no tiene .env.')
    try:
        salida = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=RAIZ, capture_output=True, text=True,
                                encoding='utf-8', check=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip('git no está disponible.')
    archivos = [RAIZ / linea for linea in salida.splitlines() if linea]
    assert len(archivos) > 50 and archivos_con(secretos().values(), archivos) == []


def test_el_revisor_del_historial_encuentra_claves_trozos_y_formatos_conocidos():
    buscados = {'BOT_ADMIN_KEY': b'clave-real-de-ejemplo-0123456789'}
    assert hallazgos(b'nada que ver', buscados) == []
    assert hallazgos(b'x clave-real-de-ejemplo-0123456789 x', buscados) == ['BOT_ADMIN_KEY']
    assert hallazgos(b'copiada a medias: de-ejemplo-0123', buscados) == ['BOT_ADMIN_KEY (un trozo)']
    assert hallazgos(('AKIA' + 'ABCDEFGHIJKLMNOP').encode(), {}) == ['clave de AWS']
