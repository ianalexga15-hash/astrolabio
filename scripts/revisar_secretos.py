"""Busca claves y huellas en todo lo que git guardó, antes de subir el proyecto a GitHub.

Revisa cada versión de cada archivo en todas las ramas, los mensajes de los commits y los archivos que git
versionaría hoy. Busca los valores reales de .env, las huellas de la contraseña y de las sesiones del panel,
y formatos conocidos de credenciales (reglas al estilo de gitleaks y detect-secrets). Nunca muestra un valor:
solo el tipo de secreto, el commit y el archivo. Sale con código 1 si encuentra algo.

Uso: .venv/Scripts/python scripts/revisar_secretos.py
"""
import hashlib
import json
import math
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from bot.config import leer_env  # noqa: E402

NOMBRE_SECRETO = re.compile(r'KEY|SECRET|TOKEN|PASS|PWD', re.I)
VENTANA = 12  # un trozo de 12 caracteres de una clave real ya cuenta como fuga
PATRONES = {nombre: re.compile(p.encode()) for nombre, p in {
    'llave privada': r'-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----(?:\s|\\n)*[A-Za-z0-9+/=]{40,}',
    'clave de AWS': r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b',
    'token de GitHub': r'\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})',
    'token de Slack': r'\bxox[abposr]-[A-Za-z0-9-]{10,}',
    'clave de Google': r'\bAIza[0-9A-Za-z_-]{35}',
    'clave de Stripe': r'\b[rs]k_live_[0-9A-Za-z]{20,}',
    'clave de OpenAI o Anthropic': r'\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}',
    'token de Hugging Face': r'\bhf_[A-Za-z0-9]{30,}',
    'token de Telegram': r'\b\d{8,10}:AA[A-Za-z0-9_-]{33}',
    'JWT': r'\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}',
    'clave de MEXC': r'\bmx0v[A-Za-z0-9]{12,}',
}.items()}
# Una clave escrita entre comillas en el código: se revisa si parece aleatoria y no dice que es de prueba.
ASIGNACION = re.compile(rb'(?i)(?:api[_-]?key|secret|token|passw(?:or)?d|pwd|clave)["\']?\s*[:=]\s*["\']([^"\'\s]{16,})["\']')
DE_PRUEBA = re.compile(rb'(?i)prueba|ejemplo|example|cambia|test|fake|dummy|xxx|\.\.\.|<|\{')
# Valores inventados de las pruebas, ya revisados: huella SHA-256 de lo encontrado (como .gitleaksignore).
PERMITIDOS = {
    '03aafb028d538b06c4341bf8cf2a692a3c6d1f36e34e0e0b376f407c6117a246',  # tests/test_notes.py: token de GitHub con checksum inválido
    'cb5ad2877854f79965d6059923ed2b827a555424f96dba1aad935f59603b0407',  # tests/test_acceso.py: contraseña equivocada a propósito
}
RUTA_PROHIBIDA = re.compile(r'(^|/)(\.env(\.(?!example$)[^/]*)?|[^/]*\.(sqlite3[^/]*|db|pem|key|p12|pfx|kdbx)|id_rsa[^/]*)$')


def secretos(env=None, base=None):
    """Valores que no pueden aparecer: claves de .env y huellas guardadas en la base del panel."""
    env = leer_env() if env is None else env
    valores = {nombre: v for nombre, v in env.items() if NOMBRE_SECRETO.search(nombre) and len(v) >= 8}
    base = Path(base or env.get('BOT_DB') or RAIZ / 'data' / 'bot.sqlite3')
    base = base if base.is_absolute() else RAIZ / base
    if base.exists():
        db = sqlite3.connect(f'{base.as_uri()}?mode=ro', uri=True)
        try:
            for (datos,) in db.execute('SELECT datos FROM acceso'):
                d = json.loads(datos)
                valores |= {f'{k} de la contraseña': d[k] for k in ('huella', 'sal') if d.get(k)}
            valores |= {f'huella de sesión {i}': h for i, (h,) in enumerate(db.execute('SELECT huella FROM sesiones'), 1)}
        except sqlite3.OperationalError:
            pass  # base sin las tablas del panel: no hay huellas que buscar
        finally:
            db.close()
    return {nombre: v.encode() for nombre, v in valores.items()}


def entropia(valor):
    return -sum(n / len(valor) * math.log2(n / len(valor)) for n in Counter(valor).values())


def hallazgos(contenido, buscados):
    """Tipos de secreto presentes en un contenido, sin decir su valor."""
    tipos = []
    for nombre, valor in buscados.items():
        if valor in contenido:
            tipos.append(nombre)
        elif any(valor[i:i + VENTANA] in contenido for i in range(0, len(valor) - VENTANA + 1, 4)):
            tipos.append(f'{nombre} (un trozo)')
    nuevo = lambda valor: hashlib.sha256(valor).hexdigest() not in PERMITIDOS
    tipos += [nombre for nombre, patron in PATRONES.items() if any(nuevo(m.group()) for m in patron.finditer(contenido))]
    if any(entropia(m) >= 3.5 and not DE_PRUEBA.search(m) and nuevo(m) for m in ASIGNACION.findall(contenido)):
        tipos.append('posible clave escrita en el código')
    return tipos


def git(*args, entrada=None):
    return subprocess.run(['git', '-c', 'core.quotepath=off', *args], cwd=RAIZ, input=entrada, capture_output=True, check=True).stdout


def versiones():
    """Cada versión de cada archivo en todas las ramas: (objeto, ruta, contenido)."""
    pares = [linea.split(' ', 1) for linea in git('rev-list', '--objects', '--all', '--filter=object:type=blob').decode().splitlines()
             if ' ' in linea]
    salida, i = git('cat-file', '--batch', entrada=''.join(f'{sha}\n' for sha, _ in pares).encode()), 0
    for sha, ruta in pares:
        fin = salida.index(b'\n', i)
        tam = int(salida[i:fin].split()[2])
        yield sha, ruta, salida[fin + 1:fin + 1 + tam]
        i = fin + 2 + tam


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    buscados = secretos()
    print('Se buscan, sin mostrarlos:', ', '.join(buscados) or 'ninguna clave (.env no existe)')
    encontrados, n = [], 0
    for sha, ruta, contenido in versiones():
        n += 1
        tipos = hallazgos(contenido, buscados) + (['archivo que no debe versionarse'] if RUTA_PROHIBIDA.search(ruta) else [])
        if tipos:
            commit = (git('log', '--all', '--reverse', '--format=%h', f'--find-object={sha}').split() or [b'?'])[0].decode()
            encontrados += [f'{t}: commit {commit}, {ruta}' for t in tipos]
    mensajes = git('log', '--all', '--format=%h%x00%B%x1e').split(b'\x1e')
    for m in mensajes:
        commit, _, texto = m.strip().partition(b'\x00')
        encontrados += [f'{t}: mensaje del commit {commit.decode()}' for t in hallazgos(texto, buscados)]
    actuales = git('ls-files', '--cached', '--others', '--exclude-standard').decode().splitlines()
    for ruta in actuales:
        archivo = RAIZ / ruta
        tipos = (hallazgos(archivo.read_bytes(), buscados) if archivo.is_file() else []) + \
            (['archivo que no debe versionarse'] if RUTA_PROHIBIDA.search(ruta) else [])
        encontrados += [f'{t}: archivo actual {ruta}' for t in tipos]
    print(f'Revisados: {len(mensajes) - 1} commits, {n} versiones de archivos y {len(actuales)} archivos actuales.')
    for linea in dict.fromkeys(encontrados):
        print('ENCONTRADO', linea)
    print('Hay que limpiar antes de subir.' if encontrados else 'Sin claves, huellas ni archivos prohibidos.')
    return 1 if encontrados else 0


if __name__ == '__main__':
    sys.exit(main())
