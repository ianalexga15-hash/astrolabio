"""Protecciones locales del panel. Ninguna función concede acceso al exchange."""
import hashlib
import hmac
import math
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

from bot.config import RAIZ

# El panel no usa ninguna de estas funciones del navegador: todas quedan apagadas. Solo nombres que Chromium reconoce, para no llenar la consola de avisos.
PERMISOS = ('accelerometer', 'autoplay', 'bluetooth', 'camera', 'clipboard-read', 'clipboard-write', 'compute-pressure', 'cross-origin-isolated',
            'display-capture', 'encrypted-media', 'fullscreen', 'gamepad', 'geolocation', 'gyroscope', 'hid', 'identity-credentials-get',
            'idle-detection', 'keyboard-map', 'local-fonts', 'magnetometer', 'microphone', 'midi', 'otp-credentials', 'payment',
            'picture-in-picture', 'publickey-credentials-create', 'publickey-credentials-get', 'screen-wake-lock', 'serial', 'storage-access',
            'sync-xhr', 'unload', 'usb', 'window-management', 'xr-spatial-tracking')
CABECERAS = [
    (b'x-content-type-options', b'nosniff'), (b'x-frame-options', b'DENY'), (b'referrer-policy', b'no-referrer'),
    (b'cross-origin-opener-policy', b'same-origin'), (b'cross-origin-resource-policy', b'same-origin'),
    (b'permissions-policy', ', '.join(f'{p}=()' for p in PERMISOS).encode()),
    # Sin 'unsafe-inline': el panel compilado no trae estilos ni scripts en línea, y los style={} de React van por CSSOM.
    (b'content-security-policy', b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
                                 b"object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
]


def _en_json(carpeta):
    """Patrón de una carpeta tal como sale dentro de un texto JSON: separada por / o por \\, que JSON escribe \\\\ (y repr() lo dobla)."""
    # (?<!\w): la «c» final de un escape como \u001c no cuenta como la unidad C:
    return r'(?<!\w)' + r'(?:(?:\\\\)+|/)'.join(re.escape(p) for p in re.split(r'[\\/]+', str(carpeta)) if p) + r'(?!\w)'


# Por pares de barras: así nunca se come la que escapa unas comillas y el JSON sigue siendo válido.
_RAIZ_JSON = re.compile(_en_json(RAIZ) + r'(?:(?:\\\\)+|/)?', re.I)
_CASA_JSON = re.compile(_en_json(Path.home()), re.I)


class RespuestaSegura(JSONResponse):
    """Todo JSON del panel sale por aquí: la carpeta del proyecto queda como ruta relativa y la del usuario como ~, aunque un error las traiga."""
    def render(self, content):
        return _CASA_JSON.sub('~', _RAIZ_JSON.sub('', super().render(content).decode())).encode()


class LimiteIntentos:
    """Frena la fuerza bruta por IP: tras `maximo` intentos fallidos seguidos, bloquea `bloqueo_s` segundos.
    Cuenta cada intento antes de comprobar la clave, así que varias peticiones a la vez no se saltan el límite."""
    def __init__(self, maximo=5, bloqueo_s=30):
        self.maximo, self.bloqueo_s = maximo, bloqueo_s
        self._ips = {}  # shortcut: no se poda; basta porque el panel solo escucha en 127.0.0.1, podarlo si algún día escucha fuera
        self._lock = threading.Lock()

    def registrar(self, ip):
        """Anota un intento. Devuelve 0 si puede comprobar la clave, o los segundos de bloqueo que le quedan."""
        with self._lock:
            ahora = time.monotonic()
            fallos, hasta = self._ips.get(ip, (0, 0.0))
            if ahora < hasta:
                return math.ceil(hasta - ahora)
            fallos = 1 if hasta else fallos + 1  # tras un bloqueo vencido empieza otra ronda
            self._ips[ip] = (fallos, ahora + self.bloqueo_s if fallos >= self.maximo else 0.0)
            return 0

    def acierto(self, ip):
        with self._lock:
            self._ips.pop(ip, None)


def huella_clave(clave, n=2 ** 14, r=8, p=1):
    """Huella scrypt con sal aleatoria. Es lo único que se guarda de la contraseña personal."""
    sal = secrets.token_bytes(16)
    huella = hashlib.scrypt(clave.encode(), salt=sal, n=n, r=r, p=p, dklen=32)
    return dict(algoritmo='scrypt', n=n, r=r, p=p, sal=sal.hex(), huella=huella.hex())


def clave_coincide(clave, datos):
    if not datos or datos.get('algoritmo') != 'scrypt':
        return False
    huella = hashlib.scrypt(clave.encode(), salt=bytes.fromhex(datos['sal']), n=datos['n'], r=datos['r'], p=datos['p'], dklen=32)
    return hmac.compare_digest(huella.hex(), datos['huella'])


# Sin contraseña personal se compara con esta huella de una clave que nadie conoce: así una clave mala tarda lo mismo
# y el tiempo de respuesta no delata si hay contraseña personal.
SENUELO = huella_clave(secrets.token_urlsafe(32))


class Sesiones:
    """Tokens aleatorios revocables. Solo se guarda su huella: en memoria y, con store, en SQLite para sobrevivir a un reinicio."""
    def __init__(self, duracion=8 * 3600, store=None):
        self.duracion = duracion
        self.store = store
        self._tokens = store.sesiones_vigentes(time.time()) if store else {}
        self._lock = threading.Lock()

    def crear(self):
        token = secrets.token_urlsafe(32)
        with self._lock:
            ahora = time.time()
            self._tokens = {k: v for k, v in self._tokens.items() if v > ahora}
            if len(self._tokens) >= 128:
                self._tokens.pop(next(iter(self._tokens)))
            self._tokens[self._huella(token)] = ahora + self.duracion
            self._guardar()
        return token

    def _guardar(self):
        # shortcut: copia completa (máx. 128 filas) en cada cambio; supone un solo proceso del bot por base, como da el puerto único.
        if self.store is not None:
            self.store.guardar_sesiones(self._tokens)

    @staticmethod
    def _huella(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def valida(self, token):
        if not token or len(token) > 128:
            return False
        with self._lock:
            return self._tokens.get(self._huella(token), 0) > time.time()

    def revocar_otras(self, token):
        """Tras cambiar la contraseña solo sigue abierta la sesión que la cambió."""
        with self._lock:
            propia = self._huella(token) if token else None
            self._tokens = {k: v for k, v in self._tokens.items() if k == propia}
            self._guardar()

    def revocar(self, token):
        if token:
            with self._lock:
                self._tokens.pop(self._huella(token), None)
                self._guardar()


class ProteccionPanel:
    """Rechaza hosts externos y peticiones de navegador de otro origen."""
    def __init__(self, app, pruebas=False):
        self.app = app
        self.hosts = {'127.0.0.1', 'localhost', '::1'} | ({'testserver'} if pruebas else set())

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])
        host = headers.get(b'host', b'').decode('latin1')
        try:
            destino = urlsplit('http://' + host)
            permitido = destino.hostname in self.hosts and not destino.username and not destino.password
        except ValueError:
            permitido = False
        origen = headers.get(b'origin')
        otro_origen = origen is not None and origen.decode('latin1') != f"{scope['scheme']}://{host}"
        sitio = headers.get(b'sec-fetch-site', b'')
        iniciada = False

        async def seguro(message):
            nonlocal iniciada
            if message['type'] == 'http.response.start':
                iniciada = True
                h = list(message.get('headers', [])) + CABECERAS
                if scope['path'].startswith(('/api/', '/llm/')):
                    h = [(k, v) for k, v in h if k.lower() != b'cache-control']
                    h.append((b'cache-control', b'no-store'))
                message = {**message, 'headers': h}
            await send(message)

        if not permitido or otro_origen or sitio in (b'cross-site', b'same-site'):
            return await JSONResponse({'detail': 'Origen de la solicitud no permitido.'}, status_code=403)(scope, receive, seguro)
        try:
            await self.app(scope, receive, seguro)
        except Exception:
            # La traza queda solo en el log local del servidor; el panel recibe un texto fijo, con las mismas cabeceras.
            if not iniciada:
                await JSONResponse({'detail': 'Error interno del bot. Revisa la bitácora en Sistema.'}, status_code=500)(scope, receive, seguro)
            raise
