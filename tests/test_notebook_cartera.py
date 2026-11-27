"""El notebook de la cartera en T4 usa el mismo código que el agente, pide T4, entrena con los cortes del modelo activo y nunca abre TE."""
import json

from research import construir_notebook_cartera as nc


def texto(celda):
    return ''.join(celda['source'])


def todo():
    return '\n'.join(texto(c) for c in nc.construir()['cells'])


def test_incluye_los_modulos_tal_cual_estan_en_el_proyecto():
    fuentes = [texto(c) for c in nc.construir()['cells'] if c['cell_type'] == 'code']
    for ruta in nc.MODULOS:
        contenido = (nc.RAIZ / ruta).read_text(encoding='utf-8').rstrip()
        assert any(f.startswith(f'%%writefile {ruta}') and contenido in f for f in fuentes), ruta


def test_el_archivo_guardado_esta_al_dia():
    guardado = json.loads(nc.ARCHIVO.read_text(encoding='utf-8'))
    assert [texto(c) for c in guardado['cells']] == [texto(c) for c in nc.construir()['cells']], 'Regenera el notebook con research/construir_notebook_cartera.py'


def test_pide_t4_y_se_detiene_si_falta():
    nb = nc.construir()
    assert nb['metadata']['colab']['gpuType'] == 'T4'
    assert "'T4' not in nombre" in todo() and 'raise RuntimeError' in todo()


def test_entrena_con_los_cortes_del_modelo_activo_y_nunca_abre_te():
    _, fin_tr, fin_va = nc.cortes_activos()
    assert f"FIN_TR, FIN_VA = '{fin_tr}', '{fin_va}'" in todo()
    propio = '\n'.join(texto(c) for c in nc.construir()['cells'] if not texto(c).startswith('%%writefile'))  # lab.py va incrustado y define abrir_te; el notebook no lo llama
    assert not any(t in propio for t in ('abrir_te', 'X_TE', 'Xcrudo_TE', 'y_TE'))
