import math

import numpy as np
import pytest

from bot import data
from tests.helpers import DAY, START, random_walk, rows


def frame(n=30, **kw):
    return data.frame_from_rows(rows(random_walk(n), **kw))


def test_conjunto_vacio_se_detiene_con_mensaje_util():
    with pytest.raises(data.DataError, match='vacío'):
        data.frame_from_rows([])


def test_auditoria_cuenta_duplicados_y_desorden():
    r = rows(random_walk(10))
    r = r + [r[3]]            # fecha duplicada al final
    r[1], r[2] = r[2], r[1]   # dos fechas desordenadas
    informe = data.audit(data.frame_from_rows(r))
    assert informe['duplicadas'] == 1
    assert informe['desordenadas'] > 0


def test_auditoria_identifica_columna_y_fecha_de_valores_invalidos():
    r = rows(random_walk(10))
    r[4][4] = '-5'      # cierre no positivo
    r[6][2] = 'nan'     # máximo faltante
    informe = data.audit(data.frame_from_rows(r))
    columnas = {(x['columna'], x['fecha']) for x in informe['invalidos']}
    assert ('close', data.fecha(r[4][0])) in columnas
    assert ('high', data.fecha(r[6][0])) in columnas


def test_auditoria_reporta_huecos_y_velas_desalineadas():
    r = rows(random_walk(10))
    del r[5]
    r[0][0] -= 8 * 3_600_000  # vela que abre a las 16:00 UTC
    informe = data.audit(data.frame_from_rows(r))
    assert informe['huecos'] == [{'desde': data.fecha(r[4][0]), 'hasta': data.fecha(r[5][0]), 'dias': 2.0}]
    assert informe['desalineadas'] == 1


def test_auditoria_detecta_ohlc_incoherente():
    r = rows(random_walk(10))
    r[3][2] = '0.001'  # máximo por debajo de apertura y cierre
    assert data.audit(data.frame_from_rows(r))['incoherentes'] == [data.fecha(r[3][0])]


def test_limpieza_elimina_duplicados_y_registra_cuantas_filas_cambian():
    r = rows(random_walk(10))
    limpio, bitacora = data.clean(data.frame_from_rows(r + [r[9]]))
    assert len(limpio) == 10
    assert limpio.open_time.is_unique and limpio.open_time.is_monotonic_increasing
    assert any('1 duplicada' in linea for linea in bitacora)


def test_limpieza_conserva_el_tramo_continuo_mas_largo_sin_inventar_filas():
    r = rows(random_walk(20))
    del r[5]  # queda un tramo de 5 y otro de 14
    limpio, bitacora = data.clean(data.frame_from_rows(r))
    assert len(limpio) == 14
    assert limpio.open_time.iloc[0] == START + 6 * DAY
    assert (limpio.open_time.diff().dropna() == DAY).all()
    assert any('5' in linea for linea in bitacora)


def test_limpieza_descarta_velas_con_otro_corte_diario():
    r = rows(random_walk(12))
    for fila in r[:4]:
        fila[0] -= 8 * 3_600_000
    limpio, _ = data.clean(data.frame_from_rows(r))
    assert (limpio.open_time % DAY == 0).all()
    assert len(limpio) == 8


def test_limpieza_retira_precios_no_validos_sin_rellenar():
    r = rows(random_walk(20))
    r[2][4] = '-1'
    limpio, _ = data.clean(data.frame_from_rows(r))
    assert (limpio.close > 0).all() and len(limpio) == 17


def test_objetivo_es_el_rendimiento_del_siguiente_cierre():
    df = data.add_target(data.frame_from_rows(rows([100.0, 102.0, 51.0])))
    assert df.y.iloc[0] == pytest.approx(0.02)
    assert df.y.iloc[1] == pytest.approx(-0.5)
    assert math.isnan(df.y.iloc[2])


def test_huella_del_dataset_cambia_si_cambia_un_precio():
    a = frame()
    b = frame()
    assert data.dataset_hash(a) == data.dataset_hash(b)
    b.loc[3, 'close'] += 1
    assert data.dataset_hash(a) != data.dataset_hash(b)


def test_particion_70_15_15_es_cronologica_y_no_se_solapa():
    p = data.split_indices(1000)
    assert (len(p['TR']), len(p['VA']), len(p['TE'])) == (700, 150, 150)
    assert p['TR'][-1] < p['VA'][0] and p['VA'][-1] < p['TE'][0]
    assert np.array_equal(np.concatenate([p['TR'], p['VA'], p['TE']]), np.arange(1000))


def test_particion_rechaza_conjuntos_vacios():
    with pytest.raises(data.DataError, match='insuficient'):
        data.split_indices(5)
