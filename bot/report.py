"""Resultados por corrida: en vivo, replay con LLM y replay sin LLM, siempre con el mismo cálculo."""
import csv
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np

from bot.metricas_riesgo import metricas_riesgo

TABLAS_EVIDENCIA = ('runs', 'decisiones', 'ordenes', 'patrimonio', 'errores', 'procesadas', 'estado', 'configuracion')  # nunca 'acceso'


def resumen_run(store, run, capital, comision):
    info = store.run(run) or {}
    marcas = store.patrimonio(run)
    ordenes = store.ordenes(run)
    decisiones = store.decisiones(run, limite=100_000)
    ejecutadas = [o for o in ordenes if o['estado'] == 'ejecutada']
    cerradas = [o for o in ejecutadas if o['lado'] == 'vender']
    latencias = [d['latencia_ms'] for d in decisiones if d['latencia_ms']]
    resumen = dict(
        run=run, tipo=info.get('tipo'), etiqueta=info.get('etiqueta'), ciclos=len(decisiones), periodo=None, rendimiento=None, drawdown=None,
        comprar_y_mantener=None, operaciones=len(cerradas), win_rate=float(np.mean([o['resultado'] > 0 for o in cerradas])) if cerradas else None,
        costos=float(sum(o['comision'] for o in ejecutadas)), ordenes_rechazadas=sum(o['estado'] == 'rechazada' for o in ordenes),
        acciones_rechazadas=sum(not d['aprobada'] for d in decisiones), latencia_media_ms=float(np.mean(latencias)) if latencias else None,
        patrimonio_final=None, **metricas_riesgo([]))
    if marcas:
        serie = np.array([m['patrimonio'] for m in marcas], dtype=float)
        picos = np.maximum.accumulate(np.concatenate([[capital], serie]))[1:]
        p0, p1 = marcas[0]['precio'], marcas[-1]['precio']
        resumen |= dict(periodo=[marcas[0]['fecha'], marcas[-1]['fecha']], rendimiento=float(serie[-1] / capital - 1), patrimonio_final=float(serie[-1]),
                        drawdown=float(((picos - serie) / picos).max()),
                        comprar_y_mantener=float(p1 / p0 * (1 - comision) / (1 + comision) - 1), **metricas_riesgo(np.r_[capital, serie]))
    return resumen


def _corridas(store, prefijo, runs):
    return [r['id'] for r in store.runs_de(prefijo)] if runs is None else list(runs)


def serie_grupo(store, prefijo, capital, runs=None):
    """Patrimonio conjunto por fecha. Antes de su primera marca, cada activo cuenta su cupo en efectivo.

    `runs`: las corridas que hoy forman la cartera; un activo que salió del universo ya no es dinero de ella.
    Por defecto, todas las del grupo, como en un replay. precio es una canasta de igual peso con base 100:
    la referencia de comprar y mantener toda la cartera.
    """
    runs = _corridas(store, prefijo, runs)
    if not runs:
        return []
    cupo = capital / len(runs)
    marcas = {r: {m['fecha']: m for m in store.patrimonio(r, limite=100_000)} for r in runs}
    fechas = sorted({f for m in marcas.values() for f in m})
    ultimo = {r: cupo for r in marcas}
    relativo = {r: 1.0 for r in marcas}
    base = {}
    salida = []
    for f in fechas:
        for r, m in marcas.items():
            if f in m:
                ultimo[r] = m[f]['patrimonio']
                base.setdefault(r, m[f]['precio'])
                relativo[r] = m[f]['precio'] / base[r]
        salida.append(dict(fecha=f, patrimonio=sum(ultimo.values()), precio=100 * float(np.mean(list(relativo.values())))))
    return salida


def resumen_grupo(store, prefijo, capital, comision, etiqueta, tipo, runs=None):
    """El mismo resumen de una corrida, sumando los activos del grupo; con `runs`, solo los de la cartera actual."""
    runs = _corridas(store, prefijo, runs)
    elegidas = set(runs)
    filas = [o for o in store.grupo('ordenes', prefijo, limite=1_000_000) if o['run'] in elegidas]
    decisiones = [d for d in store.grupo('decisiones', prefijo, limite=1_000_000) if d['run'] in elegidas]
    ejecutadas = [o for o in filas if o['estado'] == 'ejecutada']
    cerradas = [o for o in ejecutadas if o['lado'] == 'vender']
    latencias = [d['latencia_ms'] for d in decisiones if d['latencia_ms']]
    serie = serie_grupo(store, prefijo, capital, runs)
    resumen = dict(run=prefijo, tipo=tipo, etiqueta=etiqueta, activos=len(runs), ciclos=len(decisiones), periodo=None, rendimiento=None, drawdown=None, comprar_y_mantener=None, operaciones=len(cerradas),
                   win_rate=float(np.mean([o['resultado'] > 0 for o in cerradas])) if cerradas else None, costos=float(sum(o['comision'] for o in ejecutadas)),
                   ordenes_rechazadas=sum(o['estado'] == 'rechazada' for o in filas), acciones_rechazadas=sum(not d['aprobada'] for d in decisiones),
                   latencia_media_ms=float(np.mean(latencias)) if latencias else None, patrimonio_final=None, **metricas_riesgo([]))
    if serie:
        valores = np.array([m['patrimonio'] for m in serie], dtype=float)
        picos = np.maximum.accumulate(np.concatenate([[capital], valores]))[1:]
        resumen |= dict(periodo=[serie[0]['fecha'], serie[-1]['fecha']], rendimiento=float(valores[-1] / capital - 1), patrimonio_final=float(valores[-1]), drawdown=float(((picos - valores) / picos).max()),
                        comprar_y_mantener=float(serie[-1]['precio'] / 100 * (1 - comision) / (1 + comision) - 1), **metricas_riesgo(np.r_[capital, valores]))
    return resumen


def metricas_operaciones(ordenes):
    """Operaciones cerradas: cada venta cierra la compra anterior del mismo activo.

    El resultado guardado se contrasta con cantidades, precios y comisiones de las dos órdenes; si difiere más de un centavo, es un descuadre.
    """
    abiertas, cerradas = {}, []
    for o in sorted((o for o in ordenes if o['estado'] == 'ejecutada'), key=lambda o: (o['creado'], o['id'])):
        if o['lado'] == 'comprar':
            abiertas[o['run']] = o
        elif o['lado'] == 'vender' and o['run'] in abiertas and o['resultado'] is not None:
            c = abiertas.pop(o['run'])
            calculado = o['cantidad'] * o['precio'] - o['comision'] - (c['cantidad'] * c['precio'] + c['comision'])
            horas = (datetime.fromisoformat(o['creado']) - datetime.fromisoformat(c['creado'])).total_seconds() / 3600
            cerradas.append((o['resultado'], horas, abs(calculado - o['resultado']) > 0.01))
    n = len(cerradas)
    ganado = sum(r for r, _, _ in cerradas if r > 0)
    perdido = -sum(r for r, _, _ in cerradas if r < 0)
    return dict(cerradas=n, abiertas=len(abiertas), acierto=sum(r > 0 for r, _, _ in cerradas) / n if n else None,
                factor_beneficio=ganado / perdido if perdido else None, resultado_neto=float(sum(r for r, _, _ in cerradas)),
                duracion_media_h=sum(h for _, h, _ in cerradas) / n if n else None, descuadres=sum(d for _, _, d in cerradas))


def exportar_registros(db, salida):
    """Copia a CSV las tablas de evidencia. Solo lee la base y nunca exporta la huella de la contraseña."""
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db), timeout=30)
    con.execute('PRAGMA query_only=ON')
    resumen = {}
    try:
        for tabla in TABLAS_EVIDENCIA:
            cursor = con.execute(f'SELECT * FROM {tabla}')  # nombres fijos de la lista de arriba
            filas = cursor.fetchall()
            with open(salida / f'{tabla}.csv', 'w', newline='', encoding='utf-8') as f:
                escritor = csv.writer(f)
                escritor.writerow([c[0] for c in cursor.description])
                escritor.writerows(filas)
            resumen[tabla] = len(filas)
        por_vela = con.execute("SELECT fecha_vela, COUNT(*), COALESCE(SUM(aprobada), 0), COALESCE(SUM(accion_final = 'comprar'), 0), AVG(latencia_ms) "
                               "FROM decisiones WHERE run LIKE 'live:%' GROUP BY fecha_vela ORDER BY fecha_vela").fetchall()
        ordenes = dict(con.execute("SELECT estado, COUNT(*) FROM ordenes WHERE run LIKE 'live:%' GROUP BY estado").fetchall())
        errores = con.execute('SELECT COUNT(*) FROM errores').fetchone()[0]
        columnas = ('id', 'run', 'creado', 'lado', 'estado', 'cantidad', 'precio', 'comision', 'resultado')
        operaciones = metricas_operaciones([dict(zip(columnas, f)) for f in con.execute(f"SELECT {', '.join(columnas)} FROM ordenes WHERE run LIKE 'live:%'")])
    finally:
        con.close()
    lineas = ['# Ciclos en vivo', '', 'Solo la conexión actual con MEXC: los replays no cuentan.', '',
              '| Vela | Ciclos | Aprobadas por riesgo | Compras autorizadas | Latencia media del LLM |', '| --- | --- | --- | --- | --- |']
    lineas += [f'| {vela} | {n} | {aprobadas} | {compras} | {f"{lat / 1000:.1f} s" if lat else "sin dato"} |' for vela, n, aprobadas, compras, lat in por_vela]
    lineas += ['', f'Ciclos en vivo: {sum(f[1] for f in por_vela)}.',
               f'Órdenes en vivo: ejecutadas: {ordenes.get("ejecutada", 0)}, expiradas: {ordenes.get("expirada", 0)}, rechazadas: {ordenes.get("rechazada", 0)}.',
               f'Errores registrados: {errores}.']
    m = operaciones
    acierto = 'sin dato' if m['acierto'] is None else f"{m['acierto'] * 100:.0f} %"
    factor = ('sin pérdidas' if m['cerradas'] else 'sin dato') if m['factor_beneficio'] is None else f"{m['factor_beneficio']:.2f}"
    duracion = 'sin dato' if m['duracion_media_h'] is None else f"{m['duracion_media_h']:.1f} h"
    lineas.append(f"Operaciones cerradas: {m['cerradas']}; acierto {acierto}; factor de beneficio {factor}; resultado neto {m['resultado_neto']:.2f} USDT; "
                  f"duración media {duracion}; abiertas: {m['abiertas']}; descuadres: {m['descuadres']}.")
    (salida / 'resumen_en_vivo.md').write_text('\n'.join(lineas) + '\n', encoding='utf-8')
    return resumen

