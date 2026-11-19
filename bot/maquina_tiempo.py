"""Máquina del tiempo: antes de comprar, repite miles de veces los próximos días con las velas recientes del propio activo.

Idea de trader-timemachine (github.com/jakeschincariol/day-trader-skill), adaptada a velas diarias y a las salidas
reales del bot: stop a `stop_atr` ATR, el mismo objetivo (`Limites.precio_objetivo`), stop móvil a `trailing_atr` ATR del cierre,
punto de equilibrio con `proteger_atr` (como `paper.mover_trailing`) y, si una vela toca ambos, primero el stop. Es una simulación
con la historia reciente, no una predicción.
"""
import numpy as np

REPLAYS, VENTANA, HORIZONTE, SEMILLA = 10_000, 60, 60, 19


def repasar(ohlc, atr_abs, limites, replays=REPLAYS, ventana=VENTANA, horizonte=HORIZONTE, semilla=SEMILLA):
    """`ohlc`: velas diarias cerradas (apertura, máximo, mínimo, cierre); la última es la de hoy y su cierre, la entrada.

    Cada día simulado sale de una de las últimas `ventana` velas al azar, escalada al cierre anterior. Devuelve qué
    parte de los repasos llegó primero al objetivo, al stop o siguió abierta tras `horizonte` días, y el resultado
    medio en R (1 R es lo que se pierde en el stop inicial) ya descontando comisión y deslizamiento. Sin historia
    suficiente devuelve None.
    """
    ohlc = np.asarray(ohlc, dtype=float)
    if len(ohlc) <= ventana or not np.isfinite(atr_abs) or atr_abs <= 0:
        return None
    razones = ohlc[-ventana:] / ohlc[-ventana - 1:-1, 3:4]  # cada vela relativa al cierre anterior
    entrada = ohlc[-1, 3]
    riesgo = limites.stop_atr * atr_abs
    objetivo = limites.precio_objetivo(entrada, atr_abs)
    rng = np.random.default_rng(semilla)
    precio, stop = np.full(replays, entrada), np.full(replays, entrada - riesgo)
    salida, tipo = np.full(replays, np.nan), np.zeros(replays, dtype=int)  # tipo: 0 abierta, 1 objetivo, 2 stop
    for _ in range(horizonte):
        vivas = tipo == 0
        if not vivas.any():
            break
        o, h, l, c = (precio[:, None] * razones[rng.integers(0, ventana, replays)]).T
        al_stop = vivas & (l <= stop)
        al_objetivo = vivas & ~al_stop & (h >= objetivo)
        salida[al_stop] = np.minimum(o, stop)[al_stop]  # un salto por debajo del stop sale a la apertura
        salida[al_objetivo] = np.maximum(o, objetivo)[al_objetivo]
        tipo[al_stop], tipo[al_objetivo] = 2, 1
        sigue = vivas & ~al_stop & ~al_objetivo
        stop[sigue] = np.maximum(stop[sigue], c[sigue] - limites.trailing_atr * atr_abs)  # el stop solo sube
        if limites.proteger_atr:  # punto de equilibrio con el mismo costo que agent.py y reflejo.py pasan a paper.mover_trailing
            gano = sigue & (c >= entrada + limites.proteger_atr * atr_abs)
            stop[gano] = np.maximum(stop[gano], entrada * (1 + 2 * limites.comision_efectiva + limites.deslizamiento_bps / 10_000))
        precio = np.where(sigue, c, precio)
    salida[tipo == 0] = precio[tipo == 0]
    costo = 2 * (limites.comision_efectiva + limites.deslizamiento_bps / 10_000) * entrada / riesgo  # comisión y deslizamiento al entrar y al salir, como paper
    return dict(objetivo=float(np.mean(tipo == 1)), stop=float(np.mean(tipo == 2)), abiertas=float(np.mean(tipo == 0)),
                r_medio=float(np.mean((salida - entrada) / riesgo) - costo))
