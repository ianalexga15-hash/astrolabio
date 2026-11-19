"""El notebook usa exactamente el mismo código que el agente y cumple sus reglas."""
import json

from research import construir_notebook as cn


def texto(celda):
    return ''.join(celda['source'])


def test_el_notebook_incluye_los_modulos_tal_cual_estan_en_el_proyecto():
    celdas = cn.construir()['cells']
    fuentes = [texto(c) for c in celdas if c['cell_type'] == 'code']
    for ruta in cn.MODULOS:
        contenido = (cn.RAIZ / ruta).read_text(encoding='utf-8').rstrip()
        assert any(f.startswith(f'%%writefile {ruta}') and contenido in f for f in fuentes), ruta


def test_el_archivo_guardado_esta_al_dia_con_los_modulos():
    guardado = json.loads((cn.RAIZ / 'notebooks/Astrolabio_Modelo_BTC.ipynb').read_text(encoding='utf-8'))
    assert [texto(c) for c in guardado['cells']] == [texto(c) for c in cn.construir()['cells']], 'Regenera el notebook con research/construir_notebook.py'


def test_el_notebook_pide_t4_en_colab_y_se_detiene_si_falta():
    nb = cn.construir()
    assert nb['metadata']['colab']['gpuType'] == 'T4'
    todo = '\n'.join(texto(c) for c in nb['cells'])
    assert "'T4' not in nombre" in todo and 'raise RuntimeError' in todo


def test_el_notebook_recorre_las_cinco_etapas_y_sus_resultados():
    todo = '\n'.join(texto(c) for c in cn.construir()['cells'])
    for etapa in ('## 1. ', '## 2. ', '## 3. ', '## 4. ', '## 5. '):
        assert etapa in todo
    for archivo in ('experimentos.csv', 'predicciones_TE.csv', 'prediccion_futura.csv', 'simulacion.csv', 'bitacora_errores.csv', 'datos_originales.csv', 'datos_procesados.csv'):
        assert archivo in todo


def test_la_carpeta_del_modelo_trae_los_archivos_que_muestra_el_panel():
    todo = '\n'.join(texto(c) for c in cn.construir()['cells'])
    for archivo in ('experimentos.csv', 'reglas_va.csv', 'ventanas_expansivas.csv', 'curvas.json', 'diagnostico.json'):  # los que lee bot/api.py
        assert f"carpeta_modelo / '{archivo}'" in todo, archivo


def test_te_solo_se_abre_en_una_celda_y_despues_de_congelar():
    celdas = [texto(c) for c in cn.construir()['cells'] if c['cell_type'] == 'code' and not texto(c).startswith('%%writefile')]
    apertura = [i for i, f in enumerate(celdas) if 'lab.abrir_te(' in f]
    congelado = [i for i, f in enumerate(celdas) if 'configuracion = dict(' in f]
    assert len(apertura) == 1 and congelado and congelado[0] < apertura[0]
    primera_te = min(i for i, f in enumerate(celdas) if "'TE')" in f or "y_TE" in f or "emision_TE" in f)
    assert primera_te >= apertura[0]


def test_el_notebook_cumple_el_formato_4_5_con_ids_de_celda():
    import warnings

    import nbformat
    nb = nbformat.from_dict(cn.construir())
    ids = [c['id'] for c in nb.cells]
    assert len(set(ids)) == len(ids)
    with warnings.catch_warnings():
        warnings.simplefilter('error')  # nbformat avisa que faltar el id será un error
        nbformat.validate(nb)

