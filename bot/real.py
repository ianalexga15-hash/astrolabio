"""Cartera Real (etapa 4, decisión de Alex del 2026-11-26): repite con dinero real, en Spot, lo que la cartera Paper ejecuta.

Arranca apagada y solo se enciende desde el panel. Modos: apagada (no envía nada), sombra (valida cada orden con
/api/v3/order/test, sin ejecutarla) y real (la envía; pide escribir la confirmación). Opera dentro de sus topes y sin saldo
no envía nada. Cada orden de Paper se repite una sola vez y con un id de cliente: si se pierde la respuesta, se consulta antes
de reintentar. Las salidas son las de Paper: cuando Paper vende por stop, objetivo o stop móvil, la Real vende lo que compró.
Es el único módulo que crea órdenes en MEXC; no conoce retiros ni transferencias.
"""
import hashlib
import hmac
import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel

from bot.cuenta_mexc import VENTANA_MS, CuentaMexc
from bot.mexc import BASE, MexcError, MexcUnavailable
from bot.store import ahora_iso

RUTAS_ORDENES = ('/api/v3/order', '/api/v3/order/test')
MODOS = ('apagada', 'sombra', 'real')
# Entrega del curso (rúbrica del 2026-11-26): la app solo opera en Paper. Con esto el cliente rechaza el endpoint real antes de
# cualquier llamada y nadie enciende el modo real; Sombra sigue, porque /api/v3/order/test nunca ejecuta. tests/test_solo_paper.py
SOLO_PAPER = True
BLOQUEO = 'Envío real bloqueado: esta versión solo opera en Paper. Sombra valida cada orden en MEXC sin ejecutarla.'
CONFIRMACION = 'ACTIVAR REAL'
TOPES = dict(tope_total_usdt=50.0, max_orden_usdt=10.0, perdida_diaria_usdt=5.0)
FINALES = ('FILLED', 'CANCELED', 'PARTIALLY_CANCELED', 'REJECTED', 'EXPIRED')
ESQUEMA = '''
CREATE TABLE IF NOT EXISTS real_estado(id INTEGER PRIMARY KEY CHECK (id = 1), datos TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ordenes_reales(id INTEGER PRIMARY KEY AUTOINCREMENT, orden_paper INTEGER UNIQUE, creado TEXT NOT NULL,
    simbolo TEXT NOT NULL, lado TEXT NOT NULL, modo TEXT NOT NULL, cliente_id TEXT, mexc_id TEXT, estado TEXT NOT NULL,
    monto_usdt REAL, cantidad REAL, ejecutado REAL, cotizado REAL, resultado REAL, motivo TEXT);
'''


def cargar_topes(raiz):
    """Topes en USDT de config/real.json; los que falten usan los de TOPES."""
    ruta = Path(raiz) / 'config' / 'real.json'
    datos = json.loads(ruta.read_text(encoding='utf-8')) if ruta.exists() else {}
    return TOPES | {k: float(v) for k, v in datos.items() if k in TOPES and float(v) > 0}


class ClienteOrdenes(CuentaMexc):
    """Firma órdenes Spot con la clave del .env. Solo conoce /api/v3/order y /api/v3/order/test."""

    def _orden(self, metodo, ruta, params):
        if ruta not in RUTAS_ORDENES:
            raise MexcError(f'{ruta}: la cartera Real solo envía, prueba y consulta órdenes Spot.')
        if SOLO_PAPER and metodo == 'POST' and ruta == '/api/v3/order':
            raise PermissionError(BLOQUEO)
        if self.desfase_ms is None:
            self._sincronizar()
        consulta = urlencode({**params, 'timestamp': int(self.reloj() * 1000 + self.desfase_ms), 'recvWindow': VENTANA_MS})
        firma = hmac.new(self._secreto.encode(), consulta.encode(), hashlib.sha256).hexdigest()
        try:
            r = self.http.request(metodo, f'{BASE}{ruta}?{consulta}&signature={firma}', headers={'X-MEXC-APIKEY': self._clave})
        except httpx.HTTPError as e:
            raise MexcUnavailable(f'MEXC no respondió a la orden ({type(e).__name__}); se consulta antes de reintentar.') from None
        if r.status_code >= 400:
            raise MexcError(self._motivo_orden(r))
        try:
            return r.json()
        except ValueError:
            raise MexcError('MEXC respondió algo que no es JSON a la orden.') from None

    def _motivo_orden(self, r):
        try:
            codigo = int(r.json().get('code'))
        except (ValueError, TypeError, AttributeError):
            codigo = None
        if codigo == 700007:
            return 'La clave no tiene permiso de Trade: actívale el de Spot en MEXC, nunca el de retiro.'
        return self._motivo(r).replace('la lectura de la cuenta', 'la orden')  # mismos códigos de clave, firma, IP y reloj

    def orden(self, params):
        return self._orden('POST', '/api/v3/order', params)

    def orden_prueba(self, params):
        return self._orden('POST', '/api/v3/order/test', params)

    def consultar(self, simbolo, cliente_id):
        return self._orden('GET', '/api/v3/order', {'symbol': simbolo, 'origClientOrderId': cliente_id})


def _texto(cantidad, paso):
    decimales = max(0, -math.floor(math.log10(paso) + 1e-9))
    return f'{cantidad:.{decimales}f}'


class CarteraReal:
    def __init__(self, store, cliente, mercado, topes=None):
        self.store, self.cliente, self.mercado = store, cliente, mercado
        self.topes = TOPES | (topes or {})
        self._lock = threading.Lock()
        with store._lock:
            store.db.executescript(ESQUEMA)

    # Estado y modo
    def estado(self):
        f = self.store._una('SELECT datos FROM real_estado WHERE id=1')
        datos = dict(modo='apagada', desde_orden=None, compras_bloqueadas=False, motivo='', verificacion=None) | (json.loads(f['datos']) if f else {})
        if SOLO_PAPER and datos['modo'] == 'real':  # un modo real guardado antes del bloqueo no envía nada
            datos |= dict(modo='apagada', motivo=BLOQUEO)
        return datos

    def _guardar(self, **cambios):
        datos = self.estado() | cambios
        self.store._ejecutar('INSERT INTO real_estado(id, datos) VALUES(1, ?) ON CONFLICT(id) DO UPDATE SET datos=excluded.datos', json.dumps(datos))
        return datos

    def cambiar_modo(self, modo, confirmacion=''):
        if modo not in MODOS:
            raise ValueError(f'Modo desconocido: {modo}. Usa apagada, sombra o real.')
        if modo == 'real' and SOLO_PAPER:
            raise PermissionError(BLOQUEO)
        if modo == 'real' and confirmacion != CONFIRMACION:
            raise PermissionError(f'Para encender la cartera Real escribe «{CONFIRMACION}».')
        if modo != 'apagada' and not self.cliente.configurada:
            raise PermissionError('Falta la clave de MEXC en .env: agrega MEXC_API_KEY y MEXC_API_SECRET y reinicia el bot.')
        with self._lock:
            cambios = dict(modo=modo)
            if self.estado()['modo'] == 'apagada' and modo != 'apagada':  # solo cuenta lo que Paper ejecute desde ahora
                ultima = self.store._una("SELECT MAX(id) m FROM ordenes WHERE run LIKE 'live:%'")
                cambios |= dict(desde_orden=(ultima or {}).get('m') or 0, compras_bloqueadas=False, motivo='')
            elif modo != 'apagada':  # volver a elegir el modo libera las compras que un rechazo dejó en pausa
                cambios |= dict(compras_bloqueadas=False, motivo='')
            return self._guardar(**cambios)

    # Libro de órdenes reales
    def ordenes(self, limite=50):
        return self.store._todas('SELECT * FROM ordenes_reales ORDER BY id DESC LIMIT ?', limite)

    def posiciones(self):
        pos = {}
        for f in self.store._todas("SELECT * FROM ordenes_reales WHERE modo='real' AND estado='ejecutada' ORDER BY id"):
            p = pos.setdefault(f['simbolo'], dict(simbolo=f['simbolo'], cantidad=0.0, costo=0.0))
            if f['lado'] == 'comprar':
                p['cantidad'] += f['ejecutado']
                p['costo'] += f['cotizado']
            elif p['cantidad'] > 0:
                p['costo'] *= 1 - min(1.0, f['ejecutado'] / p['cantidad'])
                p['cantidad'] -= f['ejecutado']
        return [p for p in pos.values() if p['cantidad'] > 1e-12]

    def _expuesto(self):
        return sum(p['costo'] for p in self.posiciones())

    def _resultado_hoy(self):
        hoy = datetime.now(timezone.utc).date().isoformat()
        f = self.store._una('SELECT SUM(resultado) s FROM ordenes_reales WHERE resultado IS NOT NULL AND creado LIKE ?', f'{hoy}%')
        return (f or {}).get('s') or 0.0

    def _fila(self, **campos):
        campos.setdefault('creado', ahora_iso())
        cur = self.store._ejecutar(f'INSERT INTO ordenes_reales({", ".join(campos)}) VALUES({", ".join("?" * len(campos))})', *campos.values())
        return cur.lastrowid

    def _actualizar(self, fila_id, **campos):
        self.store._ejecutar(f'UPDATE ordenes_reales SET {", ".join(f"{k}=?" for k in campos)} WHERE id=?', *campos.values(), fila_id)

    def _saldo(self, activo):
        return next((s['libre'] for s in self.cliente.saldos()['saldos'] if s['activo'] == activo), 0.0)

    # Ciclo
    def paso(self):
        """Una vuelta: primero aclara las órdenes sin respuesta y luego repite lo que Paper ejecutó desde la última vez."""
        with self._lock:
            e = self.estado()
            if e['modo'] == 'apagada':
                return
            for f in self.store._todas("SELECT * FROM ordenes_reales WHERE estado='enviando'"):
                self._resolver(f)
            nuevas = self.store._todas("SELECT * FROM ordenes WHERE run LIKE 'live:%' AND estado='ejecutada' AND id>? ORDER BY id", e['desde_orden'] or 0)
            for o in nuevas:
                if self.store._una("SELECT 1 x FROM ordenes_reales WHERE estado='enviando'"):
                    return  # nada nuevo mientras una orden real siga sin respuesta
                if not self.store._una('SELECT 1 x FROM ordenes_reales WHERE orden_paper=?', o['id']):
                    self._espejar(o, self.estado())
                self._guardar(desde_orden=o['id'])

    def _espejar(self, o, e):
        simbolo = o['run'].split(':', 1)[1]
        base = dict(orden_paper=o['id'], simbolo=simbolo, lado=o['lado'], modo=e['modo'])
        try:
            filtros = self.mercado.filters(simbolo)
            plan = self._plan_compra(simbolo, filtros, e) if o['lado'] == 'comprar' else self._plan_venta(simbolo, filtros)
        except MexcError as error:
            plan = dict(motivo=f'No se pudo preparar la orden: {error}')
        if 'params' not in plan:
            self._fila(**base, estado='omitida', motivo=plan['motivo'])
            return
        cliente_id = f'astro{o["id"]}'
        params = plan['params'] | dict(newClientOrderId=cliente_id)
        datos = dict(cliente_id=cliente_id, monto_usdt=plan.get('monto'), cantidad=plan.get('cantidad'))
        if e['modo'] == 'sombra':
            try:
                self.cliente.orden_prueba(params)
                self._fila(**base, **datos, estado='probada', motivo='MEXC validó la orden sin ejecutarla.')
            except MexcError as error:
                self._fila(**base, **datos, estado='error', motivo=str(error))
                self._fallo(simbolo, error)
            return
        fila = self._fila(**base, **datos, estado='enviando')  # antes de enviar: si se pierde la respuesta, se consulta por su id
        try:
            r = self.cliente.orden(params)
        except MexcUnavailable:
            return
        except MexcError as error:
            self._actualizar(fila, estado='error', motivo=str(error))
            self._fallo(simbolo, error)
            return
        self._actualizar(fila, mexc_id=str(r.get('orderId') or ''))
        self._resolver(self.store._una('SELECT * FROM ordenes_reales WHERE id=?', fila))

    def _fallo(self, simbolo, error):
        self.store.registrar_error('real', f'{simbolo}: {error}', 'MEXC rechazó la orden real', 'Compras reales en pausa; las ventas siguen.', '')
        self._guardar(compras_bloqueadas=True, motivo=str(error))

    def _plan_compra(self, simbolo, filtros, e):
        if e['compras_bloqueadas']:
            return dict(motivo=f'Compras reales en pausa: {e["motivo"]}')
        if self._resultado_hoy() <= -self.topes['perdida_diaria_usdt']:
            return dict(motivo='Se alcanzó la pérdida diaria máxima de la cartera Real.')
        libre = self._saldo('USDT')
        disponible = self.topes['tope_total_usdt'] - self._expuesto()
        monto = math.floor(min(self.topes['max_orden_usdt'], disponible, libre) * 100) / 100
        minimo = max(filtros['minimo_quote'], 1.0)
        if monto < minimo:
            if libre < minimo:
                return dict(motivo=f'Sin saldo suficiente: hay {libre:.2f} USDT libres y MEXC pide al menos {minimo:g}.')
            if disponible < minimo:
                return dict(motivo=f'Se alcanzó el tope de la cartera Real ({self.topes["tope_total_usdt"]:g} USDT).')
            return dict(motivo=f'El monto queda por debajo del mínimo de MEXC ({minimo:g} USDT).')
        return dict(params=dict(symbol=simbolo, side='BUY', type='MARKET', quoteOrderQty=f'{monto:.2f}'), monto=monto)

    def _plan_venta(self, simbolo, filtros):
        tenida = next((p['cantidad'] for p in self.posiciones() if p['simbolo'] == simbolo), 0.0)
        if tenida <= 0:
            return dict(motivo='La cartera Real no tiene posición en este activo.')
        paso = filtros['paso_cantidad']
        cantidad = math.floor(min(tenida, self._saldo(filtros.get('base') or simbolo.removesuffix('USDT'))) / paso + 1e-9) * paso
        if cantidad <= 0:
            return dict(motivo='La cuenta no tiene libre lo que compró la cartera Real.')
        return dict(params=dict(symbol=simbolo, side='SELL', type='MARKET', quantity=_texto(cantidad, paso)), cantidad=cantidad)

    def _resolver(self, f):
        """Consulta la orden por su id de cliente: así una respuesta perdida nunca se convierte en una orden duplicada."""
        try:
            d = self.cliente.consultar(f['simbolo'], f['cliente_id'])
        except MexcUnavailable:
            return
        except MexcError as error:
            self._actualizar(f['id'], estado='no_enviada', motivo=f'MEXC no tiene la orden: {error}')
            return
        if str(d.get('status')) not in FINALES:
            return  # sigue abierta: se vuelve a consultar en la próxima vuelta
        ejecutado, cotizado = float(d.get('executedQty') or 0), float(d.get('cummulativeQuoteQty') or 0)
        resultado = None
        if f['lado'] == 'vender' and ejecutado > 0:
            p = next((p for p in self.posiciones() if p['simbolo'] == f['simbolo']), None)
            resultado = cotizado - p['costo'] * min(1.0, ejecutado / p['cantidad']) if p else None
        self._actualizar(f['id'], estado='ejecutada' if ejecutado > 0 else 'sin_ejecutar', mexc_id=str(d.get('orderId') or f['mexc_id'] or ''),
                         ejecutado=ejecutado, cotizado=cotizado, resultado=resultado)

    def verificar(self):
        """Prueba la clave con una orden que MEXC valida sin ejecutarla: dice si de verdad puede operar Spot."""
        if not self.cliente.configurada:
            v = dict(ok=False, mensaje='Falta la clave de MEXC en .env.')
        else:
            try:
                minimo = max(self.mercado.filters('BTCUSDT')['minimo_quote'], 5.0)
                self.cliente.orden_prueba(dict(symbol='BTCUSDT', side='BUY', type='MARKET', quoteOrderQty=f'{minimo:.2f}', newClientOrderId='astroverifica'))
                v = dict(ok=True, mensaje='La clave puede operar Spot: MEXC validó una orden de prueba sin ejecutarla.')
            except MexcError as error:
                v = dict(ok=False, mensaje=str(error))
        return self._guardar(verificacion=v | dict(fecha=ahora_iso()))['verificacion']

    def resumen(self):
        """Lo que muestra el panel. No consulta a MEXC: el saldo sale de /api/cuenta-mexc."""
        return self.estado() | dict(topes=self.topes, clave_configurada=self.cliente.configurada, confirmacion=CONFIRMACION, solo_paper=SOLO_PAPER,
                                    posiciones=self.posiciones(), ordenes=self.ordenes(), expuesto=self._expuesto(), resultado_hoy=self._resultado_hoy())


class CambioModo(BaseModel):
    modo: str
    confirmacion: str = ''


def registrar(app, cartera, sesion):
    """Rutas del panel para la cartera Real. Ninguna manda una orden a mano: solo cambian el modo, muestran el estado o prueban la clave."""

    @app.get('/api/real', dependencies=[Depends(sesion)])
    def ver_real():
        """Cartera Real: modo, topes, posiciones y órdenes reales. Arranca apagada."""
        return cartera.resumen()

    @app.post('/api/real/modo', dependencies=[Depends(sesion)])
    def cambiar_modo(cambio: CambioModo):
        """Apaga, pone en sombra o enciende la cartera Real; encenderla pide escribir la confirmación."""
        try:
            return cartera.cambiar_modo(cambio.modo, cambio.confirmacion)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        except PermissionError as e:
            raise HTTPException(403, str(e)) from None

    @app.post('/api/real/verificar', dependencies=[Depends(sesion)])
    def verificar_clave():
        """Prueba si la clave puede operar Spot con una orden que MEXC valida sin ejecutarla."""
        return cartera.verificar()
