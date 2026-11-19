import json
from pathlib import Path

import numpy as np
import pytest

from bot import data, features, model
from tests.helpers import random_walk, rows


def tabla(n=80, seed=3):
    return features.add_indicators(data.frame_from_rows(rows(random_walk(n, seed=seed))))


def contrato(**kw):
    base = dict(version='v-prueba', tipo='lineal', lookback=20, variables=['ret'], umbral=0.001, filtro='ninguno',
                escalador={'media': [0.0], 'desv': [1.0]}, y_media=0.0, y_desv=1.0, miembros=[])
    base.update(kw)
    return base


def test_modelo_cero_siempre_pronostica_cero():
    m = model.Modelo(contrato(tipo='cero'), {})
    assert m.pronosticar(tabla()) == 0.0


def test_lineal_aplica_pesos_e_intercepto_en_escala_original():
    pesos = {'m0_c0_w': np.full((20, 1), 0.5), 'm0_c0_b': np.array([0.1])}
    c = contrato(tipo='lineal', y_media=0.01, y_desv=0.02, miembros=[[{'tipo': 'dense', 'activacion': 'linear'}]])
    m = model.Modelo(c, pesos)
    t = tabla()
    x = t.ret.to_numpy()[-20:]
    assert m.pronosticar(t) == pytest.approx(0.01 + 0.02 * (0.5 * x.sum() + 0.1))


def test_mlp_aplica_activaciones():
    pesos = {'m0_c0_w': np.ones((20, 2)), 'm0_c0_b': np.array([-1000.0, 1.0]),
             'm0_c1_w': np.array([[2.0], [3.0]]), 'm0_c1_b': np.array([0.0])}
    c = contrato(tipo='mlp', miembros=[[{'tipo': 'dense', 'activacion': 'relu'}, {'tipo': 'dense', 'activacion': 'linear'}]])
    t = tabla()
    s = t.ret.to_numpy()[-20:].sum()
    assert model.Modelo(c, pesos).pronosticar(t) == pytest.approx(3.0 * (s + 1.0))


def test_ensamble_promedia_miembros():
    pesos = {'m0_c0_w': np.zeros((20, 1)), 'm0_c0_b': np.array([1.0]),
             'm1_c0_w': np.zeros((20, 1)), 'm1_c0_b': np.array([3.0])}
    capa = [{'tipo': 'dense', 'activacion': 'linear'}]
    assert model.Modelo(contrato(miembros=[capa, capa]), pesos).pronosticar(tabla()) == pytest.approx(2.0)


def test_senal_exige_superar_umbral():
    m = model.Modelo(contrato(tipo='cero', umbral=0.002), {})
    assert m.senal(0.003, tabla())[0] is True
    assert m.senal(0.002, tabla())[0] is False


def test_filtro_sma20_exige_cierre_por_encima_del_promedio():
    arriba = tabla()
    arriba.loc[arriba.index[-1], ['close', 'sma20']] = [110.0, 100.0]
    abajo = tabla()
    abajo.loc[abajo.index[-1], ['close', 'sma20']] = [90.0, 100.0]
    m = model.Modelo(contrato(tipo='cero', filtro='sma20'), {})
    assert m.senal(0.01, arriba)[0] is True
    assert m.senal(0.01, abajo)[0] is False


def test_si_la_regla_de_va_no_trae_filtro_se_aplica_el_filtro_minimo():
    """Decisión de Alex (2026-11-13): ningún activo compra sin filtro técnico. Con '' la regla queda como salió de VA."""
    arriba, abajo = tabla(), tabla()
    arriba.loc[arriba.index[-1], ['close', 'sma20']] = [110.0, 100.0]
    abajo.loc[abajo.index[-1], ['close', 'sma20']] = [90.0, 100.0]
    m = model.Modelo(contrato(tipo='cero', filtro='ninguno'), {})
    assert m.senal(0.01, abajo, 'sma20') == (False, dict(umbral=0.001, filtro='sma20', cumple_umbral=True, cumple_filtro=False))
    assert m.senal(0.01, arriba, 'sma20')[0] is True
    assert m.senal(0.01, abajo, '') == (True, dict(umbral=0.001, filtro='ninguno', cumple_umbral=True, cumple_filtro=True))


def test_variables_del_contrato_deben_existir():
    m = model.Modelo(contrato(variables=['no_existe']), {})
    with pytest.raises(data.DataError, match='no_existe'):
        m.pronosticar(tabla())


def test_cargar_desde_carpeta_versionada(tmp_path):
    (tmp_path / 'contrato.json').write_text(json.dumps(contrato(tipo='cero')), encoding='utf-8')
    assert model.cargar(tmp_path).version == 'v-prueba'


def test_cargar_falla_con_mensaje_util_si_falta_el_contrato(tmp_path):
    with pytest.raises(data.DataError, match='contrato.json'):
        model.cargar(tmp_path)


def test_cargar_rechaza_tipo_desconocido(tmp_path):
    (tmp_path / 'contrato.json').write_text(json.dumps(contrato(tipo='magia')), encoding='utf-8')
    with pytest.raises(data.DataError, match='magia'):
        model.cargar(tmp_path)


def test_cargar_rechaza_pesos_faltantes(tmp_path):
    c = contrato(miembros=[[{'tipo': 'dense', 'activacion': 'linear'}]])
    (tmp_path / 'contrato.json').write_text(json.dumps(c), encoding='utf-8')
    with pytest.raises(data.DataError, match='modelo.npz'):
        model.cargar(tmp_path)


def test_lstm_numpy_coincide_con_keras_si_hay_backend():
    keras = pytest.importorskip('keras')
    from keras import layers
    keras.utils.set_random_seed(1)
    red = keras.Sequential([layers.Input((20, 2)), layers.LSTM(4), layers.Dense(3, activation='relu'), layers.Dropout(0.1), layers.Dense(1)])
    x = np.random.default_rng(0).normal(size=(5, 20, 2)).astype('float32')
    miembro, pesos = model.exportar_keras(red, 0)
    salida = model.adelante(miembro, pesos, 0, x)
    assert salida == pytest.approx(red.predict(x, verbose=0).ravel(), abs=1e-5)


def test_mlp_numpy_coincide_con_keras_si_hay_backend():
    keras = pytest.importorskip('keras')
    from keras import layers
    keras.utils.set_random_seed(2)
    red = keras.Sequential([layers.Input((40,)), layers.Dense(8, activation='relu'), layers.Dense(1)])
    x = np.random.default_rng(1).normal(size=(5, 20, 2)).astype('float32')
    miembro, pesos = model.exportar_keras(red, 0)
    salida = model.adelante(miembro, pesos, 0, x)
    assert salida == pytest.approx(red.predict(x.reshape(5, -1), verbose=0).ravel(), abs=1e-5)


# Integridad al cargar: un modelo dañado nunca llega a operar
def guardar(raiz, nombre='v-integro', pesos=None, **cambios):
    """Modelo lineal válido como lo deja el entrenamiento: la carpeta lleva el nombre de su versión."""
    carpeta = raiz / nombre
    carpeta.mkdir()
    c = contrato(version=nombre, miembros=[[{'tipo': 'dense', 'activacion': 'linear'}]]) | cambios
    (carpeta / 'contrato.json').write_text(json.dumps(c), encoding='utf-8')
    np.savez(carpeta / 'modelo.npz', **(pesos or dict(m0_c0_w=np.full((20, 1), 0.01), m0_c0_b=np.zeros(1))))
    return carpeta


def test_modelo_integro_carga_con_su_version(tmp_path):
    m = model.cargar(guardar(tmp_path), version='v-integro')
    assert m.version == 'v-integro' and np.isfinite(m.predecir_x(np.zeros((1, 20, 1)))).all()


@pytest.mark.parametrize('cambios, pesos, fragmento', [
    (dict(version='otra'), None, 'versión'),
    (dict(umbral=float('nan')), None, 'umbral'),
    (dict(y_desv=0.0), None, 'y_desv'),
    (dict(filtro='rsi'), None, 'filtro'),
    (dict(lookback=0), None, 'lookback'),
    (dict(variables=[]), None, 'variables'),
    (dict(escalador={'media': [0.0], 'desv': [0.0]}), None, 'escalador'),
    (dict(escalador={'media': [0.0, 1.0], 'desv': [1.0, 1.0]}), None, 'escalador'),
    (dict(escalador={'media': [float('inf')], 'desv': [1.0]}), None, 'escalador'),
    ({}, dict(m0_c0_w=np.full((20, 1), np.nan), m0_c0_b=np.zeros(1)), 'm0_c0_w'),
    ({}, dict(m0_c0_w=np.full((19, 1), 0.01), m0_c0_b=np.zeros(1)), 'no encajan'),
    ({}, dict(m0_c0_w=np.full((20, 1), 0.01)), 'no encajan'),
    (dict(miembros=[[{'tipo': 'dense', 'activacion': 'magia'}]]), None, 'no encajan'),
], ids=['version', 'umbral-nan', 'y_desv-cero', 'filtro', 'lookback', 'sin-variables', 'escalador-desv-cero',
        'escalador-largo', 'escalador-inf', 'peso-nan', 'peso-forma', 'falta-sesgo', 'activacion'])
def test_modelo_incoherente_falla_cerrado_con_error_claro(tmp_path, cambios, pesos, fragmento):
    with pytest.raises(data.DataError, match=fragmento):
        model.cargar(guardar(tmp_path, pesos=pesos, **cambios), version='v-integro')


@pytest.mark.parametrize('archivo, danar', [
    ('contrato.json', lambda b: b[:len(b) // 2]),
    ('modelo.npz', lambda b: b[:len(b) // 2]),
    ('modelo.npz', lambda b: b[:60] + bytes(40) + b[100:]),
    ('modelo.npz', lambda b: b'basura'),
    ('modelo.npz', lambda b: b''),
], ids=['json-cortado', 'npz-truncado', 'npz-bytes-cambiados', 'npz-basura', 'npz-vacio'])
def test_archivo_danado_falla_cerrado_con_error_claro(tmp_path, archivo, danar):
    ruta = guardar(tmp_path) / archivo
    ruta.write_bytes(danar(ruta.read_bytes()))
    with pytest.raises(data.DataError, match=archivo):
        model.cargar(ruta.parent, version='v-integro')


@pytest.mark.parametrize('puntero', ['ACTIVO.txt', 'CARTERA.txt'])
def test_los_modelos_en_uso_pasan_la_revision_sin_cambios(puntero):
    raiz = Path(__file__).resolve().parents[1] / 'models'
    carpeta = raiz / (raiz / puntero).read_text(encoding='utf-8').strip()
    assert model.cargar(carpeta, version=carpeta.name).version == carpeta.name


def test_el_contrato_que_exporta_el_notebook_de_t4_pasa_la_revision(tmp_path):
    from research import lab
    d = dict(lookback=20, variables=['ret'], escalador=features.Scaler([0.001], [0.03]), y_media=0.001, y_desv=0.03)
    miembros, pesos = lab.contrato_lineal(d, dict(w=np.full(20, 0.01), b=0.0))
    carpeta = tmp_path / 't4-2026-11-12'  # como en el notebook: la carpeta lleva el nombre de la versión
    lab.guardar_modelo(carpeta, carpeta.name, 'lineal', d, 0.001, 'sma20', miembros, pesos, extra=dict(valido_para_entrega=True))
    assert model.cargar(carpeta, version=carpeta.name).version == 't4-2026-11-12'
