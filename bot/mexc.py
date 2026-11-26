"""Cliente de datos públicos de MEXC. Solo lectura: aquí no existe ninguna ruta de órdenes."""
import math
import time

import httpx

BASE = 'https://api.mexc.com'
REINTENTOS = 4
VENTANA_MAX_DIAS = 400  # /klines devuelve hasta 500 velas por llamada
DIA_MS = 86_400_000
RUTAS_PERMITIDAS = ('/api/v3/klines', '/api/v3/ticker/price', '/api/v3/ticker/bookTicker', '/api/v3/ticker/24hr', '/api/v3/exchangeInfo', '/api/v3/time', '/api/v3/depth')


class MexcError(RuntimeError):
    pass


class MexcUnavailable(MexcError):
    pass


class MexcRateLimited(MexcError):
    pass


class ParRetirado(MexcError):
    """MEXC ya no lista el par: reintentar no sirve. Reemplazarlo en config/universo.json es decisión de Alex."""


def _niveles(filas):
    """(precio, cantidad) válidos del libro: un nivel con cero, negativo o no numérico se descarta en la frontera."""
    salida = []
    for p, q, *_ in filas:
        precio, cantidad = float(p), float(q)
        if math.isfinite(precio) and math.isfinite(cantidad) and precio > 0 and cantidad > 0:
            salida.append((precio, cantidad))
    return salida


class Mexc:
    def __init__(self, http=None, sleep=time.sleep):
        self.http = http or httpx.Client(base_url=BASE, timeout=15, headers={'User-Agent': 'bot-trading-paper/1.0'})
        self.sleep = sleep

    def _get(self, ruta, params):
        if ruta not in RUTAS_PERMITIDAS:
            raise MexcError(f'{ruta}: este cliente es de solo lectura y no permite esa ruta.')
        url = BASE + ruta
        error = None
        for intento in range(REINTENTOS):
            espera = 2 ** intento
            try:
                r = self.http.get(url, params=params)
            except httpx.HTTPError as e:
                error = MexcUnavailable(f'MEXC no respondió en {ruta} ({type(e).__name__}). Revisa la conexión; se reintentará después.')
            else:
                if r.status_code == 429:
                    error = MexcRateLimited(f'MEXC aplicó límite de solicitudes en {ruta} (HTTP 429).')
                    try:
                        espera = float(r.headers.get('Retry-After', espera))
                    except ValueError:
                        pass
                elif r.status_code >= 500:
                    error = MexcUnavailable(f'MEXC falló en {ruta} con HTTP {r.status_code}.')
                elif r.status_code >= 400:
                    try:
                        codigo = r.json().get('code')
                    except (ValueError, AttributeError):
                        codigo = None
                    if codigo == -1121 and 'symbol' in params:  # «Invalid symbol»: así responde MEXC por un par que ya no lista
                        raise ParRetirado(f'MEXC ya no lista {params["symbol"]}: responde «Invalid symbol» (código -1121).')
                    sufijo = f', código {codigo}' if isinstance(codigo, int) else ''
                    raise MexcError(f'MEXC rechazó {ruta} (HTTP {r.status_code}{sufijo}).')  # su texto no llega al panel ni a la bitácora
                else:
                    try:
                        return r.json()
                    except ValueError as e:
                        raise MexcError(f'Respuesta inesperada de {ruta}: no es JSON.') from e
            if intento < REINTENTOS - 1:
                self.sleep(espera)
        raise error

    def ticker(self, simbolo):
        d = self._get('/api/v3/ticker/price', {'symbol': simbolo})
        try:
            return float(d['price'])
        except (KeyError, TypeError, ValueError) as e:
            raise MexcError(f'Respuesta inesperada del precio de {simbolo}.') from e

    def libro(self, simbolos):
        """Mejor compra y venta de varios activos con una sola consulta, sin reintentos: el siguiente segundo ya es otro intento."""
        ruta = '/api/v3/ticker/bookTicker'
        try:
            r = self.http.get(BASE + ruta)
        except httpx.HTTPError as e:
            raise MexcUnavailable(f'MEXC no respondió en {ruta} ({type(e).__name__}).') from e
        if r.status_code == 429:
            raise MexcRateLimited(f'MEXC aplicó límite de solicitudes en {ruta} (HTTP 429).')
        if r.status_code != 200:
            raise MexcUnavailable(f'MEXC falló en {ruta} con HTTP {r.status_code}.')
        ahora = time.time() * 1000
        quiero = set(simbolos)
        salida = {}
        try:
            for f in r.json():
                if f['symbol'] in quiero and f.get('bidPrice') and f.get('askPrice'):
                    salida[f['symbol']] = dict(bid=float(f['bidPrice']), ask=float(f['askPrice']), ts_ms=ahora)
        except (KeyError, TypeError, ValueError) as e:
            raise MexcError(f'Respuesta inesperada de {ruta}.') from e
        return salida

    def profundidad(self, simbolo, limite=50):
        """Libro visible de un par como (precio, cantidad). Sin reintentos: lo pide el reflejo y el siguiente segundo ya es otro intento."""
        ruta = '/api/v3/depth'
        try:
            r = self.http.get(BASE + ruta, params={'symbol': simbolo, 'limit': limite})
        except httpx.HTTPError as e:
            raise MexcUnavailable(f'MEXC no respondió en {ruta} ({type(e).__name__}).') from e
        if r.status_code == 429:
            raise MexcRateLimited(f'MEXC aplicó límite de solicitudes en {ruta} (HTTP 429).')
        if r.status_code != 200:
            raise MexcUnavailable(f'MEXC falló en {ruta} con HTTP {r.status_code}.')
        try:
            d = r.json()
            return dict(bids=_niveles(d['bids']), asks=_niveles(d['asks']))
        except (KeyError, TypeError, ValueError) as e:
            raise MexcError(f'Respuesta inesperada del libro de {simbolo}.') from e

    def klines(self, simbolo, inicio_ms=None, fin_ms=None, limit=500, intervalo='1d'):
        params = {'symbol': simbolo, 'interval': intervalo, 'limit': limit}
        if inicio_ms is not None:  # MEXC ignora el rango si no llegan ambos extremos
            params |= {'startTime': int(inicio_ms), 'endTime': int(fin_ms)}
        d = self._get('/api/v3/klines', params)
        if not isinstance(d, list):
            raise MexcError(f'Respuesta inesperada de velas de {simbolo}.')
        return d

    def history(self, simbolo, inicio_ms, fin_ms):
        """Historial completo, paginado por ventanas. Conserva tal cual lo que devuelve la fuente."""
        filas = {}
        a = inicio_ms
        while a < fin_ms:
            b = min(a + VENTANA_MAX_DIAS * DIA_MS, fin_ms)
            for f in self.klines(simbolo, a, b):
                filas[f[0]] = f
            a = b + 1
        return [filas[k] for k in sorted(filas)]

    def closed_candles(self, simbolo, limit, now_ms):
        """Solo velas ya cerradas: la vela abierta nunca cuenta como definitiva."""
        fin = int(now_ms)
        inicio = fin - (limit + 2) * DIA_MS
        filas = self.klines(simbolo, inicio, fin, limit=min(limit + 2, 500))
        return [f for f in filas if f[6] <= now_ms][-limit:]

    def filters(self, simbolo):
        d = self._get('/api/v3/exchangeInfo', {'symbol': simbolo})
        try:
            if not d['symbols']:
                raise ParRetirado(f'MEXC ya no lista {simbolo}: exchangeInfo ya no lo incluye.')
            s = d['symbols'][0]
            if str(s.get('status')) != '1':
                raise MexcError(f'{simbolo} no está disponible para operar (estado {s.get("status")}).')
            paso = float(s['baseSizePrecision']) or 10.0 ** -int(s['baseAssetPrecision'])  # MEXC manda '0' en algunos pares
            return {'paso_cantidad': paso, 'minimo_quote': float(s['quoteAmountPrecision']), 'base': s.get('baseAsset'),
                    'maker': float(s.get('makerCommission', 0)), 'taker': float(s.get('takerCommission', 0))}
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise MexcError(f'Respuesta inesperada de exchangeInfo para {simbolo}.') from e
