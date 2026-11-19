"""Simulador Paper: dinero virtual. Respeta saldo, precisión, mínimo del par, comisión y deslizamiento."""
import math
from dataclasses import dataclass


class OrdenRechazada(Exception):
    pass


@dataclass(frozen=True)
class Filtros:
    paso_cantidad: float
    minimo_quote: float


@dataclass
class Cuenta:
    efectivo: float
    cantidad: float = 0.0
    precio_medio: float = 0.0
    stop: float | None = None
    objetivo: float | None = None
    costos: float = 0.0
    costo_entrada: float = 0.0
    armada: dict | None = None  # compra autorizada por el ciclo diario que espera confirmación en vivo
    atr_abs: float | None = None
    entrada_ms: float | None = None


@dataclass(frozen=True)
class Ejecucion:
    lado: str
    cantidad: float
    precio: float
    comision: float
    motivo: str = ''
    resultado: float | None = None


def _precio_valido(precio):
    if not (isinstance(precio, (int, float)) and math.isfinite(precio) and precio > 0):
        raise OrdenRechazada(f'Precio no válido: {precio}.')


def _al_paso(cantidad, paso):
    return round(math.floor(cantidad / paso + 1e-9) * paso, 12)


def precio_por_libro(niveles, monto_quote=None, cantidad=None):
    """Precio medio al recorrer el libro: compra gastando monto_quote o vende cantidad, nivel por nivel.

    Devuelve (precio, cubierto). Si el libro visible no alcanza, el resto se valúa al peor precio visible: supuesto conservador.
    """
    if not niveles:
        return None, False
    restante = monto_quote if monto_quote is not None else cantidad
    tomado = gastado = 0.0
    for precio, disponible in niveles:
        if restante <= 1e-12:
            break
        parte = min(disponible, restante / precio) if monto_quote is not None else min(disponible, restante)
        restante -= parte * precio if monto_quote is not None else parte
        tomado += parte
        gastado += parte * precio
    cubierto = restante <= 1e-9
    if not cubierto:
        peor = niveles[-1][0]
        extra = restante / peor if monto_quote is not None else restante
        tomado += extra
        gastado += extra * peor
    return gastado / tomado, cubierto


def comprar(c, precio, monto_quote, filtros, comision, deslizamiento_bps, motivo=''):
    _precio_valido(precio)
    if monto_quote < filtros.minimo_quote:
        raise OrdenRechazada(f'Orden de {monto_quote:.2f} por debajo del mínimo del par ({filtros.minimo_quote}).')
    if monto_quote > c.efectivo:
        raise OrdenRechazada(f'Saldo insuficiente: pide {monto_quote:.2f} y hay {c.efectivo:.2f} sin apalancamiento.')
    px = precio * (1 + deslizamiento_bps / 10_000)
    cantidad = _al_paso(monto_quote / (px * (1 + comision)), filtros.paso_cantidad)
    if cantidad <= 0:
        raise OrdenRechazada(f'El monto no alcanza un paso de cantidad ({filtros.paso_cantidad}).')
    nocional = cantidad * px
    costo = nocional * comision
    if nocional < filtros.minimo_quote:
        raise OrdenRechazada(f'Nocional de {nocional:.2f} por debajo del mínimo del par ({filtros.minimo_quote}).')
    c.efectivo -= nocional + costo
    c.cantidad = round(c.cantidad + cantidad, 12)
    c.precio_medio = px
    c.costos += costo
    c.costo_entrada = nocional + costo
    return Ejecucion('comprar', cantidad, px, costo, motivo)


def vender(c, precio, filtros, comision, deslizamiento_bps, motivo=''):
    if c.cantidad <= 0:
        raise OrdenRechazada('No hay posición que vender; no se permiten ventas en corto.')
    return _liquidar(c, precio * (1 - deslizamiento_bps / 10_000), comision, motivo)


def _liquidar(c, px, comision, motivo):
    _precio_valido(px)
    cantidad = c.cantidad
    nocional = cantidad * px
    costo = nocional * comision
    resultado = nocional - costo - c.costo_entrada
    c.efectivo += nocional - costo
    c.cantidad = 0.0
    c.precio_medio = 0.0
    c.stop = c.objetivo = c.atr_abs = c.entrada_ms = None
    c.costo_entrada = 0.0
    c.costos += costo
    return Ejecucion('vender', cantidad, px, costo, motivo, resultado)


def revisar_stops(c, vela, filtros, comision, deslizamiento_bps):
    """Niveles evaluados con la vela. Si ambos se tocaron, se asume el peor caso: primero el stop."""
    if c.cantidad <= 0:
        return None
    slip = 1 - deslizamiento_bps / 10_000
    if c.stop is not None and vela['low'] <= c.stop:
        return _liquidar(c, min(vela['open'], c.stop) * slip, comision, 'stop')
    if c.objetivo is not None and vela['high'] >= c.objetivo:
        return _liquidar(c, max(vela['open'], c.objetivo) * slip, comision, 'objetivo')
    return None


def mover_trailing(c, cierre, atr_abs, k, proteger_atr=0.0, costo=0.0):
    """El stop solo sube: asegura ganancia y nunca aumenta el riesgo.

    Con `proteger_atr`, cuando el precio ya ganó esa cantidad de ATR de la entrada, el stop sube a la entrada más `costo`
    (comisiones y deslizamiento de ida y vuelta): desde ahí la posición ya no termina en pérdida, salvo un salto de precio.
    """
    if c.cantidad > 0 and c.stop is not None and math.isfinite(atr_abs):
        c.stop = max(c.stop, cierre - k * atr_abs)
        if proteger_atr and c.atr_abs and cierre >= c.precio_medio + proteger_atr * c.atr_abs:
            c.stop = max(c.stop, c.precio_medio * (1 + costo))


def patrimonio(c, precio):
    return c.efectivo + c.cantidad * precio
