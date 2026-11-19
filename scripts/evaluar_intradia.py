"""Evalúa las tres candidatas intradía con las velas auditadas de data/intradia. Investigación: no toca el bot.

Uso: .venv/Scripts/python scripts/evaluar_intradia.py
Ventanas fijadas por fecha antes de medir: TR1, TR2 y TR3 de 20 días, VA de 20 días y un periodo final reservado que no
se evalúa. Escribe docs/RESULTADOS_INTRADIA.md y data/intradia/operaciones.csv.
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding='utf-8')

from research.estrategias_intradia import VERSION, criterios  # noqa: E402
from research.simular_intradia import PASO_MS, comprar_y_mantener, resumen, simular  # noqa: E402

DIA_MS = 86_400_000
CAPITAL = 10_000.0
VENTANAS = (('TR1', 0, 20), ('TR2', 20, 40), ('TR3', 40, 60), ('VA', 60, 80))  # días desde el inicio; lo posterior al día 80 queda reservado
ESCENARIOS = (('base', 1.0, 2.0), ('costos altos', 2.0, 10.0))  # multiplicador de la comisión real del par y deslizamiento en pb


def fecha(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime('%Y-%m-%d %H:%M')


def cargar():
    registro = json.loads((RAIZ / 'data' / 'intradia' / 'auditoria.json').read_text(encoding='utf-8'))
    datos = {}
    for simbolo, info in registro['activos'].items():
        ruta = RAIZ / info['archivo']
        if hashlib.sha256(ruta.read_bytes()).hexdigest() != info['sha256']:
            sys.exit(f'{ruta} no coincide con su huella: vuelve a descargar los datos antes de evaluar.')
        df = pd.read_csv(ruta)
        df['close_time'] = df.open_time + PASO_MS - 1  # MEXC marca el cierre en el inicio de la vela siguiente; el generador espera el último milisegundo
        datos[simbolo] = df
    return registro, datos


def main():
    registro, datos = cargar()
    inicio = min(int(df.open_time.iloc[0]) for df in datos.values())
    fin = max(int(df.open_time.iloc[-1]) for df in datos.values()) + PASO_MS
    comisiones = json.loads((RAIZ / 'config' / 'comisiones.json').read_text(encoding='utf-8'))
    filas, operaciones = [], []
    for simbolo, df in datos.items():
        s, tablas = criterios(df, ahora_ms=fin)
        for escenario, factor, desliz in ESCENARIOS:
            comision = comisiones.get(simbolo, 0.0008) * factor
            for ventana, d0, d1 in VENTANAS:
                dentro = s.open_time.between(inicio + d0 * DIA_MS, inicio + d1 * DIA_MS - 1)
                tramo = s[dentro].reset_index(drop=True)
                pasivo = comprar_y_mantener(tramo, comision, desliz)
                for nombre, tabla in tablas.items():
                    ops, curva = simular(tramo, tabla.entrada_siguiente[dentro].to_numpy(), comision=comision, deslizamiento_bps=desliz, capital=CAPITAL)
                    r = resumen(ops, curva, CAPITAL)
                    filas.append(dict(escenario=escenario, ventana=ventana, estrategia=nombre, simbolo=simbolo, senales=int(tabla.senal_cierre[dentro].sum()),
                                      ops=ops, pasivo=pasivo['rendimiento'], **{k: v for k, v in r.items() if k != 'salidas'}, **r['salidas']))
                    operaciones += [dict(escenario=escenario, ventana=ventana, estrategia=nombre, simbolo=simbolo, entrada=fecha(o['entrada']), salida=fecha(o['salida']),
                                         **{k: o[k] for k in ('precio_entrada', 'precio_salida', 'cantidad', 'resultado', 'motivo', 'velas')}) for o in ops]
    pd.DataFrame(operaciones).to_csv(RAIZ / 'data' / 'intradia' / 'operaciones.csv', index=False)
    escribir_informe(registro, inicio, fin, filas)
    print('Informe en docs/RESULTADOS_INTRADIA.md;', len(operaciones), 'operaciones en data/intradia/operaciones.csv')


def agregado(grupo):
    """Las tres monedas juntas: cada una con su propio capital de 10,000, así que el capital conjunto es 30,000."""
    ops = [o for f in grupo for o in f['ops']]
    ganado = sum(o['resultado'] for o in ops if o['resultado'] > 0)
    perdido = -sum(o['resultado'] for o in ops if o['resultado'] < 0)
    n = len(ops)
    return dict(senales=sum(f['senales'] for f in grupo), operaciones=n, acierto=sum(o['resultado'] > 0 for o in ops) / n if n else None,
                factor=ganado / perdido if perdido else None, neto=sum(f['resultado_neto'] for f in grupo), rendimiento=sum(f['resultado_neto'] for f in grupo) / (CAPITAL * len(grupo)),
                drawdown=max(f['drawdown'] for f in grupo), duracion=sum(o['velas'] for o in ops) / n * 0.25 if n else None,
                exposicion=sum(f['exposicion'] for f in grupo) / len(grupo), pasivo=sum(f['pasivo'] for f in grupo) / len(grupo),
                salidas='/'.join(str(sum(f[m] for f in grupo)) for m in ('objetivo', 'stop', 'tiempo', 'fin')))


def celda(v, formato):
    return 'sin dato' if v is None else formato.format(v)


def escribir_informe(registro, inicio, fin, filas):
    lineas = [
        '# Resultados intradía de 15 minutos', '',
        f'Generado el {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")} UTC por `scripts/evaluar_intradia.py` con `{VERSION}`. **Resultados simulados**, no validados; '
        'ninguna candidata se promueve al bot.', '',
        '## Datos', '',
        f'{registro["fuente"]}. Descargados el {registro["descargado"][:16]}. Periodo de {fecha(inicio)} a {fecha(fin)} UTC.', '',
        '| Activo | Velas | Duplicados | Huecos | OHLC incoherente | Volumen cero | Huella SHA-256 |', '| --- | --- | --- | --- | --- | --- | --- |',
    ]
    for simbolo, info in registro['activos'].items():
        a = info['auditoria_cruda']
        lineas.append(f'| {simbolo} | {info["velas_guardadas"]} | {a["duplicados"]} | {a["huecos"]} | {a["ohlc_incoherente"]} | {a["volumen_cero"]} | `{info["sha256"][:16]}…` |')
    lineas += ['', '## Supuestos fijados antes de medir', '',
               '- **Señal y entrada:** la señal se conoce al cierre de una vela y solo permite comprar en la apertura de la siguiente.',
               '- **Salidas:** stop a 2 ATR14 y objetivo a 3 ATR14 de la última vela cerrada, máximo 16 velas (4 horas). Si una vela toca ambos, cuenta primero el stop; '
               'un salto bajo el stop sale a la apertura disponible; la salida por tiempo usa la apertura siguiente.',
               '- **Tamaño:** riesgo de 0.25 % del capital hasta el stop, con exposición máxima de 20 %. Capital de 10,000 por activo y una posición a la vez.',
               '- **Costos:** comisión real de MEXC del par por lado (`config/comisiones.json`: 0.05 % en BTC, ETH y SOL) más 2 pb de deslizamiento en lo que se ejecuta a mercado. '
               'Escenario de costos altos: el doble de comisión y 10 pb. El objetivo sale a su precio, pero paga comisión: no se supone llenado maker gratis.',
               '- **Ventanas:** ' + ', '.join(f'{v} de {fecha(inicio + d0 * DIA_MS)[:10]} a {fecha(inicio + d1 * DIA_MS - 1)[:10]}' for v, d0, d1 in VENTANAS)
               + f'. Del {fecha(inicio + 80 * DIA_MS)[:10]} en adelante queda reservado y no se evalúa.',
               '- **Indicadores:** se calculan con toda la historia anterior a cada vela (causales). Sin libro histórico: no se afirma una simulación fiel de la profundidad.',
               '- **Cierre de vela:** MEXC marca el cierre en el inicio de la vela siguiente; el generador espera el último milisegundo, así que se resta 1 ms.', '']
    for escenario, _, _ in ESCENARIOS:
        lineas += [f'## Escenario: {escenario}', '',
                   'Tres monedas juntas, cada una con 10,000. Salidas en orden: objetivo / stop / tiempo / fin de ventana.', '',
                   '| Estrategia | Ventana | Señales | Operaciones | Acierto | Factor de beneficio | Resultado neto | Rendimiento | Caída máx. | Duración media | Exposición | Salidas | Comprar y mantener |',
                   '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
        for estrategia in ('tendencia', 'recuperacion', 'ruptura'):
            for ventana, _, _ in VENTANAS:
                g = agregado([f for f in filas if f['escenario'] == escenario and f['estrategia'] == estrategia and f['ventana'] == ventana])
                lineas.append(f'| {estrategia} | {ventana} | {g["senales"]} | {g["operaciones"]} | {celda(g["acierto"], "{:.0%}")} | {celda(g["factor"], "{:.2f}")} | '
                              f'{g["neto"]:,.2f} USDT | {g["rendimiento"]:+.2%} | {g["drawdown"]:.2%} | {celda(g["duracion"], "{:.1f} h")} | {g["exposicion"]:.1%} | '
                              f'{g["salidas"]} | {g["pasivo"]:+.2%} |')
        lineas.append('')
    informe = RAIZ / 'docs' / 'RESULTADOS_INTRADIA.md'
    previa = informe.read_text(encoding='utf-8').split('## Lectura', 1)[1] if informe.exists() and '## Lectura' in informe.read_text(encoding='utf-8') else ''
    escrita = previa if previa.strip() and 'Pendiente de escribir a mano' not in previa else '\n\nPendiente de escribir a mano después de revisar las tablas: el script no saca conclusiones por su cuenta.\n'
    informe.write_text('\n'.join(lineas) + '## Lectura' + escrita, encoding='utf-8')  # la lectura escrita a mano se conserva al regenerar las tablas


if __name__ == '__main__':
    main()
