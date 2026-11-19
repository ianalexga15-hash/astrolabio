"""Energía del equipo: si está enchufado, cuánta batería queda y la petición para no suspenderse mientras corre el bot."""
import ctypes


class _Estado(ctypes.Structure):
    _fields_ = [('ACLineStatus', ctypes.c_ubyte), ('BatteryFlag', ctypes.c_ubyte), ('BatteryLifePercent', ctypes.c_ubyte),
                ('SystemStatusFlag', ctypes.c_ubyte), ('BatteryLifeTime', ctypes.c_ulong), ('BatteryFullLifeTime', ctypes.c_ulong)]


def mantener_despierto(kernel32=None):
    """Pide a Windows no suspender el equipo mientras corre el servidor. La pantalla sí puede apagarse y, al cerrar el proceso, Windows lo olvida."""
    k = kernel32 or ctypes.windll.kernel32
    return bool(k.SetThreadExecutionState(0x80000000 | 0x00000001))  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED


def estado_energia(leer=None):
    """Corriente y batería según Windows. None cuando no se sabe: nunca se inventa el dato."""
    desconocido = dict(conectada=None, bateria=None)
    if leer is None:
        if not hasattr(ctypes, 'windll'):
            return desconocido
        leer = lambda e: ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(e))  # noqa: E731
    estado = _Estado()
    if not leer(estado):
        return desconocido
    bateria = estado.BatteryLifePercent
    return dict(conectada={0: False, 1: True}.get(estado.ACLineStatus), bateria=bateria if bateria <= 100 else None)
