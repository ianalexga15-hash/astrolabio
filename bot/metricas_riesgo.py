"""Rendimiento y riesgo de una serie de patrimonio: volatilidad anual, Sharpe, Sortino, VaR y CVaR históricos.

Los rendimientos son simples y en decimales. Se anualiza con 365 periodos porque MEXC cotiza todos los días.
Sharpe y Sortino usan una tasa libre de riesgo y una meta anuales efectivas (0 por defecto), convertidas a su
equivalente diario. VaR y CVaR son históricos, a un periodo, y se reportan como pérdida positiva.
"""
import numpy as np

PERIODOS = 365


def var_cvar(rendimientos, c=0.95):
    """VaR: cuantil c de las pérdidas por inversa de la acumulada. CVaR: promedio de la fracción 1 - c de pérdidas
    más severas, con peso fraccionario en la última para conservar la masa exacta de la cola."""
    perdidas = np.sort(-np.asarray(rendimientos, dtype=float))[::-1]
    masa = (1 - c) * len(perdidas)
    pesos = np.clip(masa - np.arange(len(perdidas)), 0, 1)
    return float(np.quantile(perdidas, c, method='inverted_cdf')), float(perdidas @ pesos / masa)


def metricas_riesgo(patrimonio, tasa_anual=0.0, meta_anual=0.0, c=0.95, periodos=PERIODOS):
    """Con menos de dos rendimientos no hay dispersión que medir. Con desviación cero, Sharpe o Sortino quedan en None."""
    serie = np.asarray(patrimonio, dtype=float)
    r = serie[1:] / serie[:-1] - 1
    vacio = dict(observaciones=len(r), volatilidad_anual=None, sharpe=None, sortino=None, var=None, cvar=None)
    if len(r) < 2 or not np.isfinite(r).all():
        return vacio
    rf = (1 + tasa_anual) ** (1 / periodos) - 1
    meta = (1 + meta_anual) ** (1 / periodos) - 1
    exceso = r - rf
    desv = float(exceso.std(ddof=1))
    baja = float(np.sqrt(np.mean(np.minimum(r - meta, 0) ** 2)))
    var, cvar = var_cvar(r, c)
    raiz = np.sqrt(periodos)
    return dict(observaciones=len(r), volatilidad_anual=desv * raiz, sharpe=float(exceso.mean() / desv * raiz) if desv > 0 else None,
                sortino=float((r.mean() - meta) / baja * raiz) if baja > 0 else None, var=var, cvar=cvar)
