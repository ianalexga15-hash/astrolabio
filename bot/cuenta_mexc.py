"""Lectura de la cuenta real de MEXC con una clave de solo ver (etapa 3). Aquí tampoco existe ninguna ruta de órdenes."""
import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx
from fastapi import Depends

from bot.mexc import BASE, MexcError, MexcUnavailable

RUTAS_FIRMADAS = ('/api/v3/account', '/api/v3/tradeFee')  # la cuenta se ve, no se opera
VENTANA_MS = 5000
MOTIVOS = {  # códigos de la documentación de MEXC Spot V3
    10072: 'MEXC no reconoce la clave: revisa MEXC_API_KEY en .env.',
    700001: 'MEXC no reconoce la clave: revisa MEXC_API_KEY en .env.',
    700002: 'MEXC rechazó la firma: revisa que MEXC_API_SECRET en .env sea la Secret Key completa.',
    700003: 'El reloj de la laptop y el de MEXC no coinciden; se vuelve a sincronizar en la próxima lectura.',
    700006: 'MEXC no acepta peticiones desde esta IP: revisa la IP ligada a la clave.',
    700007: 'La clave no tiene permiso para ver la cuenta: actívale «View Account Details» en MEXC.',
}


class CuentaMexc:
    def __init__(self, clave, secreto, http=None, reloj=time.time):
        self._clave, self._secreto = clave or '', secreto or ''
        self.http = http or httpx.Client(timeout=15, headers={'User-Agent': 'bot-trading-paper/1.0'})
        self.reloj = reloj
        self.desfase_ms = None  # MEXC rechaza firmas fuera de su ventana de 5 s: se firma con su reloj

    def __repr__(self):
        return 'CuentaMexc(clave oculta)'

    @property
    def configurada(self):
        return bool(self._clave and self._secreto)

    def _sincronizar(self):
        try:
            servidor = float(self.http.get(BASE + '/api/v3/time').json()['serverTime'])
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            servidor = None
        self.desfase_ms = 0.0 if servidor is None else servidor - self.reloj() * 1000

    def _get(self, ruta, params=None):
        if ruta not in RUTAS_FIRMADAS:
            raise MexcError(f'{ruta}: la cuenta solo se lee; esa ruta no está permitida.')
        if self.desfase_ms is None:
            self._sincronizar()
        consulta = urlencode({**(params or {}), 'timestamp': int(self.reloj() * 1000 + self.desfase_ms), 'recvWindow': VENTANA_MS})
        firma = hmac.new(self._secreto.encode(), consulta.encode(), hashlib.sha256).hexdigest()
        try:
            r = self.http.get(f'{BASE}{ruta}?{consulta}&signature={firma}', headers={'X-MEXC-APIKEY': self._clave})
        except httpx.HTTPError as e:
            raise MexcUnavailable(f'MEXC no respondió al leer la cuenta ({type(e).__name__}); se intenta otra vez en la próxima lectura.') from None
        if r.status_code >= 400:
            raise MexcError(self._motivo(r))
        try:
            return r.json()
        except ValueError:
            raise MexcError('MEXC respondió algo que no es JSON al leer la cuenta.') from None

    def _motivo(self, r):
        """Explica el rechazo sin repetir la URL firmada ni las claves."""
        try:
            d = r.json()
            codigo = int(d.get('code'))
        except (ValueError, TypeError, AttributeError):
            return f'MEXC rechazó la lectura de la cuenta (HTTP {r.status_code}).'
        if codigo == 700003:
            self.desfase_ms = None
        return MOTIVOS.get(codigo, f'MEXC rechazó la lectura de la cuenta (código {codigo}).')  # el texto del proveedor no llega al panel

    def saldos(self):
        d = self._get('/api/v3/account')
        saldos = []
        for b in d.get('balances') or []:
            libre, bloqueado = float(b.get('free') or 0), float(b.get('locked') or 0)
            if libre or bloqueado:
                saldos.append(dict(activo=str(b.get('asset')), libre=libre, bloqueado=bloqueado))
        return dict(saldos=saldos, actualizado=d.get('updateTime'))

    def comision(self, simbolo):
        """Comisión real de un par para esta cuenta al operar por API, como fracción (0.0008 es 0.08 %)."""
        datos = self._get('/api/v3/tradeFee', {'symbol': simbolo}).get('data') or {}
        try:
            return dict(maker=float(datos['makerCommission']), taker=float(datos['takerCommission']))
        except (KeyError, TypeError, ValueError):
            raise MexcError(f'MEXC no devolvió la comisión de {simbolo}.') from None


def registrar(app, cuenta, sesion, cada_s=30):
    """Agrega GET /api/cuenta-mexc al panel: pide sesión y consulta a MEXC como máximo una vez cada `cada_s` segundos."""
    guardado = {'ts': 0.0, 'datos': None}

    @app.get('/api/cuenta-mexc', dependencies=[Depends(sesion)])
    def ver_cuenta_mexc():
        """Saldo real de la cuenta MEXC en solo lectura. Sin clave en .env, explica cómo conectarla."""
        if not cuenta.configurada:
            return dict(conectada=False, saldos=[],
                        motivo='Falta MEXC_API_KEY o MEXC_API_SECRET en .env. Crea en MEXC una clave de solo ver, agrégala y reinicia el bot.')
        ahora = time.monotonic()
        if guardado['datos'] is None or ahora - guardado['ts'] >= cada_s:
            try:
                guardado['datos'] = dict(conectada=True, error=None, **cuenta.saldos())
            except MexcError as e:
                guardado['datos'] = dict(conectada=False, error=str(e), saldos=[])
            guardado['ts'] = ahora
        return guardado['datos'] | dict(leido_hace_s=round(ahora - guardado['ts']))
