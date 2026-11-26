"""Controles deterministas. El LLM propone; aquí se decide si se ejecuta. El LLM no puede cambiar nada de esto."""
import math
from dataclasses import dataclass, field, fields

from bot.model import FILTROS
from bot.paper import Cuenta

ACCIONES = ('comprar', 'mantener', 'vender')


@dataclass(frozen=True)
class Limites:
    simbolo: str
    capital_inicial: float
    comision: float
    deslizamiento_bps: float
    exposicion_max: float
    perdida_diaria_max: float
    drawdown_max: float
    antiguedad_max_horas: float
    riesgo_por_operacion: float
    stop_atr: float
    objetivo_atr: float
    trailing_atr: float
    spread_max_bps: float = 25.0
    extension_max_atr: float = 1.5
    edad_precio_max_s: float = 5.0
    espera_max_min: float = 0.0  # minutos que una compra espera en el libro sin comisión; 0 compra al instante
    comision_espera: float = 0.0  # comisión de la orden que espera en el libro (maker)
    comision_por_par: tuple = ()  # (símbolo, comisión) reales de MEXC para la cuenta; un par sin dato usa `comision`
    maquina_tiempo: bool = False  # antes de autorizar una compra, repasa los próximos días y no compra si en promedio pierde
    max_compras_dia: float = 0  # compras nuevas que la cartera autoriza por vela diaria entre todos los activos; 0 es sin tope
    proteger_atr: float = 0.0  # al ganar esta cantidad de ATR, el stop sube a la entrada más costos; 0 lo apaga
    pausa_tras_perdida_dias: float = 0.0  # tras un stop que cerró perdiendo, días sin comprar ese activo; 0 la apaga
    objetivo_pct: float = 0.0  # meta por operación (desde 2026-11-13): vende a la entrada × (1 + esto + comisión del par); 0 usa objetivo_atr
    filtro_minimo: str = ''  # decisión de Alex (2026-11-13): filtro técnico si la regla de VA no trae ninguno; '' lo apaga

    def __post_init__(self):
        object.__setattr__(self, 'comision_por_par', tuple((str(s), float(c)) for s, c in self.comision_por_par))

    @property
    def comision_efectiva(self):
        return dict(self.comision_por_par).get(self.simbolo, self.comision)

    def precio_objetivo(self, entrada, atr_abs):
        """Precio de venta con ganancia. Lo usan el bot al comprar y la máquina del tiempo, para que repase las mismas salidas."""
        if self.objetivo_pct:
            return entrada * (1 + self.objetivo_pct + self.comision_efectiva)
        return entrada + self.objetivo_atr * atr_abs

    def validar(self):
        for f in fields(self):  # NaN e infinito pasan cualquier comparación con cero: se rechazan antes
            v = getattr(self, f.name)
            if isinstance(v, float) and not math.isfinite(v) or f.name == 'comision_por_par' and not all(math.isfinite(c) for _, c in v):
                raise ValueError(f'{f.name} debe ser un número finito.')
        if not 0 < self.exposicion_max <= 1:
            raise ValueError('exposicion_max debe estar entre 0 y 1: sin apalancamiento.')
        if self.capital_inicial <= 0:
            raise ValueError('capital_inicial debe ser positivo.')
        if min(self.comision, self.deslizamiento_bps, self.comision_espera, self.espera_max_min) < 0 or any(c < 0 for _, c in self.comision_por_par):
            raise ValueError('Las comisiones, el deslizamiento y la espera no pueden ser negativos.')
        for nombre in ('perdida_diaria_max', 'drawdown_max'):
            if not 0 < getattr(self, nombre) < 1:
                raise ValueError(f'{nombre} debe estar entre 0 y 1.')
        if not 0 < self.riesgo_por_operacion <= 0.2:
            raise ValueError('riesgo_por_operacion debe estar entre 0 y 0.2.')
        for nombre in ('antiguedad_max_horas', 'stop_atr', 'objetivo_atr', 'trailing_atr', 'spread_max_bps', 'extension_max_atr', 'edad_precio_max_s'):
            if getattr(self, nombre) <= 0:
                raise ValueError(f'{nombre} debe ser positivo.')
        if not isinstance(self.maquina_tiempo, bool):
            raise ValueError('maquina_tiempo debe ser verdadero o falso.')
        v = self.max_compras_dia
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or v != int(v):
            raise ValueError('max_compras_dia debe ser un entero mayor o igual a 0.')
        if not 0 <= self.proteger_atr < self.objetivo_atr:
            raise ValueError('proteger_atr debe ir de 0 a menos que objetivo_atr: 0 lo apaga.')
        if self.pausa_tras_perdida_dias < 0:
            raise ValueError('pausa_tras_perdida_dias no puede ser negativa: 0 la apaga.')
        if not 0 <= self.objetivo_pct < 1:
            raise ValueError('objetivo_pct debe ir de 0 a menos de 1 (0.13 es 13 %): 0 usa el objetivo en ATR.')
        if self.filtro_minimo == 'ninguno' or self.filtro_minimo not in ('', *FILTROS):
            raise ValueError(f"filtro_minimo debe ser un filtro técnico ({', '.join(f for f in FILTROS if f != 'ninguno')}) o '' para apagarlo.")
        return self


@dataclass(frozen=True)
class Contexto:
    estado: str
    simbolo: str
    edad_horas: float
    senal: bool
    cuenta: Cuenta
    precio: float
    atr_abs: float
    patrimonio: float
    patrimonio_inicio_dia: float
    patrimonio_maximo: float
    maquina: dict | None = None  # resultado de maquina_tiempo.repasar; el reflejo no lo trae y no bloquea por él
    compras_hoy: int | None = None  # compras ya autorizadas en esta vela por la cartera; tampoco lo trae el reflejo
    dias_desde_perdida: float | None = None  # días desde el último stop que cerró perdiendo; None si no hubo o no se consultó


@dataclass(frozen=True)
class Decision:
    aprobada: bool
    accion: str
    motivos: list = field(default_factory=list)
    monto_quote: float = 0.0
    stop: float | None = None
    objetivo: float | None = None
    bloquear: bool = False


def _rechazo(*motivos, bloquear=False):
    return Decision(False, 'mantener', list(motivos), bloquear=bloquear)


def evaluar(propuesta, ctx, limites):
    if propuesta not in ACCIONES:
        return _rechazo(f'Acción no permitida: {propuesta}.')
    if ctx.simbolo != limites.simbolo:
        return _rechazo(f'Símbolo no permitido: {ctx.simbolo}.')
    if propuesta == 'mantener':
        return Decision(True, 'mantener')
    if ctx.estado != 'activo':
        return _rechazo(f'El bot está {ctx.estado}: no se envían órdenes nuevas.')
    if not math.isfinite(ctx.edad_horas) or ctx.edad_horas < 0:
        return _rechazo('Edad del dato no válida: no se puede confirmar su vigencia.')
    if ctx.edad_horas > limites.antiguedad_max_horas:
        return _rechazo(f'Dato atrasado: {ctx.edad_horas:.1f} h supera {limites.antiguedad_max_horas} h.')
    en_posicion = ctx.cuenta.cantidad > 0
    if propuesta == 'vender':
        if not en_posicion:
            return _rechazo('No hay posición que vender; sin ventas en corto.')
        return Decision(True, 'vender')

    if en_posicion:
        return _rechazo('Ya hay una posición abierta; no se recompra.')
    # Fallar de forma cerrada antes de divisiones y min(): NaN puede eludir
    # comparaciones o dejar una orden aparentemente válida. Solo entradas;
    # una salida no depende de los datos utilizados para dimensionar compras.
    valores = (ctx.precio, ctx.patrimonio, ctx.patrimonio_inicio_dia,
               ctx.patrimonio_maximo, ctx.cuenta.efectivo)
    if not all(math.isfinite(v) and v > 0 for v in valores):
        return _rechazo('Precio, patrimonio y efectivo deben ser positivos y finitos para comprar.')
    caida = 1 - ctx.patrimonio / ctx.patrimonio_maximo
    if caida >= limites.drawdown_max:
        return _rechazo(f'Límite de caída máxima alcanzado ({caida:.1%}).', bloquear=True)
    perdida = 1 - ctx.patrimonio / ctx.patrimonio_inicio_dia
    if perdida >= limites.perdida_diaria_max:
        return _rechazo(f'Límite de pérdida diaria alcanzado ({perdida:.1%}).')
    if not ctx.senal:
        return _rechazo('El modelo no da señal de compra; el LLM no puede abrir posición por su cuenta.')
    if not (math.isfinite(ctx.atr_abs) and ctx.atr_abs > 0):
        return _rechazo('ATR no válido: no se puede dimensionar la posición.')
    if limites.max_compras_dia and ctx.compras_hoy is not None and ctx.compras_hoy >= limites.max_compras_dia:
        return _rechazo(f'Tope diario: la cartera ya autorizó {ctx.compras_hoy} compras en esta vela; el máximo es {limites.max_compras_dia:g}.')
    if limites.pausa_tras_perdida_dias and ctx.dias_desde_perdida is not None and ctx.dias_desde_perdida < limites.pausa_tras_perdida_dias:
        return _rechazo(f'Pausa tras pérdida: el último stop de este activo cerró perdiendo hace {ctx.dias_desde_perdida:g} día(s); '
                        f'espera {limites.pausa_tras_perdida_dias:g}.')
    m = ctx.maquina
    if limites.maquina_tiempo and m is not None and not math.isfinite(m.get('r_medio', math.nan)):
        return _rechazo('Máquina del tiempo: sin un repaso válido de esta compra (falta historia o el resultado no es un número); no se autoriza.')
    if limites.maquina_tiempo and m is not None and m['r_medio'] <= 0:
        return _rechazo(f'Máquina del tiempo: repitiendo los próximos días con sus últimas velas, esta compra llega primero al objetivo '
                        f'{m["objetivo"] * 100:.0f} % de las veces y al stop {m["stop"] * 100:.0f} %; en promedio deja {m["r_medio"]:+.2f} R.')
    distancia = limites.stop_atr * ctx.atr_abs
    stop = ctx.precio - distancia
    objetivo = limites.precio_objetivo(ctx.precio, ctx.atr_abs)
    if not (math.isfinite(stop) and math.isfinite(objetivo) and 0 < stop < ctx.precio < objetivo):
        return _rechazo('Niveles de salida no válidos: se requiere 0 < stop < precio < objetivo.')
    por_riesgo = limites.riesgo_por_operacion * ctx.patrimonio / distancia * ctx.precio
    monto = min(por_riesgo, limites.exposicion_max * ctx.patrimonio, ctx.cuenta.efectivo)
    if not math.isfinite(monto) or monto <= 0:
        return _rechazo('Monto de compra no válido.')
    return Decision(True, 'comprar', monto_quote=monto, stop=stop, objetivo=objetivo)
