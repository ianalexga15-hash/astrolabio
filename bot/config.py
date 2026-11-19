"""Ajustes del servidor. Las claves viven solo en .env, fuera del repositorio y de los logs."""
import json
import os
from dataclasses import MISSING, asdict, dataclass, fields, replace
from pathlib import Path
from urllib.parse import urlparse

from bot.risk import Limites

RAIZ = Path(__file__).resolve().parent.parent
MODELOS_PERMITIDOS = ('qwen3:4b-instruct', 'qwen3:4b', 'qwen3:0.6b', 'deepseek-r1:1.5b', 'deepseek-r1:8b')


@dataclass(frozen=True)
class Ajustes:
    admin_key: str
    llm_key: str
    ollama_url: str = 'http://127.0.0.1:11434'
    llm_modelo: str = 'qwen3:4b-instruct'
    raiz: Path = RAIZ
    db: Path = RAIZ / 'data' / 'bot.sqlite3'
    puerto: int = 8770
    decisor: str = 'llm'
    espera_tick_s: int = 30
    reflejo_s: float = 1.0
    sin_suspender: bool = False
    mexc_clave: str = ''  # clave de solo ver de la cuenta real (etapa 3); nunca se imprime
    mexc_secreto: str = ''

    def validar(self):
        for nombre in ('admin_key', 'llm_key'):
            if len(getattr(self, nombre) or '') < 16:
                raise ValueError(f'{nombre} falta o es muy corta: ejecuta python -m bot.preparar para generar .env.')
        if urlparse(self.ollama_url).hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('Ollama debe ser local: la inferencia no puede salir de esta laptop.')
        if self.llm_modelo not in MODELOS_PERMITIDOS:
            raise ValueError(f'Modelo LLM no permitido: {self.llm_modelo}.')
        if self.decisor not in ('llm', 'regla'):
            raise ValueError('decisor debe ser llm o regla.')
        return self

    def __repr__(self):
        return f'Ajustes(raiz={self.raiz}, llm_modelo={self.llm_modelo}, puerto={self.puerto})'  # nunca imprime claves


def leer_env(ruta=RAIZ / '.env'):
    valores = {}
    if Path(ruta).exists():
        for linea in Path(ruta).read_text(encoding='utf-8').splitlines():
            linea = linea.strip()
            if linea and not linea.startswith('#') and '=' in linea:
                k, v = linea.split('=', 1)
                valores[k.strip()] = v.strip()
    return valores | {k: v for k, v in os.environ.items() if k.startswith('BOT_')}


def cargar_ajustes():
    e = leer_env()
    db = Path(e['BOT_DB']) if e.get('BOT_DB') else RAIZ / 'data' / 'bot.sqlite3'
    return Ajustes(admin_key=e.get('BOT_ADMIN_KEY', ''), llm_key=e.get('BOT_LLM_KEY', ''), db=db if db.is_absolute() else RAIZ / db,
                   ollama_url=e.get('BOT_OLLAMA_URL', 'http://127.0.0.1:11434'), llm_modelo=e.get('BOT_LLM_MODEL', 'qwen3:4b-instruct'),
                   puerto=int(e.get('BOT_PORT', 8770)), decisor=e.get('BOT_DECISOR', 'llm'), reflejo_s=float(e.get('BOT_REFLEJO_S', 1.0)),
                   sin_suspender=e.get('BOT_SIN_SUSPENDER') == '1', mexc_clave=e.get('MEXC_API_KEY', ''),
                   mexc_secreto=e.get('MEXC_API_SECRET', '')).validar()


def cargar_universo(raiz, principal):
    """Activos de la cartera. Sin archivo de universo, solo el activo principal."""
    ruta = Path(raiz) / 'config' / 'universo.json'
    simbolos = json.loads(ruta.read_text(encoding='utf-8'))['simbolos'] if ruta.exists() else []
    return [principal] + [s for s in simbolos if s != principal]


def cargar_limites(raiz, store):
    """La última configuración guardada por una persona autenticada; si no hay, la inicial del archivo."""
    datos = store.cargar_configuracion() or json.loads((Path(raiz) / 'config' / 'riesgo.json').read_text(encoding='utf-8'))
    limites = limites_desde(datos)
    reales = cargar_comisiones(raiz)
    return replace(limites, comision_por_par=tuple(sorted(reales.items()))) if reales else limites


def cargar_comisiones(raiz):
    """Comisión real por par al comprar o vender al instante, leída de MEXC con la clave de solo ver; vacío si no se ha consultado."""
    ruta = Path(raiz) / 'config' / 'comisiones.json'
    return {s: float(c) for s, c in json.loads(ruta.read_text(encoding='utf-8')).items()} if ruta.exists() else {}


def limites_desde(datos):
    validos = {f.name for f in fields(Limites)}
    obligatorios = {f.name for f in fields(Limites) if f.default is MISSING}
    desconocidos = set(datos) - validos
    if desconocidos or obligatorios - set(datos):
        raise ValueError(f'Configuración inválida. Sobran {sorted(desconocidos)}; faltan {sorted(obligatorios - set(datos))}.')
    return Limites(**datos).validar()


def limites_a_dict(limites):
    return asdict(limites)
