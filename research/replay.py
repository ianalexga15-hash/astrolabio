"""Replay histórico para comparar con el mismo periodo y costos: regla sin LLM, agente con LLM y comprar y mantener.

Queda etiquetado como replay y separado de la conexión actual. Por defecto usa validación; TE exige confirmación explícita.
Ejecuta en la apertura siguiente con velas diarias: no reproduce el reflejo por segundo, porque no hay historia de cada segundo.

    python research/replay.py --decisor regla --dias 60
    python research/replay.py --decisor llm --dias 60
    python research/replay.py --decisor regla --cartera --dias 400
    python research/replay.py --decisor regla --cartera --dias 400 --maquina no   # comparar sin la máquina del tiempo
    python research/replay.py --decisor regla --cartera --dias 400 --tope 3 --prioridad repaso   # cupos a los de mejor repaso
    python research/replay.py --decisor regla --cartera --dias 5000 --pausa 3   # 3 días sin comprar tras un stop con pérdida
    python research/replay.py --decisor regla --cartera --dias 5000 --objetivo-pct 0   # objetivo en ATR, como antes del 2026-11-13
    python research/replay.py --decisor regla --cartera --dias 5000 --filtro-minimo ""   # sin el filtro mínimo, como antes del 2026-11-13
"""
import argparse
import json
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import httpx
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding='utf-8')

from bot import data, features, llm, maquina_tiempo, mexc, model  # noqa: E402
from bot.agent import HISTORIA, Agente  # noqa: E402
from bot.config import cargar_ajustes, cargar_limites, cargar_universo  # noqa: E402
from bot.report import resumen_grupo, resumen_run  # noqa: E402
from bot.store import Store  # noqa: E402
from research import lab  # noqa: E402


class MercadoFijo:
    """El replay no consulta precios: usa los archivos guardados y los filtros reales de cada par."""

    def __init__(self):
        self.mexc = mexc.Mexc()

    def filters(self, simbolo):
        return self.mexc.filters(simbolo)


def filas_de(simbolo):
    ruta = RAIZ / 'data/cartera' / f'{simbolo}.csv'
    if not ruta.exists():
        ruta = RAIZ / 'data/processed' / f'{simbolo}_1d.csv'
    return pd.read_csv(ruta)[data.COLUMNAS].values.tolist()


def fechas_conjunto(conjunto):
    """Fechas de emisión de VA o TE según la partición de BTC, la misma en toda la cartera."""
    t = lab.tabla_comun(data.add_target(features.add_indicators(pd.read_csv(RAIZ / 'data/processed/BTCUSDT_1d.csv'))))
    return lab.preparar(t, ['ret'])[f'emision_{conjunto}']


def correr(store, limites, m, proponente, simbolo, run, fechas, mercado):
    filas = filas_de(simbolo)
    indice = {data.fecha(f[0]): i for i, f in enumerate(filas)}
    posiciones = [indice[f] for f in fechas if f in indice and indice[f] >= 60 and indice[f] + 1 < len(filas)]
    if not posiciones:
        return None
    agente = Agente(store=store, mercado=mercado, modelo=m, proponente=proponente, limites=limites, run_id=run)
    return agente.replay(posiciones[0], posiciones[-1] + 1, filas)


def te_abierto(store, decisor):
    """Corridas de TE ya registradas con este decisor, de un activo o de la cartera."""
    return [r['id'] for r in store.runs() if r['id'].startswith((f'replay-TE-{decisor}-', f'replay-cartera-TE-{decisor}-'))]


def puntaje(agente, filas, i):
    """R medio de la máquina del tiempo con la misma historia que usa el agente ese día; sin opinión, al final."""
    tabla = features.add_indicators(agente._validar(filas[max(0, i - HISTORIA + 1):i + 1]))
    r = maquina_tiempo.repasar(tabla[data.PRECIOS].to_numpy(dtype=float), float(tabla.atr14.iloc[-1] * tabla.close.iloc[-1]), agente.limites)
    return r['r_medio'] if r else float('-inf')


def por_fecha(agentes, fechas):
    """Replay día por día: los activos sin posición pasan en orden de su repaso, así el tope diario da los cupos a los mejores."""
    indices = {s: {data.fecha(f[0]): i for i, f in enumerate(filas)} for s, (_, filas) in agentes.items()}
    for f in fechas:
        listos = [(s, indices[s][f]) for s, (_, filas) in agentes.items() if indices[s].get(f, -1) >= 60 and indices[s][f] + 1 < len(filas)]
        clave = {s: -puntaje(*agentes[s], i) if agentes[s][0].cuenta.cantidad <= 0 else float('inf') for s, i in listos}  # con posición no compra
        for s, i in sorted(listos, key=lambda x: clave[x[0]]):
            agentes[s][0].replay(i, i + 1, agentes[s][1])


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--decisor', choices=['regla', 'llm'], required=True)
    a.add_argument('--dias', type=int, default=60, help='Últimos días del conjunto elegido')
    a.add_argument('--conjunto', choices=['VA', 'TE'], default='VA')
    a.add_argument('--simbolo', default='BTCUSDT')
    a.add_argument('--cartera', action='store_true', help='Toda la cartera a cupos iguales')
    a.add_argument('--confirmo-abrir-te', action='store_true')
    a.add_argument('--maquina', choices=['si', 'no'], help='Enciende o apaga la máquina del tiempo; por defecto, la configuración')
    a.add_argument('--tope', type=int, help='Compras nuevas por día en la cartera; por defecto, la configuración (0 es sin tope)')
    a.add_argument('--objetivo', type=float, help='ATR del objetivo de ganancia; por defecto, la configuración')
    a.add_argument('--objetivo-pct', type=float, help='Meta por operación: 0.13 vende a +13 %% más la comisión del par; 0 usa el objetivo en ATR')
    a.add_argument('--proteger', type=float, help='ATR de ganancia con los que el stop sube a la entrada más costos; 0 lo apaga')
    a.add_argument('--pausa', type=float, help='Días sin comprar un activo tras un stop que cerró perdiendo; 0 la apaga')
    a.add_argument('--filtro-minimo', help="Filtro técnico si la regla de VA no trae ninguno: sma20, o '' para apagarlo; por defecto, la configuración")
    a.add_argument('--modelo-cartera', help='Carpeta en models/ del modelo de cartera a probar; por defecto, el de CARTERA.txt. No cambia el modelo activo')
    a.add_argument('--prioridad', choices=['lista', 'repaso'], default='lista',
                   help='Orden de cada día en la cartera: lista, el del universo; repaso, primero el mejor de la máquina del tiempo')
    args = a.parse_args()
    if args.conjunto == 'TE' and not args.confirmo_abrir_te:
        raise SystemExit('TE se evalúa una sola vez con el sistema congelado. Usa --confirmo-abrir-te solo con el modelo final de T4.')
    if args.cartera and args.decisor == 'llm':
        raise SystemExit('El LLM tarda unos segundos por decisión: el replay de toda la cartera con LLM tomaría horas. Usa un solo activo.')

    aj = cargar_ajustes()
    store = Store(aj.db)
    if args.conjunto == 'TE' and (previas := te_abierto(store, args.decisor)):
        raise SystemExit(f'TE ya se abrió con el decisor {args.decisor} ({previas[0]}). Se evalúa una sola vez con el sistema congelado: '
                         'otra apertura ya no sería una prueba limpia. Las corridas existentes se conservan.')
    limites = cargar_limites(aj.raiz, store)
    if args.maquina:
        limites = replace(limites, maquina_tiempo=args.maquina == 'si')
    if args.objetivo is not None:
        limites = replace(limites, objetivo_atr=args.objetivo).validar()
    if args.objetivo_pct is not None:
        limites = replace(limites, objetivo_pct=args.objetivo_pct).validar()
    if args.proteger is not None:
        limites = replace(limites, proteger_atr=args.proteger).validar()
    if args.tope is not None:
        limites = replace(limites, max_compras_dia=args.tope).validar()
    if args.pausa is not None:
        limites = replace(limites, pausa_tras_perdida_dias=args.pausa).validar()
    if args.filtro_minimo is not None:
        limites = replace(limites, filtro_minimo=args.filtro_minimo).validar()
    leer = lambda nombre: model.cargar(aj.raiz / 'models' / (aj.raiz / 'models' / nombre).read_text(encoding='utf-8').strip())
    principal = leer('ACTIVO.txt')
    modelo_cartera = model.cargar(aj.raiz / 'models' / args.modelo_cartera) if args.modelo_cartera else leer('CARTERA.txt')
    if args.decisor == 'llm':
        proponente = llm.ProponenteLLM(http=httpx.Client(), url=f'http://127.0.0.1:{aj.puerto}/llm/chat', clave=aj.llm_key, modelo=aj.llm_modelo)
    else:
        proponente = llm.ProponenteRegla()
    fechas = fechas_conjunto(args.conjunto)[-args.dias:]
    mercado = MercadoFijo()
    sello = int(time.time())
    inicio = time.perf_counter()
    nombre = ('con LLM' if args.decisor == 'llm' else 'regla sin LLM') + (', con máquina del tiempo' if limites.maquina_tiempo else '') \
        + (f', tope de {limites.max_compras_dia:g} compras por día' if limites.max_compras_dia else '') \
        + (', cupos por repaso' if args.prioridad == 'repaso' else '') \
        + (f', punto de equilibrio a {limites.proteger_atr:g} ATR' if limites.proteger_atr else '') \
        + (f', pausa de {limites.pausa_tras_perdida_dias:g} días tras un stop con pérdida' if limites.pausa_tras_perdida_dias else '') \
        + (f', filtro mínimo {limites.filtro_minimo.upper()}' if limites.filtro_minimo else '') \
        + (f', objetivo a +{limites.objetivo_pct * 100:g} % más la comisión del par' if limites.objetivo_pct
           else f', objetivo a {limites.objetivo_atr:g} ATR' if args.objetivo is not None else '') \
        + (f', modelo de cartera {modelo_cartera.version}' if args.modelo_cartera else '')

    if args.cartera:
        conjunto = modelo_cartera
        simbolos = cargar_universo(aj.raiz, limites.simbolo)
        cupo = limites.capital_inicial / len(simbolos)
        grupo = f'replay-cartera-{args.conjunto}-{args.decisor}-{sello}'
        etiqueta = f'Replay {args.conjunto} de {len(simbolos)} activos, {nombre}, {fechas[0]} a {fechas[-1]}'
        agentes = {}
        for s in simbolos:
            run = f'{grupo}:{s}'
            m = principal if s == limites.simbolo else conjunto
            lim_s = replace(limites, simbolo=s, capital_inicial=cupo)
            store.abrir_run(run, 'replay', etiqueta, dict(grupo_etiqueta=etiqueta, modelo=m.version, decisor=args.decisor,
                            limites=asdict(lim_s), conjunto=args.conjunto, desde=fechas[0], hasta=fechas[-1], prioridad=args.prioridad))
            if args.prioridad == 'repaso':
                agentes[s] = (Agente(store=store, mercado=mercado, modelo=m, proponente=proponente, limites=lim_s, run_id=run), filas_de(s))
                continue
            r = correr(store, lim_s, m, proponente, s, run, fechas, mercado)
            print(s, r and r['ciclos'], flush=True)
        if agentes:
            por_fecha(agentes, fechas)
        resumen = resumen_grupo(store, grupo, limites.capital_inicial, limites.comision, etiqueta, 'replay')
    else:
        run = f'replay-{args.conjunto}-{args.decisor}-{args.simbolo}-{sello}'
        etiqueta = f'Replay {args.conjunto} de {args.simbolo}, {nombre}, {fechas[0]} a {fechas[-1]}'
        m = principal if args.simbolo == limites.simbolo else modelo_cartera
        lim_s = replace(limites, simbolo=args.simbolo)
        store.abrir_run(run, 'replay', etiqueta, dict(modelo=m.version, decisor=args.decisor,
                        limites=asdict(lim_s), conjunto=args.conjunto, desde=fechas[0], hasta=fechas[-1]))
        correr(store, lim_s, m, proponente, args.simbolo, run, fechas, mercado)
        resumen = resumen_run(store, run, limites.capital_inicial, limites.comision)
    print(json.dumps(dict(segundos=round(time.perf_counter() - inicio, 1), **resumen), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
