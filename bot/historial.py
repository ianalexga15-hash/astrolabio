"""Historial de operaciones en vivo: cada compra con su venta, su resultado y si se compró en alta o en baja respecto al día anterior."""
from datetime import datetime

from fastapi import Depends

DIA_MS = 86_400_000
NIVELES = ((1.0, 'sobre el máximo del día anterior'), (2 / 3, 'en alta'), (1 / 3, 'a media altura'), (0.0, 'en baja'))


def _ms(iso):
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def altura(precio, velas, ms):
    """Posición del precio en el rango del último día cerrado antes de la compra: 0 es su mínimo y 1 su máximo."""
    previas = [v for v in velas if v['open_time'] + DIA_MS <= ms]
    if not previas:
        return None
    v = previas[-1]
    rango = v['high'] - v['low']
    return (precio - v['low']) / rango if rango > 0 else None


def etiqueta(a):
    if a is None:
        return 'sin dato'
    return next((nombre for minimo, nombre in NIVELES if a >= minimo), 'bajo el mínimo del día anterior')


def historial(ordenes, velas_por_simbolo):
    """Pares compra-venta en orden de compra; la venta cierra la compra anterior del mismo activo. Lo más reciente primero."""
    abiertas, filas = {}, []
    for o in sorted((o for o in ordenes if o['estado'] == 'ejecutada'), key=lambda o: (o['creado'], o['id'])):
        simbolo = o['run'].split(':', 1)[1]
        if o['lado'] == 'comprar':
            a = altura(o['precio'], velas_por_simbolo.get(simbolo, []), _ms(o['creado']))
            fila = dict(simbolo=simbolo, compra=o['creado'], precio_compra=o['precio'], cantidad=o['cantidad'], altura=a, etiqueta=etiqueta(a), estado='abierta',
                        costos_compra=o.get('modelo_costos'), venta=None, precio_venta=None, motivo_venta=None, resultado=None, rendimiento=None, horas=None)
            abiertas[simbolo] = fila
            filas.append(fila)
        elif o['lado'] == 'vender' and simbolo in abiertas:
            fila = abiertas.pop(simbolo)
            fila |= dict(estado='cerrada', venta=o['creado'], precio_venta=o['precio'], motivo_venta=o['motivo'], resultado=o['resultado'],
                         rendimiento=o['precio'] / fila['precio_compra'] - 1, horas=(_ms(o['creado']) - _ms(fila['compra'])) / 3_600_000)
    return filas[::-1]


def registrar(app, store, sesion):
    @app.get('/api/historial', dependencies=[Depends(sesion)])
    def ver_historial():
        """Historial de operaciones en vivo: cada compra con su venta, su resultado y si se compró en alta o en baja respecto al día anterior."""
        ordenes = store.grupo('ordenes', 'live')
        simbolos = {o['run'].split(':', 1)[1] for o in ordenes}
        return historial(ordenes, {s: store.velas(s, limite=400) for s in simbolos})
