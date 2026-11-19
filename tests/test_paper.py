import pytest

from bot.paper import Cuenta, Filtros, OrdenRechazada, comprar, mover_trailing, patrimonio, precio_por_libro, revisar_stops, vender

F = Filtros(paso_cantidad=0.001, minimo_quote=1.0)


def test_compra_redondea_hacia_abajo_al_paso_y_descuenta_comision():
    c = Cuenta(efectivo=1000.0)
    e = comprar(c, precio=333.0, monto_quote=1000.0, filtros=F, comision=0.001, deslizamiento_bps=0)
    assert e.cantidad == pytest.approx(3.0)          # 3.003 cabría sin comisión; el paso y la comisión lo bajan
    assert e.precio == 333.0
    assert e.comision == pytest.approx(3 * 333 * 0.001)
    assert c.efectivo == pytest.approx(1000 - 3 * 333 * 1.001)
    assert c.cantidad == pytest.approx(3.0)


def test_el_deslizamiento_siempre_empeora_el_precio():
    c = Cuenta(efectivo=1000.0)
    compra = comprar(c, 100.0, 500.0, F, 0.0, deslizamiento_bps=10)
    assert compra.precio == pytest.approx(100.1)
    venta = vender(c, 100.0, F, 0.0, deslizamiento_bps=10)
    assert venta.precio == pytest.approx(99.9)


def test_no_compra_por_encima_del_efectivo_sin_apalancamiento():
    c = Cuenta(efectivo=100.0)
    with pytest.raises(OrdenRechazada, match='[Ss]aldo insuficiente'):
        comprar(c, 10.0, 100.01, F, 0.0, 0)
    assert c.efectivo == 100.0 and c.cantidad == 0.0


def test_el_efectivo_nunca_queda_negativo_al_comprar_todo_con_comision():
    c = Cuenta(efectivo=1000.0)
    comprar(c, 7.0, 1000.0, F, 0.001, 5)
    assert c.efectivo >= 0


def test_rechaza_orden_menor_al_minimo_del_par():
    c = Cuenta(efectivo=1000.0)
    with pytest.raises(OrdenRechazada, match='mínimo'):
        comprar(c, 100.0, 0.5, F, 0.0, 0)
    assert c.cantidad == 0.0


def test_rechaza_cantidad_que_no_alcanza_un_paso():
    c = Cuenta(efectivo=1000.0)
    with pytest.raises(OrdenRechazada, match='paso'):
        comprar(c, 100_000.0, 50.0, Filtros(paso_cantidad=0.001, minimo_quote=1.0), 0.0, 0)


def test_rechaza_datos_no_finitos_o_precio_no_positivo():
    c = Cuenta(efectivo=1000.0)
    with pytest.raises(OrdenRechazada, match='[Pp]recio'):
        comprar(c, float('nan'), 100.0, F, 0.0, 0)
    with pytest.raises(OrdenRechazada, match='[Pp]recio'):
        comprar(c, 0.0, 100.0, F, 0.0, 0)


def test_no_hay_ventas_en_corto():
    c = Cuenta(efectivo=1000.0)
    with pytest.raises(OrdenRechazada, match='posición'):
        vender(c, 100.0, F, 0.0, 0)
    assert c.cantidad == 0.0


def test_venta_cierra_toda_la_posicion_y_calcula_resultado_neto():
    c = Cuenta(efectivo=1000.0)
    comprar(c, 100.0, 500.0, F, 0.001, 0)
    q = c.cantidad
    e = vender(c, 110.0, F, 0.001, 0)
    assert c.cantidad == 0.0 and c.stop is None and c.objetivo is None
    assert e.resultado == pytest.approx(q * 110 * 0.999 - q * 100 * 1.001)
    assert c.efectivo == pytest.approx(1000 - q * 100 * 1.001 + q * 110 * 0.999)
    assert c.costos == pytest.approx(q * 100 * 0.001 + q * 110 * 0.001)


def test_patrimonio_es_efectivo_mas_valor_de_la_posicion():
    c = Cuenta(efectivo=500.0, cantidad=2.0, precio_medio=100.0)
    assert patrimonio(c, 150.0) == 800.0


def posicion(stop=90.0, objetivo=120.0):
    c = Cuenta(efectivo=500.0)
    comprar(c, 100.0, 500.0, F, 0.0, 0)
    c.stop, c.objetivo = stop, objetivo
    return c


def test_stop_ejecuta_al_precio_del_stop_si_lo_toca():
    c = posicion()
    e = revisar_stops(c, dict(open=95.0, high=96.0, low=89.0, close=92.0), F, 0.0, 0)
    assert e.motivo == 'stop' and e.precio == 90.0 and c.cantidad == 0.0


def test_stop_con_hueco_ejecuta_a_la_apertura_que_es_peor():
    c = posicion()
    e = revisar_stops(c, dict(open=80.0, high=85.0, low=78.0, close=82.0), F, 0.0, 0)
    assert e.motivo == 'stop' and e.precio == 80.0


def test_objetivo_ejecuta_al_precio_objetivo():
    c = posicion()
    e = revisar_stops(c, dict(open=110.0, high=125.0, low=108.0, close=118.0), F, 0.0, 0)
    assert e.motivo == 'objetivo' and e.precio == 120.0


def test_si_toca_stop_y_objetivo_en_la_misma_vela_se_asume_lo_peor():
    c = posicion()
    e = revisar_stops(c, dict(open=100.0, high=130.0, low=80.0, close=100.0), F, 0.0, 0)
    assert e.motivo == 'stop'


def test_sin_tocar_niveles_no_hay_ejecucion():
    c = posicion()
    assert revisar_stops(c, dict(open=100.0, high=110.0, low=95.0, close=105.0), F, 0.0, 0) is None
    assert c.cantidad > 0


def test_sin_posicion_no_hay_stops():
    assert revisar_stops(Cuenta(efectivo=1.0), dict(open=1, high=1, low=1, close=1), F, 0.0, 0) is None


def test_trailing_solo_sube_nunca_baja():
    c = posicion(stop=90.0, objetivo=None)
    mover_trailing(c, cierre=110.0, atr_abs=5.0, k=2.0)
    assert c.stop == 100.0
    mover_trailing(c, cierre=102.0, atr_abs=5.0, k=2.0)
    assert c.stop == 100.0


def test_comprar_recorriendo_el_libro_da_el_precio_medio():
    precio, cubierto = precio_por_libro([(100.0, 1.0), (101.0, 1.0)], monto_quote=150.0)
    assert cubierto and precio == pytest.approx(150.0 / (1 + 50.0 / 101.0))


def test_vender_recorriendo_el_libro_da_el_precio_medio():
    precio, cubierto = precio_por_libro([(100.0, 1.0), (99.0, 2.0)], cantidad=2.0)
    assert cubierto and precio == pytest.approx(99.5)


def test_libro_insuficiente_se_informa_y_el_resto_va_al_peor_precio_visible():
    precio, cubierto = precio_por_libro([(100.0, 1.0), (98.0, 1.0)], cantidad=3.0)
    assert not cubierto and precio == pytest.approx((100 + 98 + 98) / 3)
    assert precio_por_libro([], monto_quote=10.0) == (None, False)


def test_punto_de_equilibrio_sube_el_stop_a_la_entrada_mas_costos_al_ganar_lo_pedido():
    c = Cuenta(efectivo=0.0, cantidad=1.0, precio_medio=100.0, stop=90.0, objetivo=120.0, atr_abs=5.0)
    mover_trailing(c, 104.0, 5.0, 2.0, proteger_atr=1.0, costo=0.002)
    assert c.stop == pytest.approx(94.0)  # aún no gana 1 ATR: solo el stop móvil
    mover_trailing(c, 105.0, 5.0, 2.0, proteger_atr=1.0, costo=0.002)
    assert c.stop == pytest.approx(100.2)  # ganó 1 ATR: entrada más costos, ya no termina en pérdida salvo un salto
    mover_trailing(c, 101.0, 5.0, 2.0, proteger_atr=1.0, costo=0.002)
    assert c.stop == pytest.approx(100.2)  # nunca baja
    apagado = Cuenta(efectivo=0.0, cantidad=1.0, precio_medio=100.0, stop=90.0, objetivo=120.0, atr_abs=5.0)
    mover_trailing(apagado, 105.0, 5.0, 2.0)
    assert apagado.stop == pytest.approx(95.0)
