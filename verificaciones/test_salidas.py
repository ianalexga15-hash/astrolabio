import threading
from concurrent.futures import wait

from bot.agent import Agente
from bot.salidas import ReflejoProtegido
from bot.events import NULO
from bot.paper import Cuenta
from bot.store import Store
from tests.test_agent import Modelo, Proponente
from tests.test_reflejo import preparar, libro, SYM


def abierto(tmp_path):
    store=Store(tmp_path/'salidas.sqlite3')
    m,a,_=preparar(store)
    a.cuenta=Cuenta(efectivo=100,cantidad=2,precio_medio=100,costo_entrada=200,stop=95,objetivo=110,entrada_ms=m.ahora()-10000)
    store.guardar_cuenta(a.run_id,a.cuenta)
    m.profundidad=lambda simbolo: {'bids':[(94,20)],'asks':[(95,20)]}
    r=ReflejoProtegido({SYM:a},NULO)
    return store,m,a,r


def test_stop_cierra_una_vez_y_persiste(tmp_path):
    store,m,a,r=abierto(tmp_path)
    r.barrer(libro(94,m=m),m.ahora())
    wait(list(r.trabajos.values()))
    assert a.cuenta.cantidad==0
    r.barrer(libro(94,m=m),m.ahora())
    ventas=[x for x in store.ordenes(a.run_id) if x['lado']=='vender']
    assert len(ventas)==1 and ventas[0]['estado']=='ejecutada'
    assert r.salidas[SYM]['estado']=='cerrada_paper'
    r.cerrar()


def test_no_finge_liquidez_y_recupera_pendiente_tras_reinicio(tmp_path):
    store,m,a,r=abierto(tmp_path)
    m.profundidad=lambda simbolo: {'bids':[(94,.01)],'asks':[]}
    r.barrer(libro(94,m=m),m.ahora())
    wait(list(r.trabajos.values()))
    assert a.cuenta.cantidad==2 and not [o for o in store.ordenes(a.run_id) if o['lado']=='vender']
    assert r.salidas[SYM]['estado']=='pendiente'
    r.cerrar()
    r=ReflejoProtegido({SYM:a},NULO)
    m.profundidad=lambda simbolo: {'bids':[(100,20)],'asks':[]}
    # Aunque el precio recupera, el stop disparado sigue pendiente hasta cerrar.
    r.barrer(libro(100,m=m),m.ahora())
    wait(list(r.trabajos.values()))
    assert a.cuenta.cantidad==0
    r.cerrar()


def test_lock_ocupado_no_frena_y_detener_no_vende(tmp_path):
    store,m,a,r=abierto(tmp_path)
    dentro=threading.Event(); soltar=threading.Event()
    def ocupar():
        with a._lock:
            dentro.set(); soltar.wait(3)
    hilo=threading.Thread(target=ocupar); hilo.start(); dentro.wait(1)
    try:
        r.barrer(libro(94,m=m),m.ahora())
        assert r.salidas[SYM]['estado']=='esperando_agente'
        assert a.cuenta.cantidad==2
    finally:
        soltar.set(); hilo.join()
    a.detener()
    r.barrer(libro(94,m=m),m.ahora())
    assert a.cuenta.cantidad==2
    assert r.salidas[SYM]['estado']=='desactivada'
    r.cerrar()


def test_precio_atrasado_no_cierra(tmp_path):
    _,m,a,r=abierto(tmp_path)
    r.barrer(libro(94,m=m,ts=m.ahora()-100000),m.ahora())
    assert a.cuenta.cantidad==2
    assert r.salidas[SYM]['estado']=='dato_atrasado'
    r.cerrar()


def test_fallo_un_activo_no_aborta_otra_salida(tmp_path):
    from dataclasses import replace
    store,m,a,r=abierto(tmp_path)
    otra=tmp_path/'otro'; otra.mkdir()
    _,m2,b,r2=abierto(otra)
    r.cerrar(); r2.cerrar()
    b.limites=replace(b.limites,simbolo='ETHUSDT')
    def fallar(s): raise RuntimeError('fallo simulado')
    m.profundidad=fallar
    r=ReflejoProtegido({SYM:a,'ETHUSDT':b},NULO)
    precios=libro(94,m=m); precios['ETHUSDT']=precios[SYM].copy()
    r.barrer(precios,m.ahora())
    wait(list(r.trabajos.values()))
    assert a.cuenta.cantidad==2 and b.cuenta.cantidad==0
    r.cerrar()


def test_objetivo_respeta_espera_y_stop_tiene_prioridad(tmp_path):
    from dataclasses import replace
    store,m,a,r=abierto(tmp_path)
    a.limites=replace(a.limites,espera_max_min=30,comision_espera=0.)
    m.profundidad=lambda s: {'bids':[(111,.1),(109,20)],'asks':[]}
    r.barrer(libro(112,m=m),m.ahora())
    assert a.cuenta.cantidad==2  # no inventar fill límite por debajo de 110
    m.profundidad=lambda s: {'bids':[(94,20)],'asks':[]}
    r.barrer(libro(94,m=m),m.ahora())
    assert a.cuenta.cantidad==0
    assert store.ordenes(a.run_id)[-1]['motivo']=='stop'
    r.cerrar()


def venta_diaria_sin_libro(tmp_path):
    """La decisión diaria pide vender y el libro no cubre la posición: la orden queda rechazada."""
    store,m,a,r=abierto(tmp_path)
    a.cuenta.stop,a.cuenta.objetivo=1e-9,1e12  # solo la decisión diaria pide vender
    a.proponente=Proponente('vender')
    m.profundidad=lambda s: {'bids':[(1.0,.01)],'asks':[]}
    m.avanzar()
    assert a.tick()['accion']=='vender' and a.cuenta.cantidad==2
    return store,m,a,r


def ventas(store,a):
    return [o for o in store.ordenes(a.run_id) if o['lado']=='vender' and o['estado']=='ejecutada']


def test_venta_diaria_rechazada_se_reintenta_en_cada_barrido_hasta_vender(tmp_path):
    store,m,a,r=venta_diaria_sin_libro(tmp_path)
    precio=m.ticker(SYM)
    r.barrer(libro(precio,m=m),m.ahora())
    wait(list(r.trabajos.values()))
    assert a.cuenta.cantidad==2 and r.salidas[SYM]['estado']=='pendiente'
    m.profundidad=lambda s: {'bids':[(precio,20)],'asks':[]}
    r.barrer(libro(precio,m=m),m.ahora())
    wait(list(r.trabajos.values()))
    assert a.cuenta.cantidad==0 and [v['motivo'] for v in ventas(store,a)]==['decision']
    r.cerrar()


def test_venta_diaria_pendiente_sobrevive_a_un_reinicio(tmp_path):
    store,m,a,r=venta_diaria_sin_libro(tmp_path)
    r.cerrar()
    b=Agente(store=store,mercado=m,modelo=Modelo(),proponente=Proponente('mantener'),limites=a.limites,run_id=a.run_id,ahora=m.ahora,modo_reflejo=True)
    r=ReflejoProtegido({SYM:b},NULO)
    precio=m.ticker(SYM)
    m.profundidad=lambda s: {'bids':[(precio,20)],'asks':[]}
    r.barrer(libro(precio,m=m),m.ahora())
    wait(list(r.trabajos.values()))
    assert b.cuenta.cantidad==0 and [v['motivo'] for v in ventas(store,b)]==['decision']
    r.cerrar()


def test_venta_diaria_pendiente_se_olvida_si_la_posicion_se_cierra_por_otra_via(tmp_path):
    store,m,a,r=venta_diaria_sin_libro(tmp_path)
    a.cerrar_posicion(precio=m.ticker(SYM))
    r.barrer(libro(m.ticker(SYM),m=m),m.ahora())
    assert a.salida_pendiente is None
    assert store._una('SELECT 1 x FROM salidas_pendientes WHERE run=?',a.run_id) is None
    assert [v['motivo'] for v in ventas(store,a)]==['manual']
    r.cerrar()
