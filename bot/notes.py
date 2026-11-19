"""Notas del desarrollo: Markdown con enlaces [[Título]]. Se ven como universo en el panel y también abren en Obsidian.

Los enlaces salen del texto: nunca se inventan relaciones. Cada nota dice quién la hizo.
"""
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ORIGENES = ('alex', 'claude', 'codex', 'ambos')
TIPOS = ('Visión', 'Hito', 'Decisión', 'Código', 'Modelo', 'Estudio', 'Prueba', 'Error', 'Seguridad', 'Herramienta', 'Pendiente', 'En curso')
SECRETOS = [
    r'sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}', r'gh[pousr]_[A-Za-z0-9]{30,}', r'AKIA[0-9A-Z]{16}', r'AIza[0-9A-Za-z_-]{35}',
    r'xox[abprs]-[A-Za-z0-9-]{10,}', r'-----BEGIN [A-Z ]*PRIVATE KEY-----', r'0x[a-fA-F0-9]{64}',
    r'(?i)\b(?:password|passwd|contraseña|contrasena|secret)\s*[:=]\s*\S{4,}', r'(?:BOT|MEXC)_[A-Z_]*(?:KEY|SECRET)\s*=\s*\S{4,}',
    r'mx0v[A-Za-z0-9]{12,}',
]
_FECHA = re.compile(r'\d{4}-\d{2}-\d{2}(T[\d:.+\-Z]*)?$')


def _slug(titulo):
    plano = unicodedata.normalize('NFKD', titulo).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', plano.lower()).strip('-')[:70] or 'nota'


def _unica(valor):
    return ' '.join(str(valor).split())


def guardar(carpeta, titulo, cuerpo, origen, tipo, galaxia, fuente='', fecha=None, ident=None):
    carpeta = Path(carpeta)
    titulo, galaxia, fuente, cuerpo = _unica(titulo), _unica(galaxia), _unica(fuente), str(cuerpo).strip()
    fecha = fecha or datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M')
    if not titulo or not cuerpo:
        raise ValueError('Título y contenido son obligatorios.')
    if origen not in ORIGENES:
        raise ValueError(f'Origen inválido: usa {ORIGENES}.')
    if tipo not in TIPOS:
        raise ValueError(f'Tipo inválido: usa {TIPOS}.')
    if not _FECHA.match(fecha):
        raise ValueError('Fecha inválida. Usa AAAA-MM-DD o AAAA-MM-DDTHH:MM.')
    if ident and not re.fullmatch(r'[a-z0-9-]{1,80}', ident):
        raise ValueError('Identificador inválido: es el nombre del archivo de la nota, sin carpetas.')  # evita escribir fuera de notas/
    texto =' '.join((titulo, cuerpo, fuente))
    if any(re.search(p, texto) for p in SECRETOS):
        raise ValueError('Parece contener un secreto. Las notas no guardan claves: quítalo y vuelve a guardar.')
    carpeta.mkdir(parents=True, exist_ok=True)
    existentes = leer(carpeta)
    if any(n['titulo'].casefold() == titulo.casefold() and n['id'] != ident for n in existentes):
        raise ValueError(f'Ya existe una nota llamada «{titulo}». Usa un título único para no romper los enlaces.')
    nombre = ident or _slug(titulo)
    ocupados = {n['id'] for n in existentes} - {ident}
    base, i = nombre, 2
    while nombre in ocupados:
        nombre, i = f'{base}-{i}', i + 1
    ruta = carpeta / f'{nombre}.md'
    ruta.write_text(f'---\ntitulo: {titulo}\norigen: {origen}\ntipo: {tipo}\ngalaxia: {galaxia}\nfuente: {fuente}\nfecha: {fecha}\n---\n\n{cuerpo}\n', encoding='utf-8')
    return ruta


def _parsear(ruta):
    texto = ruta.read_text(encoding='utf-8')
    if not texto.startswith('---\n') or '\n---\n' not in texto:
        return None
    cabecera, cuerpo = texto[4:].split('\n---\n', 1)
    datos = dict(linea.split(': ', 1) if ': ' in linea else (linea.rstrip(':'), '') for linea in cabecera.splitlines())
    if not {'titulo', 'origen', 'tipo', 'galaxia', 'fecha'} <= datos.keys():
        return None
    return dict(id=ruta.stem, titulo=datos['titulo'], origen=datos['origen'], tipo=datos['tipo'], galaxia=datos['galaxia'],
                fuente=datos.get('fuente', ''), fecha=datos['fecha'], cuerpo=cuerpo.strip())


def leer(carpeta):
    notas = [n for n in map(_parsear, sorted(Path(carpeta).glob('*.md'))) if n]
    return sorted(notas, key=lambda n: (n['fecha'], n['id']))


def grafo(carpeta):
    carpeta = Path(carpeta)
    notas = leer(carpeta)
    ids = {n['id'] for n in notas}
    omitidas = sorted(r.name for r in carpeta.glob('*.md') if r.stem not in ids)
    por_titulo = {n['titulo'].casefold(): n['id'] for n in notas}
    enlaces = sorted({(n['id'], por_titulo[t.strip().casefold()]) for n in notas for t in re.findall(r'\[\[([^\]]+)\]\]', n['cuerpo'])
                      if t.strip().casefold() in por_titulo and por_titulo[t.strip().casefold()] != n['id']})
    contar = lambda campo: {k: sum(n[campo] == k for n in notas) for k in sorted({n[campo] for n in notas})}
    return dict(notas=notas, enlaces=[dict(origen=a, destino=b) for a, b in enlaces], galaxias=contar('galaxia'),
                autores=contar('origen'), omitidas=omitidas)


def resumen(carpeta):
    """En qué nos quedamos: visión, lo que está en curso, lo pendiente y lo último hecho."""
    notas = leer(carpeta)
    hechas = [n for n in notas if n['tipo'] not in ('Visión', 'En curso', 'Pendiente')]
    return dict(vision=[n for n in notas if n['tipo'] == 'Visión'], en_curso=[n for n in notas if n['tipo'] == 'En curso'],
                pendiente=[n for n in notas if n['tipo'] == 'Pendiente'], hecho=hechas[-8:][::-1])
