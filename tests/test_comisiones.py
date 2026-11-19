"""Comisión real por par: cada activo cobra la de MEXC para la cuenta; un par sin dato usa la comisión general."""
import json
from dataclasses import replace

from bot.config import cargar_limites, limites_a_dict, limites_desde
from bot.store import Store

BASE = dict(simbolo='BTCUSDT', capital_inicial=1000.0, comision=0.0008, deslizamiento_bps=5.0, exposicion_max=0.8, perdida_diaria_max=0.05,
            drawdown_max=0.25, antiguedad_max_horas=26.0, riesgo_por_operacion=0.02, stop_atr=2.0, objetivo_atr=4.0, trailing_atr=2.0)


def test_cada_par_usa_su_comision_real_y_sin_dato_la_general():
    lim = limites_desde(BASE | dict(comision_por_par=[['XRPUSDT', 0.0], ['BTCUSDT', 0.0005]]))
    assert lim.comision_efectiva == 0.0005
    assert replace(lim, simbolo='XRPUSDT').comision_efectiva == 0.0
    assert replace(lim, simbolo='ZIGUSDT').comision_efectiva == 0.0008


def test_la_comision_por_par_sobrevive_al_guardar_desde_el_panel():
    lim = limites_desde(BASE | dict(comision_por_par=[['XRPUSDT', 0.0]]))
    otra = limites_desde(json.loads(json.dumps(limites_a_dict(lim))))
    assert replace(otra, simbolo='XRPUSDT').comision_efectiva == 0.0 and otra.comision_efectiva == 0.0008


def test_cargar_limites_toma_las_comisiones_reales_del_archivo(tmp_path):
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'riesgo.json').write_text(json.dumps(BASE), encoding='utf-8')
    (tmp_path / 'config' / 'comisiones.json').write_text(json.dumps({'XRPUSDT': 0.0, 'BTCUSDT': 0.0005}), encoding='utf-8')
    lim = cargar_limites(tmp_path, Store(tmp_path / 'bot.sqlite3'))
    assert lim.comision == 0.0008 and lim.comision_efectiva == 0.0005
    assert replace(lim, simbolo='XRPUSDT').comision_efectiva == 0.0


def test_la_espera_y_su_comision_no_pueden_ser_negativas():
    import pytest
    for campo in ('espera_max_min', 'comision_espera'):
        with pytest.raises(ValueError, match="negativ"):
            limites_desde(BASE | {campo: -1})
