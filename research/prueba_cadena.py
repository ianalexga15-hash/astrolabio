"""Prueba de integración: cadena completa de compra y venta con precios reales de MEXC y umbral forzado.

Solo sirve para ver funcionar el camino en vivo: no es una señal real. Usa una base temporal y no toca models/ ni data/bot.sqlite3.

    python research/prueba_cadena.py 60
"""
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding='utf-8')

from bot import llm, mexc, model  # noqa: E402
from bot.cartera import Cartera  # noqa: E402
from bot.config import cargar_limites, cargar_universo  # noqa: E402
from bot.store import Store  # noqa: E402

SEGUNDOS = int(sys.argv[1]) if len(sys.argv) > 1 else 60

modelos_dir = RAIZ / 'models'
principal = model.cargar(modelos_dir / (modelos_dir / 'ACTIVO.txt').read_text(encoding='utf-8').strip())
conjunto = model.cargar(modelos_dir / (modelos_dir / 'CARTERA.txt').read_text(encoding='utf-8').strip())
principal.umbral = conjunto.umbral = -1.0  # en memoria y solo aquí: todo pronóstico cuenta como señal

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as carpeta:
    store = Store(Path(carpeta) / 'prueba.sqlite3')
    limites = cargar_limites(RAIZ, store)
    simbolos = cargar_universo(RAIZ, limites.simbolo)
    modelos = {s: principal if s == limites.simbolo else conjunto for s in simbolos}
    c = Cartera(store=store, mercado=mexc.Mexc(), modelos=modelos, proponente=llm.ProponenteRegla(), limites=limites)
    c.iniciar()
    t0 = time.time()
    r = c.ciclo()
    print(f'ciclo {time.time() - t0:.0f}s', {k: r[k] for k in ('resultado', 'procesadas', 'fallos', 'sin_velas_nuevas', 'inactivos')})
    print('fallos:', {s: d.get('error') for s, d in r['detalle'].items() if d['resultado'] == 'fallo'})
    print('armadas antes del primer barrido:', sum(1 for a in c.agentes.values() if a.cuenta.armada))

    t0 = time.time()
    n = 0
    while time.time() - t0 < SEGUNDOS:
        inicio = time.time()
        e = c.barrer()
        n += 1
        if n in (1, 2, 5) or n % 30 == 0:
            rs = c.resumen()
            print(f'barrido {n}: posiciones {rs["posiciones"]}, armadas {rs["armadas"]}, patrimonio {rs["patrimonio"]:.2f}, exposición {rs["exposicion"]:.1%}, latencia {e.get("latencia_ms", 0):.2f} ms, error {e.get("error")}')
        time.sleep(max(0, 1 - (time.time() - inicio)))

    print('\nPosiciones:')
    for s, a in c.agentes.items():
        cu = a.cuenta
        if cu.cantidad > 0:
            fila = c.reflejo.radar[s]
            nocional = cu.cantidad * cu.precio_medio
            print(f'  {s:11} cant {cu.cantidad:<16g} entrada {cu.precio_medio:<12g} monto {nocional:8.2f} ({nocional / a.limites.capital_inicial:5.1%} del cupo) stop {cu.stop:<12g} objetivo {cu.objetivo:<12g} spread {fila["spread_bps"]:.1f} pb abierto {fila["resultado_abierto"]:+.3%}')
            assert cu.stop < cu.precio_medio < cu.objetivo, s
            assert nocional <= a.limites.exposicion_max * a.limites.capital_inicial + 1e-6, s
            assert cu.efectivo >= 0, s
    print('\nSin comprar y por qué:')
    for s, a in c.agentes.items():
        if a.cuenta.cantidad == 0:
            fila = c.reflejo.radar[s]
            faltan = [f'{x["nombre"]}: {x["detalle"]}' for x in fila['condiciones'] if not x['cumple']]
            ords = [o for o in store.ordenes(a.run_id) if o['estado'] == 'rechazada']
            print(f'  {s:11} {fila["estado"]:12} {faltan or [o["motivo"] for o in ords] or a.motivo}')

    ordenes = [o for a in c.agentes.values() for o in store.ordenes(a.run_id)]
    print('\nÓrdenes ejecutadas:', sum(o['estado'] == 'ejecutada' for o in ordenes), 'rechazadas:', sum(o['estado'] == 'rechazada' for o in ordenes))
    antes = c.resumen()
    print('Antes de cerrar:', {k: round(antes[k], 4) for k in ('patrimonio', 'exposicion', 'efectivo', 'costos')}, 'posiciones', antes['posiciones'])
    if antes['posiciones']:
        print('Cerradas:', c.cerrar_posicion())
    despues = c.resumen()
    print('Después de cerrar:', {k: round(despues[k], 4) for k in ('patrimonio', 'exposicion', 'efectivo', 'costos')}, 'posiciones', despues['posiciones'])
    print('Errores registrados:', store.errores()[:5])
    assert despues['posiciones'] == 0
    assert abs(despues['patrimonio'] - despues['efectivo']) < 1e-6
    for a in c.agentes.values():  # identidad contable: el efectivo final es el cupo más los resultados realizados
        resultado = sum(o['resultado'] or 0 for o in store.ordenes(a.run_id) if o['estado'] == 'ejecutada')
        assert abs(a.cuenta.efectivo - a.limites.capital_inicial - resultado) < 1e-6, a.limites.simbolo
    print('Contabilidad correcta en los', len(c.agentes), 'activos.')
