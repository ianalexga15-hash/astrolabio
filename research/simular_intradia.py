"""Simulador de investigación de las candidatas intradía: no es el ejecutor del bot ni autoriza órdenes.

Cada señal se conoce al cierre de su vela y solo permite comprar en la apertura de la siguiente. Stop a 2 ATR14 y
objetivo a 3 ATR14 de la última vela cerrada, máximo 16 velas. Si una vela toca ambos, cuenta primero el stop; con un
salto bajo el stop se sale a la apertura disponible. Comisión en entrada y salida y deslizamiento en lo que se ejecuta
a mercado. El objetivo es una orden límite y sale a su precio, pero paga comisión: no se supone llenado maker gratis.
"""
import numpy as np
import pandas as pd

PASO_MS = 15 * 60_000
COLUMNAS = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time']


def auditar(df, fin_ms):
    """Continuidad, duplicados, coherencia OHLC, volumen y cierre. Solo informa; no corrige nada."""
    t = df.open_time
    unicos = np.sort(t.drop_duplicates().to_numpy())
    dif = np.diff(unicos)
    valores = df[COLUMNAS].to_numpy(dtype=float)
    return dict(
        velas=int(len(df)), desde=int(unicos[0]) if len(unicos) else None, hasta=int(unicos[-1]) if len(unicos) else None,
        duplicados=int(t.duplicated().sum()), desordenadas=int((t.diff().iloc[1:] <= 0).sum()),
        huecos=int((dif > PASO_MS).sum()), velas_faltantes=int(((dif[dif > PASO_MS] // PASO_MS) - 1).sum()),
        ohlc_incoherente=int(((df.high < df[['open', 'close', 'low']].max(axis=1)) | (df.low > df[['open', 'close']].min(axis=1))).sum()),
        precio_no_positivo=int((df[['open', 'high', 'low', 'close']] <= 0).any(axis=1).sum()), volumen_negativo=int((df.volume < 0).sum()),
        volumen_cero=int((df.volume == 0).sum()), no_finitos=int((~np.isfinite(valores)).any(axis=1).sum()),
        abiertas=int((df.open_time + PASO_MS > fin_ms).sum()),  # MEXC marca el cierre en el inicio de la vela siguiente: se compara por inicio
    )


def simular(s, entrada, comision=0.0005, deslizamiento_bps=2.0, capital=10_000.0, riesgo=0.0025, exposicion_max=0.20,
            stop_atr=2.0, objetivo_atr=3.0, max_velas=16):
    """Una posición a la vez. `entrada[i]` verdadero: la señal de la vela i-1 permite comprar en la apertura de i."""
    desliz = deslizamiento_bps / 10_000
    o, h, l, c, atr = (s[k].to_numpy(dtype=float) for k in ('open', 'high', 'low', 'close', 'atr14'))
    t, senal = s.open_time.to_numpy(), np.asarray(entrada, dtype=bool)
    efectivo, pos, ops, curva = float(capital), None, [], np.empty(len(s))

    def cerrar(i, precio, motivo):
        nonlocal efectivo, pos
        neto = pos['cantidad'] * precio * (1 - comision)
        efectivo += neto
        ops.append(dict(entrada=int(pos['ts']), salida=int(t[i]), precio_entrada=pos['precio'], precio_salida=float(precio), cantidad=pos['cantidad'],
                        resultado=neto - pos['costo'], motivo=motivo, velas=i - pos['i']))
        pos = None

    for i in range(len(s)):
        if pos is not None and i - pos['i'] >= max_velas:
            cerrar(i, o[i] * (1 - desliz), 'tiempo')
        if pos is None and senal[i] and i > 0 and np.isfinite(atr[i - 1]) and atr[i - 1] > 0:
            precio = o[i] * (1 + desliz)
            atr_precio = atr[i - 1] * c[i - 1]  # el generador da ATR14 dividido entre el cierre; aquí se pasa a precio
            stop, objetivo = precio - stop_atr * atr_precio, precio + objetivo_atr * atr_precio
            cantidad = min(efectivo * riesgo / (precio - stop), efectivo * exposicion_max / precio)  # sin posición, efectivo = patrimonio
            costo = cantidad * precio * (1 + comision)
            efectivo -= costo
            pos = dict(i=i, ts=t[i], precio=precio, cantidad=cantidad, costo=costo, stop=stop, objetivo=objetivo)
        if pos is not None:
            if pos['i'] < i and o[i] <= pos['stop']:  # salto bajo el stop: la apertura disponible, nunca el precio del stop
                cerrar(i, o[i] * (1 - desliz), 'stop')
            elif pos['i'] < i and o[i] >= pos['objetivo']:  # salto sobre el objetivo: la orden límite se llena a la apertura
                cerrar(i, o[i], 'objetivo')
            elif l[i] <= pos['stop']:  # si la vela toca stop y objetivo, sin saber el orden, cuenta primero el stop
                cerrar(i, pos['stop'] * (1 - desliz), 'stop')
            elif h[i] >= pos['objetivo']:
                cerrar(i, pos['objetivo'], 'objetivo')
        if pos is not None and i == len(s) - 1:
            cerrar(i, c[i] * (1 - desliz), 'fin')
        curva[i] = efectivo + (pos['cantidad'] * c[i] if pos else 0.0)
    return ops, pd.Series(curva, index=s.open_time.to_numpy())


def resumen(ops, curva, capital):
    n = len(ops)
    ganado = sum(o['resultado'] for o in ops if o['resultado'] > 0)
    perdido = -sum(o['resultado'] for o in ops if o['resultado'] < 0)
    return dict(operaciones=n, acierto=sum(o['resultado'] > 0 for o in ops) / n if n else None,
                factor_beneficio=ganado / perdido if perdido else None, resultado_neto=float(curva.iloc[-1] - capital),
                rendimiento=float(curva.iloc[-1] / capital - 1), drawdown=float((1 - curva / curva.cummax()).max()),
                duracion_media_h=sum(o['velas'] for o in ops) / n * PASO_MS / 3_600_000 if n else None,
                exposicion=sum(o['velas'] for o in ops) / len(curva) if len(curva) else 0.0,
                salidas={m: sum(o['motivo'] == m for o in ops) for m in ('objetivo', 'stop', 'tiempo', 'fin')})


def comprar_y_mantener(s, comision, deslizamiento_bps):
    """Referencia pasiva con las mismas fechas y costos: compra en la primera apertura y vende en el último cierre."""
    desliz = deslizamiento_bps / 10_000
    precio = s.open.iloc[0] * (1 + desliz)
    curva = s.close / precio
    return dict(rendimiento=float(s.close.iloc[-1] * (1 - desliz) * (1 - comision) / (precio * (1 + comision)) - 1),
                drawdown=float((1 - curva / curva.cummax()).max()))
