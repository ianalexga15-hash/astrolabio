import dataclasses

import pytest

from bot.paper import Cuenta
from bot.risk import Contexto, Limites, evaluar

L = Limites(simbolo='BTCUSDT', capital_inicial=50_000.0, comision=0.0, deslizamiento_bps=5.0, exposicion_max=0.8,
            perdida_diaria_max=0.05, drawdown_max=0.25, antiguedad_max_horas=26.0, riesgo_por_operacion=0.02,
            stop_atr=2.0, objetivo_atr=4.0, trailing_atr=2.0)


def ctx(**kw):
    base = dict(estado='activo', simbolo='BTCUSDT', edad_horas=1.0, senal=True, cuenta=Cuenta(efectivo=50_000.0),
                precio=100.0, atr_abs=2.0, patrimonio=50_000.0, patrimonio_inicio_dia=50_000.0, patrimonio_maximo=50_000.0)
    base.update(kw)
    return Contexto(**base)


def con_posicion():
    return Cuenta(efectivo=10_000.0, cantidad=400.0, precio_medio=100.0)


@pytest.mark.parametrize('campo', ['precio', 'patrimonio', 'patrimonio_inicio_dia', 'patrimonio_maximo', 'edad_horas'])
@pytest.mark.parametrize('valor', [float('nan'), float('inf'), -float('inf'), -1.0])
def test_no_autoriza_compra_con_contexto_invalido(campo, valor):
    assert not evaluar('comprar', ctx(**{campo: valor}), L).aprobada


@pytest.mark.parametrize('campo', ['precio', 'patrimonio', 'patrimonio_inicio_dia', 'patrimonio_maximo'])
def test_no_autoriza_compra_con_base_cero(campo):
    assert not evaluar('comprar', ctx(**{campo: 0.0}), L).aprobada


@pytest.mark.parametrize('efectivo', [float('nan'), float('inf'), -1.0, 0.0])
def test_no_autoriza_compra_sin_efectivo_valido(efectivo):
    assert not evaluar('comprar', ctx(cuenta=Cuenta(efectivo=efectivo)), L).aprobada


def test_no_autoriza_stop_cero_o_negativo():
    assert not evaluar('comprar', ctx(atr_abs=50.0), L).aprobada
    assert not evaluar('comprar', ctx(atr_abs=60.0), L).aprobada


def test_salida_no_depende_de_patrimonio_o_atr_para_dimensionar_compra():
    assert evaluar('vender', ctx(cuenta=con_posicion(), patrimonio=float('nan'), atr_abs=float('nan')), L).aprobada


def test_compra_aprobada_dimensiona_por_riesgo_y_coloca_stop_y_objetivo():
    d = evaluar('comprar', ctx(), L)
    assert d.aprobada and d.accion == 'comprar'
    # riesgo 2% de 50 000 = 1 000; distancia al stop = 2 ATR = 4; 250 unidades = 25 000 < tope de 40 000
    assert d.monto_quote == pytest.approx(25_000)
    assert d.stop == pytest.approx(96.0) and d.objetivo == pytest.approx(108.0)


def test_exposicion_nunca_supera_el_limite():
    d = evaluar('comprar', ctx(atr_abs=0.01), L)
    assert d.aprobada and d.monto_quote == pytest.approx(40_000)


def test_sin_apalancamiento_la_compra_no_supera_el_efectivo():
    d = evaluar('comprar', ctx(atr_abs=0.01, cuenta=Cuenta(efectivo=1_000.0), patrimonio=50_000.0), L)
    assert d.monto_quote == pytest.approx(1_000)


def test_rechaza_exposicion_mayor_a_uno_al_configurar():
    with pytest.raises(ValueError, match='apalancamiento'):
        dataclasses.replace(L, exposicion_max=1.5).validar()


@pytest.mark.parametrize('campo,valor', [('perdida_diaria_max', 0), ('antiguedad_max_horas', -1), ('capital_inicial', 0),
                                         ('riesgo_por_operacion', 0.9), ('comision', -0.1)])
def test_rechaza_limites_fuera_de_rango(campo, valor):
    with pytest.raises(ValueError):
        dataclasses.replace(L, **{campo: valor}).validar()


def test_los_limites_son_inmutables():
    with pytest.raises(dataclasses.FrozenInstanceError):
        L.exposicion_max = 1.0


@pytest.mark.parametrize('estado', ['pausado', 'detenido', 'bloqueado'])
def test_no_abre_si_el_bot_no_esta_activo(estado):
    d = evaluar('comprar', ctx(estado=estado), L)
    assert not d.aprobada and d.accion == 'mantener' and estado in ' '.join(d.motivos)


def test_rechaza_dato_atrasado():
    d = evaluar('comprar', ctx(edad_horas=30.0), L)
    assert not d.aprobada and 'atrasado' in ' '.join(d.motivos)


def test_rechaza_simbolo_no_permitido():
    d = evaluar('comprar', ctx(simbolo='DOGEUSDT'), L)
    assert not d.aprobada and 'DOGEUSDT' in ' '.join(d.motivos)


def test_rechaza_accion_no_permitida():
    d = evaluar('apostar', ctx(), L)
    assert not d.aprobada and d.accion == 'mantener'


def test_el_llm_no_puede_abrir_si_el_modelo_no_da_senal():
    d = evaluar('comprar', ctx(senal=False), L)
    assert not d.aprobada and 'señal' in ' '.join(d.motivos)


def test_no_compra_con_posicion_abierta():
    d = evaluar('comprar', ctx(cuenta=con_posicion()), L)
    assert not d.aprobada and 'posición' in ' '.join(d.motivos)


def test_no_vende_sin_posicion():
    d = evaluar('vender', ctx(), L)
    assert not d.aprobada and 'posición' in ' '.join(d.motivos)


def test_vender_con_posicion_se_aprueba_aunque_haya_senal():
    d = evaluar('vender', ctx(cuenta=con_posicion()), L)
    assert d.aprobada and d.accion == 'vender'


def test_mantener_siempre_se_aprueba_y_no_genera_monto():
    d = evaluar('mantener', ctx(senal=False), L)
    assert d.aprobada and d.accion == 'mantener' and d.monto_quote == 0


def test_perdida_diaria_alcanzada_bloquea_nuevas_compras():
    d = evaluar('comprar', ctx(patrimonio=47_000.0, patrimonio_inicio_dia=50_000.0), L)
    assert not d.aprobada and 'pérdida diaria' in ' '.join(d.motivos)


def test_perdida_diaria_permite_reducir_riesgo():
    d = evaluar('vender', ctx(cuenta=con_posicion(), patrimonio=47_000.0, patrimonio_inicio_dia=50_000.0), L)
    assert d.aprobada


def test_caida_maxima_alcanzada_bloquea_y_lo_informa():
    d = evaluar('comprar', ctx(patrimonio=35_000.0, patrimonio_inicio_dia=35_000.0, patrimonio_maximo=50_000.0), L)
    assert not d.aprobada and d.bloquear and 'caída máxima' in ' '.join(d.motivos)


def test_atr_invalido_impide_dimensionar():
    d = evaluar('comprar', ctx(atr_abs=float('nan')), L)
    assert not d.aprobada and 'ATR' in ' '.join(d.motivos)


def test_maquina_del_tiempo_bloquea_la_compra_que_en_promedio_pierde():
    lim = dataclasses.replace(L, maquina_tiempo=True)
    contra = dict(objetivo=0.2, stop=0.75, abiertas=0.05, r_medio=-0.31)
    d = evaluar('comprar', ctx(maquina=contra), lim)
    assert not d.aprobada and 'Máquina del tiempo' in d.motivos[0] and '-0.31 R' in d.motivos[0]
    assert evaluar('comprar', ctx(maquina=dict(contra, r_medio=0.4)), lim).aprobada
    assert evaluar('comprar', ctx(maquina=contra), L).aprobada  # apagada no decide
    assert evaluar('comprar', ctx(), lim).aprobada  # sin repaso, como en el reflejo, no bloquea


def test_maquina_del_tiempo_solo_acepta_verdadero_o_falso():
    with pytest.raises(ValueError, match='verdadero o falso'):
        dataclasses.replace(L, maquina_tiempo='no').validar()


def test_tope_diario_bloquea_la_compra_cuando_la_cartera_ya_autorizo_el_maximo():
    lim = dataclasses.replace(L, max_compras_dia=3)
    d = evaluar('comprar', ctx(compras_hoy=3), lim)
    assert not d.aprobada and 'Tope diario' in d.motivos[0] and 'ya autorizó 3' in d.motivos[0]
    assert evaluar('comprar', ctx(compras_hoy=2), lim).aprobada
    assert evaluar('comprar', ctx(compras_hoy=9), L).aprobada  # 0 es sin tope
    assert evaluar('comprar', ctx(), lim).aprobada  # sin conteo, como en el reflejo, no bloquea


@pytest.mark.parametrize('valor', [-1, 2.5, True, '3'])
def test_tope_diario_es_un_entero_no_negativo(valor):
    with pytest.raises(ValueError, match='max_compras_dia'):
        dataclasses.replace(L, max_compras_dia=valor).validar()


@pytest.mark.parametrize('valor', [-0.5, 4.0])
def test_punto_de_equilibrio_va_de_0_a_antes_del_objetivo(valor):
    with pytest.raises(ValueError, match='proteger_atr'):
        dataclasses.replace(L, proteger_atr=valor).validar()


@pytest.mark.parametrize('campo', ['comision', 'deslizamiento_bps', 'stop_atr', 'capital_inicial'])
def test_los_limites_rechazan_numeros_no_finitos(campo):
    with pytest.raises(ValueError, match=campo):
        dataclasses.replace(L, **{campo: float('nan')}).validar()


def test_maquina_del_tiempo_sin_un_repaso_valido_no_autoriza():
    lim = dataclasses.replace(L, maquina_tiempo=True)
    for malo in (dict(objetivo=0.5, stop=0.5, abiertas=0.0, r_medio=float('nan')), dict(r_medio=float('nan'))):
        d = evaluar('comprar', ctx(maquina=malo), lim)
        assert not d.aprobada and 'sin un repaso válido' in d.motivos[0]


def test_pausa_tras_perdida_no_compra_hasta_cumplir_los_dias():
    lim = dataclasses.replace(L, pausa_tras_perdida_dias=3)
    d = evaluar('comprar', ctx(dias_desde_perdida=2), lim)
    assert not d.aprobada and 'Pausa tras pérdida' in d.motivos[0]
    assert evaluar('comprar', ctx(dias_desde_perdida=3), lim).aprobada
    assert evaluar('comprar', ctx(dias_desde_perdida=None), lim).aprobada  # ningún stop con pérdida
    assert evaluar('comprar', ctx(dias_desde_perdida=0), L).aprobada  # apagada por defecto


def test_objetivo_pct_vende_al_13_mas_la_comision_de_cada_par():
    """Meta por operación: 13 % si el par no cobra comisión; si cobra, 13 % más esa comisión."""
    assert L.objetivo_pct == 0  # por defecto sigue el objetivo en ATR: 100 + 4 × 2 = 108
    lim = dataclasses.replace(L, objetivo_pct=0.13, comision_por_par=(('BTCUSDT', 0.0005), ('XRPUSDT', 0.0), ('ZIGUSDT', 0.0008)))
    d = evaluar('comprar', ctx(), lim)
    assert d.aprobada and d.objetivo == pytest.approx(113.05) and d.stop == pytest.approx(96.0)  # el stop no cambia
    for simbolo, objetivo in (('XRPUSDT', 113.0), ('ZIGUSDT', 113.08)):
        d = evaluar('comprar', ctx(simbolo=simbolo), dataclasses.replace(lim, simbolo=simbolo))
        assert d.aprobada and d.objetivo == pytest.approx(objetivo)
    assert not evaluar('comprar', ctx(atr_abs=50.0), lim).aprobada  # sigue exigiendo 0 < stop < precio < objetivo


@pytest.mark.parametrize('valor', [-0.1, 1.0, 2.0, float('nan'), float('inf')])
def test_objetivo_pct_va_de_0_a_menos_de_1(valor):
    with pytest.raises(ValueError, match='objetivo_pct'):
        dataclasses.replace(L, objetivo_pct=valor).validar()


def test_filtro_minimo_acepta_los_filtros_del_modelo_o_vacio():
    assert L.filtro_minimo == ''  # apagado por defecto: lo enciende config/riesgo.json
    for valor in ('', 'sma20'):
        dataclasses.replace(L, filtro_minimo=valor).validar()
    for valor in ('rsi', 'ninguno', None, 0):  # para apagarlo se usa '', no «ninguno»
        with pytest.raises(ValueError, match='filtro_minimo'):
            dataclasses.replace(L, filtro_minimo=valor).validar()


@pytest.mark.parametrize('valor', [-1.0, float('nan')])
def test_pausa_tras_perdida_rechaza_valores_invalidos(valor):
    with pytest.raises(ValueError, match='pausa_tras_perdida_dias'):
        dataclasses.replace(L, pausa_tras_perdida_dias=valor).validar()
