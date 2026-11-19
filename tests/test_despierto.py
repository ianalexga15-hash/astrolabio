"""Opción para que Windows no suspenda el equipo mientras el servidor corre."""
from bot import config, energia
from tests.test_api import app_cliente, entrar, raiz  # noqa: F401


class Kernel32:
    def __init__(self):
        self.banderas = []

    def SetThreadExecutionState(self, banderas):
        self.banderas.append(banderas)
        return 0x80000000


def test_pide_mantener_el_equipo_despierto_sin_forzar_la_pantalla():
    k = Kernel32()
    assert energia.mantener_despierto(k) is True
    assert k.banderas == [0x80000000 | 0x00000001]  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED, sin ES_DISPLAY_REQUIRED


def test_la_opcion_viene_apagada_y_se_activa_con_bot_sin_suspender(monkeypatch):
    claves = dict(BOT_ADMIN_KEY='a' * 20, BOT_LLM_KEY='b' * 20)
    monkeypatch.setattr(config, 'leer_env', lambda: claves)
    assert config.cargar_ajustes().sin_suspender is False
    monkeypatch.setattr(config, 'leer_env', lambda: claves | dict(BOT_SIN_SUSPENDER='1'))
    assert config.cargar_ajustes().sin_suspender is True


def test_estado_de_energia_lee_corriente_y_bateria_de_windows():
    def falso(estado):
        estado.ACLineStatus, estado.BatteryLifePercent = 0, 41
        return 1
    assert energia.estado_energia(falso) == dict(conectada=False, bateria=41)


def test_estado_de_energia_desconocido_no_inventa_datos():
    def falso(estado):
        estado.ACLineStatus, estado.BatteryLifePercent = 255, 255
        return 1
    assert energia.estado_energia(falso) == dict(conectada=None, bateria=None)
    assert energia.estado_energia(lambda estado: 0) == dict(conectada=None, bateria=None)


def test_sistema_informa_la_energia_y_si_se_pide_no_suspender(raiz):
    c, _ = app_cliente(raiz)
    entrar(c)
    energia = c.get('/api/sistema').json()['energia']
    assert set(energia) == {'conectada', 'bateria', 'sin_suspender'} and energia['sin_suspender'] is False
