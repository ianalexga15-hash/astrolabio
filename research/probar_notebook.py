"""Ejecuta el notebook completo en modo prueba: sin GPU, con datos sintéticos y pocas épocas.

Confirma que todas las celdas corren, incluida la de TE, sin abrir el TE real. No genera evidencia válida.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import nbformat
from nbclient import NotebookClient

RAIZ = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')


def main():
    os.environ.update(NB_PRUEBA='1', KERAS_BACKEND='torch', MPLBACKEND='Agg')
    nb = nbformat.read(RAIZ / 'notebooks' / 'Astrolabio_Modelo_BTC.ipynb', as_version=4)
    trabajo = Path(tempfile.mkdtemp(prefix='nb_prueba_'))
    try:
        NotebookClient(nb, timeout=900, kernel_name='python3', resources={'metadata': {'path': str(trabajo)}}).execute()
        generados = sorted(p.name for p in (trabajo / 'resultados').iterdir())
        print('Todas las celdas corrieron. Archivos:', generados)
        faltan = {'experimentos.csv', 'predicciones_TE.csv', 'prediccion_futura.csv', 'simulacion.csv', 'bitacora_errores.csv', 'ficha_activo.json', 'apertura_te.json', 'prueba-sin-t4'} - set(generados)
        if faltan:
            raise SystemExit(f'Faltan archivos de resultados: {faltan}')
        for celda in nb.cells:
            if celda.cell_type == 'code':
                for salida in celda.outputs:
                    if 'Sistema final congelado' in str(salida.get('text', '')):
                        print(salida['text'][:300])
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)


if __name__ == '__main__':
    main()
