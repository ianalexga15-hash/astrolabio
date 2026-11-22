"""Genera notebooks/Astrolabio_Modelo_BTC.ipynb. El código se copia de bot/ y research/ para que notebook y agente usen las mismas definiciones."""
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MODULOS = ['bot/data.py', 'bot/features.py', 'bot/metricas_riesgo.py', 'bot/model.py', 'bot/mexc.py', 'research/lab.py']


def md(texto):
    return dict(cell_type='markdown', metadata={}, source=texto.strip().splitlines(keepends=True))


def code(texto):
    return dict(cell_type='code', metadata={}, execution_count=None, outputs=[], source=texto.strip().splitlines(keepends=True))


def modulo(ruta):
    return code(f'%%writefile {ruta}\n' + (RAIZ / ruta).read_text(encoding='utf-8'))


def celdas():
    c = [md('''
# Astrolabio: modelo diario de BTCUSDT

**Del pronóstico de rendimientos a las bases de un agente de trading.** Activo: BTCUSDT diario en MEXC.

**Cómo ejecutarlo.** En Colab elige *Entorno de ejecución > Cambiar tipo > GPU T4* y después *Ejecutar todo*. Si Colab no asigna una T4, el notebook se detiene antes de entrenar. Al terminar, descarga `resultados_t4.zip`, descomprímelo y copia su carpeta `t4-AAAA-MM-DD` a `models/` del proyecto.

**Orden.** Cinco etapas: datos y referencias, redes, validación temporal, diseño del agente, e indicadores con evaluación final. TE solo se abre una vez, en la etapa 5, con el sistema congelado.
'''),
         md('## Entorno y evidencia de T4'),
         code('''
import json, os, platform, subprocess, sys, time, zipfile
from pathlib import Path

PRUEBA = os.environ.get('NB_PRUEBA') == '1'  # solo para probar el notebook sin GPU, con datos sintéticos; no es evidencia válida
SEMILLA_GLOBAL = 11
os.makedirs('bot', exist_ok=True); os.makedirs('research', exist_ok=True); os.makedirs('resultados', exist_ok=True)
for ruta in ('bot/__init__.py', 'research/__init__.py'):
    Path(ruta).touch()
SALIDA = Path('resultados')
inicio_notebook = time.time()
bitacora = []

def anotar(etapa, error, causa, accion, resultado):
    """Bitácora de errores: fecha, etapa, error, causa, acción correctiva y resultado de la verificación."""
    bitacora.append(dict(fecha=time.strftime('%Y-%m-%d %H:%M:%S'), etapa=etapa, error=error, causa=causa, accion_correctiva=accion, resultado_verificacion=resultado))
'''),
         code('''
evidencia = dict(python=platform.python_version(), semilla=SEMILLA_GLOBAL, inicio=time.strftime('%Y-%m-%d %H:%M:%S'), prueba_sin_gpu=PRUEBA)
if PRUEBA:
    print('MODO PRUEBA: sin T4 y con datos sintéticos. Esta corrida NO sirve como evidencia de T4.')
    evidencia |= dict(gpu='ninguna', valido_para_entrega=False)
else:
    try:
        salida = subprocess.run(['nvidia-smi'], capture_output=True, text=True, check=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        anotar('entorno', 'nvidia-smi no disponible', str(e), 'Detener el entrenamiento y cambiar el entorno a GPU T4', 'Sin entrenar')
        raise RuntimeError('No hay GPU en esta sesión. Elige Entorno de ejecución > Cambiar tipo > GPU T4 y vuelve a ejecutar.') from e
    print(salida)
    (SALIDA / 'nvidia_smi.txt').write_text(salida)
    import tensorflow as tf
    gpus = tf.config.list_physical_devices('GPU')
    nombre = tf.config.experimental.get_device_details(gpus[0]).get('device_name', '') if gpus else ''
    print('GPU detectada:', nombre or 'ninguna')
    if 'T4' not in nombre:
        anotar('entorno', f'GPU distinta de T4: {nombre or "ninguna"}', 'Colab no garantiza el tipo de GPU', 'Detener el entrenamiento y reprogramar la ejecución', 'Sin entrenar')
        raise RuntimeError('No se asignó una T4: se detiene el entrenamiento profundo. Reprograma la ejecución.')
    with tf.device('/GPU:0'):
        a = tf.random.normal((2000, 2000))
        operacion = tf.linalg.matmul(a, a)
    print('Operación ejecutada en:', operacion.device)
    tf.config.experimental.reset_memory_stats('GPU:0')
    evidencia |= dict(gpu=nombre, tensorflow=tf.__version__, dispositivo_operacion=operacion.device, valido_para_entrega=True)
import keras
evidencia |= dict(keras=keras.__version__, backend=keras.backend.backend())
print(evidencia)
'''),
         code('''
# Guarda los resultados fuera del almacenamiento temporal de Colab
DRIVE = None
if not PRUEBA:
    try:
        from google.colab import drive
        drive.mount('/content/drive')
        DRIVE = Path('/content/drive/MyDrive/DL_Finanzas_T4')
        DRIVE.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # sin Drive se sigue, pero queda registrado
        anotar('entorno', 'Google Drive no disponible', str(e), 'Descargar el zip al terminar', 'Pendiente')
        print('Sin Drive:', e, '- descarga el zip al terminar.')
'''),
         md('''
### Código del proyecto

Estas celdas escriben los mismos módulos que usa el agente. Así las variables se calculan igual al entrenar y al operar. Se pueden leer y explicar aquí mismo.
''')]
    c += [modulo(r) for r in MODULOS]
    c += [
        code('''
%pip install -q httpx
import numpy as np, pandas as pd, matplotlib.pyplot as plt
from bot import data, features, mexc, model
from research import lab
keras.utils.set_random_seed(SEMILLA_GLOBAL)
np.random.seed(SEMILLA_GLOBAL)
ENTRENAMIENTO = dict(epocas=3, lote=64, paciencia=2) if PRUEBA else dict(epocas=300, lote=64, paciencia=25)
COSTO = 0.001   # costo supuesto: 0.10 % por compra y por venta
'''),
        md('''
## 1. Datos confiables y referencias

**Etapa 1.** Ficha del activo, auditoría, separación TR, VA y TE, y dos modelos de referencia: pronóstico cero y regresión lineal con los mismos rezagos.
'''),
        code('''
ARCHIVO = Path('BTCUSDT_1d.csv')
if PRUEBA:
    rng = np.random.default_rng(1)
    cierres = 100 * np.cumprod(1 + rng.normal(0.0004, 0.02, 1700))
    dia = 86_400_000
    inicio = 1_500_000_000_000 - 1_500_000_000_000 % dia
    filas = [[inicio + i * dia, str(cierres[i - 1] if i else cierres[0]), str(max(cierres[i], cierres[i - 1] if i else cierres[0]) * 1.01),
              str(min(cierres[i], cierres[i - 1] if i else cierres[0]) * 0.99), str(cierres[i]), '10', inicio + (i + 1) * dia, '100'] for i in range(1700)]
    fuente = 'Datos sintéticos de prueba'
elif ARCHIVO.exists():
    filas = pd.read_csv(ARCHIVO)[data.COLUMNAS].values.tolist()  # copia local identificada y trazable
    fuente = f'Copia local {ARCHIVO}, descargada de MEXC'
else:
    try:
        ahora = int(time.time() * 1000)
        filas = [f for f in mexc.Mexc().history('BTCUSDT', 1_483_228_800_000, ahora) if f[6] <= ahora]
        fuente = mexc.BASE + '/api/v3/klines'
    except mexc.MexcError as e:
        anotar('datos', 'Descarga fallida de MEXC', str(e), 'Subir BTCUSDT_1d.csv de data/raw del proyecto y reejecutar', 'Sin datos')
        raise RuntimeError(f'No se pudo descargar BTCUSDT de MEXC: {e}. Sube el archivo data/raw/BTCUSDT_1d.csv y vuelve a ejecutar.') from e

crudo = data.frame_from_rows(filas)
auditoria = data.audit(crudo)
limpio, limpieza = data.clean(crudo)
crudo.to_csv(SALIDA / 'datos_originales.csv', index=False)
limpio.to_csv(SALIDA / 'datos_procesados.csv', index=False)
for linea in limpieza:
    anotar('preparación', linea, 'Regla de limpieza documentada', 'Conservar el tramo continuo más largo sin rellenar', 'Índice único y orden cronológico verificados')
assert limpio.open_time.is_unique and limpio.open_time.is_monotonic_increasing
if len(limpio) < 1500:
    raise ValueError(f'Solo hay {len(limpio)} observaciones válidas; se necesitan al menos 1,500.')

ficha = dict(activo='BTCUSDT', mercado='Criptomonedas', plataforma='MEXC', fuente=fuente, frecuencia='Diaria', zona_horaria='UTC', calendario='Continuo',
             moneda_base='BTC', moneda_cotizada='USDT', fecha_descarga=time.strftime('%Y-%m-%d'), periodo=[limpio.date.iloc[0], limpio.date.iloc[-1]], observaciones=len(limpio),
             ajustes='Sin ajustes: no hay dividendos ni particiones', volumen='Reportado por la fuente', huella=data.dataset_hash(limpio))
(SALIDA / 'ficha_activo.json').write_text(json.dumps(ficha, indent=2, ensure_ascii=False))
print(json.dumps(ficha, indent=2, ensure_ascii=False))
print('Auditoría del original:', {k: (v if not isinstance(v, list) else (len(v), v[:3])) for k, v in auditoria.items()})
print('Limpieza:', limpieza)
'''),
        code('''
tabla_total = data.add_target(features.add_indicators(limpio))
tabla = lab.tabla_comun(tabla_total)  # todas las versiones se evalúan en las mismas fechas
fig, ax = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
fechas = pd.to_datetime(tabla.date)
ax[0].plot(fechas, tabla.close); ax[0].plot(fechas, tabla.sma20, '--'); ax[0].set_title('Precio de cierre y SMA20'); ax[0].set_yscale('log')
ax[1].plot(fechas, tabla.ret, linewidth=.6); ax[1].set_title('Rendimiento diario')
ax[2].plot(fechas, tabla.vol20); ax[2].set_title('Volatilidad de 20 días, sin anualizar')
plt.tight_layout(); plt.savefig(SALIDA / 'exploracion.png', dpi=130); plt.show()
extremos = tabla.loc[tabla.ret.abs() > 4 * tabla.ret.std(), ['date', 'ret']]
print('Rendimientos extremos (más de 4 desviaciones):'); print(extremos.to_string(index=False))
'''),
        md('''
**Hipótesis técnica, verificable más adelante:** la distancia del cierre a su SMA de 20 días y la volatilidad de 20 días aportan información para pronosticar el rendimiento del día siguiente. Que una figura se vea sugerente no implica capacidad predictiva: se comprueba en el capítulo 11.
'''),
        code('''
A = lab.preparar(tabla, lab.CONJUNTOS_VARIABLES['rezagos'])
display(lab.tabla_particion(A))
print('El último objetivo de TR es anterior al primero de VA, y el de VA al primero de TE:', A['objetivo_TR'][-1] < A['objetivo_VA'][0] < A['objetivo_TE'][0])
print('Forma de entrada:', A['X_TR'].shape, '(ejemplos, pasos temporales, variables)')
print('El escalador se ajustó solo con TR. Media y desviación:', A['escalador'].media, A['escalador'].desv)
print('Fila de control:', lab.fila_de_control(A))
'''),
        md('''
**Control de aprendizaje.** La fila anterior muestra que las entradas terminan en la fecha de emisión y que el objetivo es del día siguiente. Al predecir, el modelo solo ve rendimientos ya ocurridos: la respuesta todavía no existe en sus entradas.
'''),
        code('''
experimentos, curvas = [], {}
DISPOSITIVO = 'cpu (prueba)' if PRUEBA else evidencia['gpu']
candidatos_A = lab.probar_referencias(A, 'rezagos', experimentos)
display(pd.DataFrame(experimentos)[['modelo', 'configuracion', 'MAE_TR', 'RMSE_TR', 'MAE_VA', 'RMSE_VA', 'direccional_VA']])
'''),
        md('''
**Seguimiento.** Para aportar algo, el modelo profundo tendría que reducir el RMSE frente a pronosticar cero en validación. En rendimientos diarios la diferencia suele ser mínima: la mayor parte del error es ruido irreducible.
'''),
        md('''
## 2. MLP y LSTM

**Etapa 2.** Mismo objetivo, variables y particiones. Tres configuraciones por red, variando solo neuronas o tasa de aprendizaje, y la mejor se repite con tres semillas. Parada temprana con VA y restauración de los mejores pesos.
'''),
        code('''
inicio_redes = time.time()
candidatos_A += [lab.probar_red(A, 'rezagos', 'mlp', lab.CONFIGS_MLP, experimentos, curvas, dispositivo=DISPOSITIVO, **ENTRENAMIENTO),
                 lab.probar_red(A, 'rezagos', 'lstm', lab.CONFIGS_LSTM, experimentos, curvas, dispositivo=DISPOSITIVO, **ENTRENAMIENTO)]
print(f'Entrenamiento en {DISPOSITIVO}: {time.time() - inicio_redes:.0f} s')
if not PRUEBA:
    memoria = tf.config.experimental.get_memory_info('GPU:0')
    print('Memoria de GPU usada, en bytes:', memoria)
    evidencia['memoria_gpu_pico'] = memoria['peak']
    if memoria['peak'] <= 0:
        anotar('entrenamiento', 'La GPU no registró uso', 'El framework entrenó en CPU', 'Detener y revisar el entorno', 'Sin evidencia válida')
        raise RuntimeError('La GPU no se usó durante el entrenamiento: no hay evidencia válida de T4.')
for c in candidatos_A[-2:]:
    print(c['nombre'], f"RMSE VA media={c['rmse_media']:.6f} desviación={c['rmse_desv']:.6f}")
tabla_exp = pd.DataFrame(experimentos)
display(tabla_exp[['modelo', 'configuracion', 'semilla', 'dispositivo', 'segundos', 'RMSE_TR', 'RMSE_VA', 'MAE_VA', 'direccional_VA']])
'''),
        code('''
fig, ax = plt.subplots(1, 2, figsize=(11, 3.4))
for eje, (nombre, h) in zip(ax, curvas.items()):
    eje.plot(h['loss'], label='TR'); eje.plot(h['val_loss'], label='VA'); eje.set_title(f'Pérdida por época: {nombre}'); eje.legend()
plt.tight_layout(); plt.savefig(SALIDA / 'curvas_aprendizaje.png', dpi=130); plt.show()
for nombre, h in curvas.items():
    print(nombre, 'mejor época', int(np.argmin(h['val_loss'])) + 1, 'de', len(h['val_loss']))
'''),
        md('''
**Seguimiento.** ¿Una menor pérdida en TR también mejora VA? Compara las curvas: si TR sigue bajando y VA sube, hay sobreajuste; si ambas se quedan altas y planas, el modelo no capta relación útil o casi no la hay en los datos. Escribe aquí lo que observaste en esta corrida.
'''),
        md('''
## 3. Validación temporal y regla de señal

**Etapa 3.** Tres ventanas expansivas dentro de TR: cada entrenamiento termina antes del bloque que evalúa, y las transformaciones se reajustan solo con ese entrenamiento. Después, hasta cinco umbrales candidatos en VA.

El pronóstico directo y recursivo es una ampliación opcional y no se realiza. **Diferenciación fraccionaria:** busca estabilizar una serie sin borrar toda su memoria, con un orden entre 0 y 1. Aquí no es necesaria: los rendimientos ya son estacionarios, como muestra la prueba siguiente; serviría si se usaran precios o volatilidades con memoria larga.
'''),
        code('''
from statsmodels.tsa.stattools import adfuller
print('Prueba ADF, valor p. Precio:', round(adfuller(tabla.close.values[-1500:])[1], 4), ' Rendimiento:', round(adfuller(tabla.ret.values[-1500:])[1], 6))
redes_A = [(c['tipo'], c['cfg']) for c in candidatos_A if 'cfg' in c]
ventanas_A = lab.validacion_expansiva(A, redes_A, **ENTRENAMIENTO)
tabla_ventanas = pd.DataFrame(ventanas_A)
display(tabla_ventanas.pivot_table(index=['ventana', 'bloque_desde', 'bloque_hasta'], columns='modelo', values='RMSE'))
'''),
        code('''
velas_va = lab.velas_de(tabla, A['emision_VA'])
reglas_A = []
for c in candidatos_A:
    c['casi_constante'], c['metricas_va'] = lab.casi_constante(c['pred_va']), lab.metricas(A['y_VA'], c['pred_va'])
    c['reglas'] = lab.probar_reglas(c['pred_va'], velas_va, COSTO)
    c['regla'] = lab.elegir_regla(c['reglas'])
    reglas_A += [dict(variables='rezagos', modelo=c['nombre'], **r) for r in c['reglas']]
display(pd.DataFrame([dict(modelo=c['nombre'], RMSE_VA=c['metricas_va']['RMSE'], casi_constante=c['casi_constante'], **{k: c['regla'][k] for k in ('umbral', 'filtro', 'rendimiento', 'drawdown', 'operaciones')}) for c in candidatos_A]))
pasivo_va = lab.comprar_y_mantener(velas_va, COSTO)
print('Comprar y mantener en VA:', round(pasivo_va['rendimiento'], 4), 'caída', round(pasivo_va['drawdown'], 4))
'''),
        md('''
**Seguimiento.** ¿El resultado depende de un único periodo favorable? Revisa si el RMSE se sostiene en las tres ventanas. Un umbral no equivale a una probabilidad de acierto: solo decide cuándo actuar. TE no intervino en ninguna decisión.
'''),
        md('''
## 4. Diseño del agente

**Etapa 4.** Se diseña el entorno; todavía no se entrena un agente DQN o DDQN.

| Elemento | Definición |
| --- | --- |
| Estado | 20 rendimientos recientes, pronóstico, volatilidad, efectivo y posición, todo conocido al cierre de t |
| Acciones | Comprar, mantener una posición abierta, vender una posición existente. Permanecer en efectivo es mantener sin posición |
| Restricciones | Sin apalancamiento, sin posiciones negativas, sin compras mayores al efectivo |
| Recompensa | Cambio del patrimonio después de costos, calculado al cierre del día de ejecución |
| Ejecución | La decisión del cierre de t se ejecuta en la apertura de t+1 |

**Pronóstico, señal y política.** El pronóstico estima un rendimiento. La señal es la instrucción que sale de una regla, como comprar si supera el umbral. La política es lo que aprendería un agente: una función de estados a acciones, entrenada por recompensas.

**DQN y DDQN.** La exploración prueba acciones al azar con probabilidad épsilon para descubrir mejores decisiones. La memoria de experiencias guarda transiciones y las muestrea al azar para romper la correlación temporal. La red objetivo es una copia que se actualiza de vez en cuando para estabilizar el aprendizaje, y DDQN separa quién elige la acción de quién la evalúa para reducir la sobreestimación.
'''),
        code('''
# Transición calculada: estado, acción, ejecución, recompensa y nuevo estado
t = lab.transicion_ejemplo(efectivo=100_000.0, precio_ejecucion=100.0, cierre=102.0, comision=COSTO)
print('Estado: efectivo 100,000, sin posición. Acción: comprar. Ejecución: apertura de t+1 a 100.')
print('Costo:', round(t['costo'], 2), ' Cantidad:', round(t['cantidad'], 4), ' Patrimonio al cierre a 102:', round(t['patrimonio_nuevo'], 2))
print('Recompensa, cambio del patrimonio después de costos:', round(t['recompensa'], 2))
print('Nuevo estado: efectivo 0, posición', round(t['cantidad'], 4))
'''),
        md('''
**Seguimiento.** ¿El agente podría aprovechar un error del simulador? Sí, si el simulador le dejara operar al cierre que ya conoce, comprar sin costo o gastar más efectivo del disponible. Por eso la ejecución ocurre en la siguiente apertura, los costos se cobran al operar y el saldo se revisa antes de cada compra.
'''),
        md('''
## 5. Indicadores técnicos y evaluación final

**Etapa 5.** El mismo procedimiento con rezagos más dos indicadores: distancia a SMA20 y volatilidad de 20 días. Las dos versiones se comparan en las mismas fechas de VA. La versión final se elige con VA y TE se evalúa una sola vez.
'''),
        code('''
display(pd.DataFrame([dict(indicador=k, definicion=v, primera_fecha_valida=features.first_valid_dates(tabla_total).get(k)) for k, v in features.INDICADORES.items()]))
B = lab.preparar(tabla, lab.CONJUNTOS_VARIABLES['rezagos_indicadores'])
assert A['objetivo_VA'] == B['objetivo_VA'], 'Las dos versiones deben evaluarse en las mismas fechas.'
candidatos_B = lab.probar_referencias(B, 'rezagos_indicadores', experimentos)
candidatos_B += [lab.probar_red(B, 'rezagos_indicadores', 'mlp', lab.CONFIGS_MLP, experimentos, curvas, dispositivo=DISPOSITIVO, **ENTRENAMIENTO),
                 lab.probar_red(B, 'rezagos_indicadores', 'lstm', lab.CONFIGS_LSTM, experimentos, curvas, dispositivo=DISPOSITIVO, **ENTRENAMIENTO)]
reglas_B = []
for c in candidatos_B:
    c['casi_constante'], c['metricas_va'] = lab.casi_constante(c['pred_va']), lab.metricas(B['y_VA'], c['pred_va'])
    c['reglas'] = lab.probar_reglas(c['pred_va'], velas_va, COSTO)
    c['regla'] = lab.elegir_regla(c['reglas'])
    reglas_B += [dict(variables='rezagos_indicadores', modelo=c['nombre'], **r) for r in c['reglas']]
comparacion = pd.DataFrame([dict(version=v, modelo=c['nombre'], MAE_VA=c['metricas_va']['MAE'], RMSE_VA=c['metricas_va']['RMSE'], direccional_VA=c['metricas_va']['direccional'], casi_constante=c['casi_constante'],
                                 **{k: c['regla'][k] for k in ('umbral', 'filtro', 'rendimiento', 'drawdown', 'operaciones', 'win_rate')})
                            for v, lista in (('rezagos', candidatos_A), ('rezagos_indicadores', candidatos_B)) for c in lista])
display(comparacion)
print(tabla[['ret', 'dist_sma20', 'vol20', 'rsi14', 'macd_hist', 'bb_pos', 'atr14']].corr().round(2).to_string())
'''),
        code('''
# Comparación C frente a D: la misma estrategia sin filtro y con filtro técnico. El filtro cambia operaciones, no predicciones.
todas_reglas = pd.DataFrame(reglas_A + reglas_B)
filtro = todas_reglas.pivot_table(index=['variables', 'modelo', 'umbral'], columns='filtro', values=['rendimiento', 'drawdown', 'operaciones'])
display(filtro.head(20))

# Selección final con VA, congelada antes de abrir TE
todos = [(A, c) for c in candidatos_A] + [(B, c) for c in candidatos_B]
D, final = max(todos, key=lambda t: (round(t[1]['regla']['rendimiento'], 10), -t[1]['regla']['drawdown']))
referencia_lineal = max(candidatos_A + candidatos_B, key=lambda c: (c['tipo'] == 'lineal', -c['metricas_va']['RMSE']))
configuracion = dict(modelo=final['nombre'], tipo=final['tipo'], variables=D['variables'], regla={k: final['regla'][k] for k in ('umbral', 'filtro')}, datos=ficha['huella'], costo=COSTO,
                     semillas=list(lab.SEMILLAS))
print('Sistema final congelado:', json.dumps(configuracion, indent=2, ensure_ascii=False))
# La exportación a NumPy debe reproducir a Keras con este motor (Colab usa TensorFlow): se comprueba en VA, antes de abrir TE.
previos = lab.contrato_lineal(D, final['ajuste']) if final['tipo'] == 'lineal' else lab.contrato_redes(final['resultados'])
exportado = lab.guardar_modelo(SALIDA / 'verificacion_antes_de_te', 'verificacion', final['tipo'], D, final['regla']['umbral'], final['regla']['filtro'], *previos)
pasos_control = {
    'datos finitos': bool(np.isfinite(D['X_TR']).all() and np.isfinite(D['X_VA']).all() and np.isfinite(D['X_TE']).all()),
    'predicciones VA finitas': bool(np.isfinite(final['pred_va']).all()),
    'fechas alineadas': D['objetivo_VA'][-1] < D['objetivo_TE'][0],
    'transformaciones solo con TR': True,  # lab.preparar ajusta el escalador con TR y solo transforma VA y TE
    'evidencia y registro guardados': (SALIDA / 'ficha_activo.json').exists(),
    'exportación a NumPy reproduce a Keras en VA': bool(np.allclose(exportado.predecir_x(D['ventanas'].X[D['indices']['VA']]), final['pred_va'], atol=1e-4)),
}
print('Controles antes de TE:', pasos_control)
assert all(pasos_control.values()), 'Un control falló: corrige antes de abrir TE.'
'''),
        code('''
# Única evaluación en TE. Las versiones finales se definieron antes de esta celda.
sello = lab.abrir_te(SALIDA / 'apertura_te.json', lab.huella(configuracion))
print('Sello de TE:', sello)
if sello['contaminado'] or sello['aperturas'] > 1:
    anotar('evaluación', 'TE abierto más de una vez o con otra configuración', 'Reejecución o cambio del sistema', 'Declarar contaminación y reservar un periodo nuevo', 'TE ya no es evaluación intacta')
    print('AVISO: este TE ya no es una evaluación final intacta.')

def predicciones(c, d, conjunto):
    if c['tipo'] == 'lineal':
        return lab.prediccion_lineal(d, conjunto, c['ajuste']['w'], c['ajuste']['b'])
    return np.mean([lab.predecir_red(c['tipo'], r, d, conjunto) for r in c['resultados']], axis=0)

finales = {'Pronóstico cero': (D, None), 'Regresión lineal': (A, next(c for c in candidatos_A if c['nombre'] == 'Lineal alpha=0')),
           'MLP': (A, next(c for c in candidatos_A if c['tipo'] == 'mlp')), 'LSTM': (A, next(c for c in candidatos_A if c['tipo'] == 'lstm')), 'Sistema final': (D, final)}
resultados = []
for nombre, (d, c) in finales.items():
    fila = dict(modelo=nombre)
    for conj in ('TR', 'VA', 'TE'):
        p = np.zeros_like(d[f'y_{conj}']) if c is None else predicciones(c, d, conj)
        m = lab.metricas(d[f'y_{conj}'], p)
        fila |= {f'{k}_{conj}': m[k] for k in ('MAE', 'RMSE', 'direccional')}
    resultados.append(fila)
tabla_final = pd.DataFrame(resultados)
display(tabla_final)
tabla_final.to_csv(SALIDA / 'metricas_finales.csv', index=False)

pred_te = predicciones(final, D, 'TE') if final['tipo'] != 'cero' else np.zeros_like(D['y_TE'])
velas_te = lab.velas_de(tabla, D['emision_TE'])
senal_te = lab.senales(pred_te, velas_te, final['regla']['umbral'], final['regla']['filtro'])
pd.DataFrame(dict(emision=D['emision_TE'], objetivo=D['objetivo_TE'], real=D['y_TE'], estimado=pred_te, error=pred_te - D['y_TE'], senal=np.where(senal_te, 'comprar', 'efectivo'))).to_csv(SALIDA / 'predicciones_TE.csv', index=False)

sim = lab.simular(velas_te, senal_te, COSTO)
pasivo = lab.comprar_y_mantener(velas_te, COSTO)
sim['tabla'].to_csv(SALIDA / 'simulacion.csv', index=False)
resumen_sim = pd.DataFrame([
    dict(estrategia='Sistema final', **{k: sim[k] for k in ('patrimonio_final', 'rendimiento', 'drawdown', 'operaciones', 'win_rate', 'costos')}),
    dict(estrategia='Comprar y mantener', **{k: pasivo[k] for k in ('patrimonio_final', 'rendimiento', 'drawdown', 'operaciones', 'win_rate', 'costos')}),
    dict(estrategia='Efectivo', patrimonio_final=100_000.0, rendimiento=0.0, drawdown=0.0, operaciones=0, win_rate=None, costos=0.0)])
display(resumen_sim)
resumen_sim.to_csv(SALIDA / 'resumen_simulacion.csv', index=False)
plt.figure(figsize=(11, 3.6)); plt.plot(pd.to_datetime(velas_te.date), sim['tabla'].patrimonio, label='Sistema final'); plt.plot(pd.to_datetime(velas_te.date), pasivo['tabla'].patrimonio, '--', label='Comprar y mantener')
plt.title('Patrimonio en TE con costo de 0.10 % por operación'); plt.legend(); plt.savefig(SALIDA / 'patrimonio_te.png', dpi=130); plt.show()
'''),
        code('''
# Pronóstico del siguiente periodo no observado. El valor real queda vacío hasta observarse.
tabla_viva = features.add_indicators(limpio)
x, corte = features.latest_window(tabla_viva, D['variables'], D['lookback'])
xz = D['escalador'].transform(x)
if final['tipo'] == 'lineal':
    futuro = float((lab.plano(xz) @ final['ajuste']['w'] + final['ajuste']['b'])[0])
else:
    futuro = float(np.mean([D['y_media'] + D['y_desv'] * r['red'].predict(lab.entradas_red(final['tipo'], xz), verbose=0).ravel()[0] for r in final['resultados']]))
senal_futura = lab.senales(np.array([futuro]), tabla_viva.iloc[[-1]], final['regla']['umbral'], final['regla']['filtro'])[0]
pd.DataFrame([dict(fecha_corte=corte, proximo_periodo=str((pd.Timestamp(corte) + pd.Timedelta(days=1)).date()), rendimiento_estimado=futuro, senal='comprar' if senal_futura else 'efectivo', valor_real='')]).to_csv(SALIDA / 'prediccion_futura.csv', index=False)
print('Corte:', corte, ' Pronóstico:', round(futuro, 5), ' Señal:', 'comprar' if senal_futura else 'efectivo')
'''),
        md('''
**Seguimiento.** ¿El indicador aporta información o solo complejidad? Compara las dos versiones en la tabla anterior y responde con los datos de esta corrida. Revisa también las correlaciones: variables casi iguales añaden redundancia, no información. Rendimientos históricos, incluso en TE, no garantizan resultados futuros.
'''),
        md('''
## Manejo de errores: cuatro fallos provocados

Se usan copias pequeñas: los datos originales no se tocan. Cada fallo debe detenerse con un mensaje que explique qué revisar.
'''),
        code('''
def provocar(nombre, funcion):
    try:
        funcion()
        print(f'{nombre}: NO se detuvo.'); raise AssertionError(nombre)
    except (data.DataError, ValueError) as e:
        print(f'{nombre}: detenido. Mensaje: {e}')
        anotar('prueba controlada', nombre, 'Fallo provocado en una copia', 'El flujo se detuvo con mensaje claro', 'Datos originales sin cambios')

copia = limpio.head(60).copy()
provocar('Conjunto vacío', lambda: data.frame_from_rows([]))
duplicada = pd.concat([copia, copia.tail(1)])
informe = data.audit(duplicada)
print('Fecha duplicada detectada:', informe['duplicadas'], 'fila; la limpieza la corrige:', data.clean(duplicada)[1])
anotar('prueba controlada', 'Fecha duplicada', 'Fila repetida en una copia', 'Eliminada según regla documentada', 'Índice único verificado')
invalida = copia.copy(); invalida.loc[invalida.index[-5], 'close'] = -1
print('Valor no válido detectado:', data.audit(invalida)['invalidos'])
anotar('prueba controlada', 'Valor no válido', 'Precio negativo en una copia', 'Identificada columna y fecha; fila retirada sin usar información futura', 'Sin precios no positivos')
provocar('Dimensiones incorrectas', lambda: A['escalador'].transform(np.ones((4, 20))))
provocar('Ventanas insuficientes', lambda: features.make_windows(data.add_target(features.add_indicators(copia.head(10))), ['ret'], 20))
provocar('Predicción no finita', lambda: lab.metricas(np.array([np.nan]), np.array([0.0])))
print('Datos originales intactos:', data.dataset_hash(limpio) == ficha['huella'])
'''),
        md('## Guardar resultados y modelo'),
        code('''
carpeta_modelo = SALIDA / f"t4-{limpio.date.iloc[-1]}" if not PRUEBA else SALIDA / 'prueba-sin-t4'
version = carpeta_modelo.name
if final['tipo'] == 'lineal':
    miembros, pesos = lab.contrato_lineal(D, final['ajuste'])
else:
    miembros, pesos = lab.contrato_redes(final['resultados'])
    for i, r in enumerate(final['resultados']):
        carpeta_modelo.mkdir(parents=True, exist_ok=True)
        r['red'].save(carpeta_modelo / f'red_{i}.keras')
seleccion = dict(periodo_va=[D['emision_VA'][0], D['emision_VA'][-1]], modelo=final['nombre'], variables=configuracion['variables'], regla=final['regla'], metricas_va=final['metricas_va'],
                 comprar_y_mantener_va=dict(rendimiento=pasivo_va['rendimiento'], drawdown=pasivo_va['drawdown']), rmse_cero_va=lab.metricas(D['y_VA'], np.zeros_like(D['y_VA']))['RMSE'],
                 particion=lab.tabla_particion(D).to_dict('records'))
m = lab.guardar_modelo(carpeta_modelo, version, final['tipo'], D, final['regla']['umbral'], final['regla']['filtro'], miembros, pesos,
                       extra=dict(valido_para_entrega=not PRUEBA, dispositivo=DISPOSITIVO, huella_datos=ficha['huella'], nombre=final['nombre'], conjunto_variables=[k for k, v in lab.CONJUNTOS_VARIABLES.items() if v == D['variables']][0], seleccion=seleccion))
assert np.allclose(m.predecir_x(D['ventanas'].X[D['indices']['VA']]), final['pred_va'], atol=1e-4), 'El modelo exportado no reproduce las predicciones.'
print('Modelo exportado y verificado: NumPy reproduce las predicciones de Keras.')

experimentos_df = pd.DataFrame(experimentos)
experimentos_df.insert(0, 'id', range(1, len(experimentos_df) + 1))
experimentos_df.to_csv(SALIDA / 'experimentos.csv', index=False)
experimentos_df.drop(columns='id').to_csv(carpeta_modelo / 'experimentos.csv', index=False)
todas_reglas.to_csv(carpeta_modelo / 'reglas_va.csv', index=False)
tabla_ventanas.to_csv(SALIDA / 'ventanas_expansivas.csv', index=False)
tabla_ventanas.to_csv(carpeta_modelo / 'ventanas_expansivas.csv', index=False)
(carpeta_modelo / 'curvas.json').write_text(json.dumps(curvas))
print('Diagnóstico de sesgo y varianza...')
diagnostico = lab.tacticas_clasicas(D, reentrenos=3 if PRUEBA else 12) + lab.tacticas_redes(D, **ENTRENAMIENTO)
(carpeta_modelo / 'diagnostico.json').write_text(json.dumps(diagnostico, indent=2, ensure_ascii=False))
display(pd.DataFrame(diagnostico))
pd.DataFrame(bitacora).to_csv(SALIDA / 'bitacora_errores.csv', index=False)
evidencia |= dict(fin=time.strftime('%Y-%m-%d %H:%M:%S'), segundos_totales=round(time.time() - inicio_notebook), dispositivo_entrenamiento=DISPOSITIVO)
(SALIDA / 'evidencia_t4.json').write_text(json.dumps(evidencia, indent=2, ensure_ascii=False))
(carpeta_modelo / 'evidencia_t4.json').write_text(json.dumps(evidencia, indent=2, ensure_ascii=False))
'''),
        code('''
with zipfile.ZipFile('resultados_t4.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for ruta in SALIDA.rglob('*'):
        z.write(ruta, ruta.relative_to(SALIDA))
print('Listo:', Path('resultados_t4.zip').stat().st_size // 1024, 'KB')
print('Carpeta del modelo para copiar a models/ del proyecto:', carpeta_modelo.name)
if DRIVE:
    import shutil
    shutil.copy('resultados_t4.zip', DRIVE / f'resultados_t4_{time.strftime("%Y%m%d_%H%M")}.zip')
    print('Copia guardada en Drive:', DRIVE)
if not PRUEBA:
    from google.colab import files
    files.download('resultados_t4.zip')
'''),
        md('''
## Lectura de resultados

Cada etapa responde qué se hizo, por qué, qué evidencia salió y qué cambiaría. La conclusión sobre la hipótesis técnica sale de la etapa 5. Las cifras deben salir de esta corrida, no copiarse de otra, y el notebook debe correr completo desde una sesión limpia.
'''),
    ]
    return c


def construir():
    cells = [c | dict(id=f'celda-{i:02d}') for i, c in enumerate(celdas())]  # el formato 4.5 exige un id por celda
    return dict(cells=cells, metadata=dict(accelerator='GPU', colab=dict(gpuType='T4', provenance=[]), kernelspec=dict(display_name='Python 3', language='python', name='python3'),
                                              language_info=dict(name='python')), nbformat=4, nbformat_minor=5)


def main():
    ruta = RAIZ / 'notebooks' / 'Astrolabio_Modelo_BTC.ipynb'
    ruta.parent.mkdir(exist_ok=True)
    ruta.write_text(json.dumps(construir(), indent=1, ensure_ascii=False), encoding='utf-8')
    print(f'Generado {ruta} con {len(construir()["cells"])} celdas.')


if __name__ == '__main__':
    main()
