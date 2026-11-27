"""Genera notebooks/Astrolabio_Modelo_Cartera.ipynb: el modelo conjunto de la cartera entrenado en una T4 de Colab.

Mismo protocolo que research/entrenar_cartera.py (CPU): mismas variables, redes, hiperparámetros y regla elegida con VA, y los mismos cortes
de fecha que el modelo de cartera activo, para comparar ambos en el mismo VA. TE no se abre. El código se copia de bot/ y research/.
"""
import json
from pathlib import Path

from research.construir_notebook import code, md, modulo

RAIZ = Path(__file__).resolve().parent.parent
MODULOS = ['bot/data.py', 'bot/features.py', 'bot/metricas_riesgo.py', 'bot/model.py', 'research/lab.py', 'research/cartera.py']
COMMIT_DATOS = '96f7faaf8692c979e3621983405da2d592a962f0'  # data/cartera y config/universo.json se bajan de este commit del repositorio público
ARCHIVO = RAIZ / 'notebooks' / 'Astrolabio_Modelo_Cartera.ipynb'


def cortes_activos():
    """Últimas fechas objetivo de TR y VA del modelo de cartera activo, para entrenar con la misma partición."""
    version = (RAIZ / 'models' / 'CARTERA.txt').read_text(encoding='utf-8').strip()
    particion = {p['conjunto']: p for p in json.loads((RAIZ / 'models' / version / 'contrato.json').read_text(encoding='utf-8'))['seleccion']['particion']}
    return version, particion['TR']['ultimo_objetivo'], particion['VA']['ultimo_objetivo']


def celdas():
    version, fin_tr, fin_va = cortes_activos()
    c = [md(f'''
# Astrolabio: modelo conjunto de la cartera en T4

Entrena en una GPU T4 el modelo que pronostica el rendimiento del día siguiente de los activos de la cartera. Sigue el mismo protocolo que el entrenamiento de desarrollo en CPU: mismas variables, mismas redes, mismos hiperparámetros, regla elegida con VA simulando la cartera completa y los mismos cortes de fecha que `{version}`. **TE no se abre.**

**Cómo ejecutarlo.** En Colab elige *Entorno de ejecución > Cambiar tipo > GPU T4* y después *Ejecutar todo*. Si Colab no asigna una T4, el notebook se detiene antes de entrenar. Al terminar se descarga `resultados_cartera_t4.zip`; su carpeta `t4-cartera-…` va a `models/` del proyecto.

**Datos.** Las velas diarias de `data/cartera/` y el universo de `config/universo.json` se bajan del repositorio público, fijados a un commit: son exactamente los del proyecto.
'''),
         md('## Entorno y evidencia de T4'),
         code('''
import json, os, platform, shutil, subprocess, sys, time, zipfile
from pathlib import Path

PRUEBA = os.environ.get('NB_PRUEBA') == '1'  # solo para probar el notebook sin GPU, con cuatro activos y dos épocas; no es evidencia válida
SEMILLA_GLOBAL = 11
os.makedirs('bot', exist_ok=True); os.makedirs('research', exist_ok=True); os.makedirs('resultados', exist_ok=True)
for ruta in ('bot/__init__.py', 'research/__init__.py'):
    Path(ruta).touch()
SALIDA = Path('resultados')
inicio_notebook = time.time()
'''),
         code('''
evidencia = dict(python=platform.python_version(), semilla=SEMILLA_GLOBAL, inicio=time.strftime('%Y-%m-%d %H:%M:%S'), prueba_sin_gpu=PRUEBA)
if PRUEBA:
    print('MODO PRUEBA: sin T4, con cuatro activos y dos épocas. Esta corrida NO sirve como evidencia de T4.')
    evidencia |= dict(gpu='ninguna', valido_para_entrega=False)
else:
    try:
        salida = subprocess.run(['nvidia-smi'], capture_output=True, text=True, check=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        raise RuntimeError('No hay GPU en esta sesión. Elige Entorno de ejecución > Cambiar tipo > GPU T4 y vuelve a ejecutar.') from e
    print(salida)
    (SALIDA / 'nvidia_smi.txt').write_text(salida)
    import tensorflow as tf
    gpus = tf.config.list_physical_devices('GPU')
    nombre = tf.config.experimental.get_device_details(gpus[0]).get('device_name', '') if gpus else ''
    print('GPU detectada:', nombre or 'ninguna')
    if 'T4' not in nombre:
        raise RuntimeError('No se asignó una T4: se detiene el entrenamiento. Reprograma la ejecución.')
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
         md('''
### Código del proyecto

Estas celdas escriben los mismos módulos que usa el agente y el entrenamiento en CPU: las variables, la partición y la regla se calculan igual.
''')]
    c += [modulo(r) for r in MODULOS]
    c += [
        code(f'''
import numpy as np, pandas as pd
from urllib.parse import quote
from urllib.request import urlopen
from bot import data
from research import cartera, lab
keras.utils.set_random_seed(SEMILLA_GLOBAL)
np.random.seed(SEMILLA_GLOBAL)
COMMIT = '{COMMIT_DATOS}'
FIN_TR, FIN_VA = '{fin_tr}', '{fin_va}'  # mismos cortes que {version}: los dos modelos se comparan en el mismo VA y TE sigue cerrado
ENTRENAMIENTO = dict(epocas=2, lote=256, paciencia=1) if PRUEBA else dict(epocas=60, lote=256, paciencia=8)  # los mismos del entrenamiento en CPU
'''),
        md('## 1. Datos de la cartera'),
        code('''
BASE = f'https://raw.githubusercontent.com/ianalexga15-hash/astrolabio/{COMMIT}/'
LOCAL = os.environ.get('NB_DATOS')  # solo al probar fuera de Colab: carpeta local del proyecto

def traer(ruta):
    destino = Path(ruta)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if LOCAL:
        shutil.copy(Path(LOCAL) / ruta, destino)
    else:
        destino.write_bytes(urlopen(BASE + quote(ruta), timeout=60).read())

traer('config/universo.json')
universo = json.loads(Path('config/universo.json').read_text(encoding='utf-8'))
if PRUEBA:
    universo['simbolos'] = universo['simbolos'][:4]
    Path('config/universo.json').write_text(json.dumps(universo), encoding='utf-8')
for s in universo['simbolos']:
    traer(f'data/cartera/{s}.csv')
huella_datos = lab.huella({s: data.dataset_hash(pd.read_csv(f'data/cartera/{s}.csv')) for s in universo['simbolos']})
tablas, _ = cartera.cargar_tablas('.')
d = cartera.preparar_conjunto(tablas, FIN_TR, FIN_VA)
assert max(d['objetivo_TR']) <= FIN_TR < min(d['objetivo_VA']) and max(d['objetivo_VA']) <= FIN_VA, 'La partición no respeta los cortes.'
display(pd.DataFrame([dict(conjunto=k, ejemplos=len(d[f'y_{k}']), primer_objetivo=min(d[f'objetivo_{k}']), ultimo_objetivo=max(d[f'objetivo_{k}'])) for k in ('TR', 'VA', 'TE')]))
print('Activos:', len(tablas), '| huella de los datos:', huella_datos[:16], '| TE no se evalúa en este notebook.')
'''),
        md('''
## 2. Redes en la T4

Referencias (pronóstico cero, regresión lineal y Ridge), MLP y LSTM. Tres configuraciones por red elegidas por RMSE de VA; la mejor se repite con tres semillas y forma un ensamble. Parada temprana con VA.
'''),
        code('''
DISPOSITIVO = 'cpu (prueba)' if PRUEBA else evidencia['gpu']
experimentos, curvas = [], {}
inicio_redes = time.time()
candidatos = lab.probar_referencias(d, 'rezagos_indicadores', experimentos, dispositivo=DISPOSITIVO)
for tipo, configs in (('mlp', lab.CONFIGS_MLP), ('lstm', lab.CONFIGS_LSTM)):
    c = lab.probar_red(d, 'rezagos_indicadores', tipo, configs, experimentos, curvas, dispositivo=DISPOSITIVO, **ENTRENAMIENTO)
    print(c['nombre'], f"RMSE_VA media={c['rmse_media']:.6f}", f'{time.time() - inicio_redes:.0f} s en {DISPOSITIVO}', flush=True)
    candidatos.append(c)
if not PRUEBA:
    evidencia['memoria_gpu_pico'] = tf.config.experimental.get_memory_info('GPU:0')['peak']
display(pd.DataFrame(experimentos))
'''),
        md('## 3. Regla elegida con VA, simulando la cartera completa'),
        code('''
final, reglas = cartera.seleccionar(tablas, d, candidatos)
print('Elegido:', final['nombre'], final['regla'])
'''),
        md('## 4. Modelo, evidencia y descarga'),
        code('''
version = f"t4-cartera-{d['fin_va']}-{len(tablas)}" if not PRUEBA else 'prueba-cartera-sin-t4'
carpeta = SALIDA / version
motivo = 'Modelo conjunto entrenado en T4 con el protocolo de la cartera; TE sin abrir.' if not PRUEBA else 'Prueba del notebook sin T4.'
sim, pasivo, resumen = cartera.guardar(carpeta, version, tablas, d, final, reglas, experimentos, curvas,
                                       extra=dict(valido_para_entrega=not PRUEBA, dispositivo=DISPOSITIVO, motivo=motivo, huella_datos=huella_datos, commit_datos=COMMIT))
print('Modelo exportado y verificado: NumPy reproduce las predicciones de Keras en VA.')
print('Cartera en VA:', round(sim['rendimiento'], 4), 'caída', round(sim['drawdown'], 4), '| comprar y mantener:', round(pasivo['rendimiento'], 4), 'caída', round(pasivo['drawdown'], 4))
evidencia |= dict(fin=time.strftime('%Y-%m-%d %H:%M:%S'), segundos_totales=round(time.time() - inicio_notebook), dispositivo_entrenamiento=DISPOSITIVO)
(carpeta / 'evidencia_t4.json').write_text(json.dumps(evidencia, indent=2, ensure_ascii=False))
print(json.dumps(evidencia, indent=2, ensure_ascii=False))
'''),
        code('''
with zipfile.ZipFile('resultados_cartera_t4.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for ruta in SALIDA.rglob('*'):
        z.write(ruta, ruta.relative_to(SALIDA))
print('Listo:', Path('resultados_cartera_t4.zip').stat().st_size // 1024, 'KB. Carpeta del modelo:', version)
if not PRUEBA:
    from google.colab import files
    files.download('resultados_cartera_t4.zip')
'''),
        md('''
## Cuándo reemplaza al modelo activo

Regla fijada antes de ver resultados: el modelo de T4 reemplaza al activo solo si, en el replay de la cartera sobre VA, sube el rendimiento sin que suba la caída máxima, o baja la caída sin que baje el rendimiento. Un resultado mixto lo deja como evidencia, sin activarlo. TE no se usa para decidir.
'''),
    ]
    return c


def construir():
    cells = [c | dict(id=f'celda-{i:02d}') for i, c in enumerate(celdas())]
    return dict(cells=cells, metadata=dict(accelerator='GPU', colab=dict(gpuType='T4', provenance=[]), kernelspec=dict(display_name='Python 3', language='python', name='python3'),
                                              language_info=dict(name='python')), nbformat=4, nbformat_minor=5)


def main():
    ARCHIVO.parent.mkdir(exist_ok=True)
    nb = construir()
    ARCHIVO.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding='utf-8')
    print(f'Generado {ARCHIVO} con {len(nb["cells"])} celdas.')


if __name__ == '__main__':
    main()
