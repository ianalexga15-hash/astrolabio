import { describe, expect, it } from 'vitest';
import {
  centroDeGalaxia, conectadas, cuentaAtras, filtrarNotas, indexar100, type Nota, pctSigno, polvoDeGalaxia, posicionesUniverso, precio, proyectar, rutasDeEsquema, sma, usd, validarNuevaClave, avisoEnergia,
  avisoDetener, conexionActivos, detalleDeError, estadoMexc, horaLocal, idsNuevos, interruptor, metricasOperaciones, puntosNuevos, registrarCambio, resumenHistorial, tonoAltura, valorCuenta,
  limiteVacio, sumarSegundo, ejeX, avisoDetenido, comprasPosibles, bollinger, rsi, macd, ema, atr, volatilidad, unirVelasDelDia,
} from './logica';

describe('vela del día en vivo', () => {
  const DIA = 86_400_000;
  const vela = (dia: number, close: number) => ({ open_time: dia * DIA, open: 10, high: 12, low: 9, close });

  it('suma solo las velas de MEXC posteriores a las guardadas y cierra la de hoy al precio en vivo', () => {
    const serie = unirVelasDelDia([vela(1, 10), vela(2, 11)], [vela(1, 99), vela(2, 99), vela(3, 11.5)], 13, 3 * DIA);
    expect(serie.map((v) => v.close)).toEqual([10, 11, 13]);
    expect(serie[2]).toMatchObject({ open: 10, high: 13, low: 9 });
    expect(unirVelasDelDia([vela(1, 10)], [vela(2, 11)], 8, 2 * DIA)[1]).toMatchObject({ high: 12, low: 8, close: 8 });
  });

  it('deja la última vela como está si no es la de hoy o no hay precio en vivo', () => {
    const cerradas = [vela(1, 10), vela(2, 11)];
    expect(unirVelasDelDia(cerradas, null, 13, 3 * DIA)).toEqual(cerradas);
    expect(unirVelasDelDia(cerradas, [vela(3, 11.5)], null, 3 * DIA).map((v) => v.close)).toEqual([10, 11, 11.5]);
  });
});

describe('aviso de bot detenido', () => {
  it('solo avisa con el bot detenido y posiciones abiertas', () => {
    expect(avisoDetenido('detenido', 7)).toContain('7 posiciones abiertas');
    expect(avisoDetenido('detenido', 1)).toContain('1 posición abierta');
    expect(avisoDetenido('detenido', 0)).toBeNull();
    expect(avisoDetenido('activo', 7)).toBeNull();
    expect(avisoDetenido(undefined, 7)).toBeNull();
  });
});

describe('eje de fechas', () => {
  it('pone la fecha ISO como dd/mm/aa y deja igual el resto', () => {
    expect(ejeX('2026-11-04')).toBe('2026-11-04');
    expect(ejeX('  14:05:09')).toBe('14:05:09'); // la serie de 1 s antepone dos espacios
    expect(ejeX('  12')).toBe('12');
  });
});

describe('límites vacíos', () => {
  const campos = [['comision', 'Comisión', 'ayuda'], ['stop_atr', 'Stop de pérdida', 'ayuda']] as const;
  it('nombra el primer campo vacío y deja pasar el cero', () => {
    expect(limiteVacio({ comision: 0, stop_atr: '' }, campos)).toBe('Stop de pérdida');
    expect(limiteVacio({ comision: 0, stop_atr: 2 }, campos)).toBeNull();
  });
});

describe('serie de 1 s', () => {
  it('suma solo barridos nuevos con precio', () => {
    const una = sumarSegundo([], 1_000, 10, 10.1);
    expect(una).toEqual([{ t: 1_000, bid: 10, ask: 10.1 }]);
    expect(sumarSegundo(una, 1_000, 11, 11.1)).toBe(una); // el mismo barrido leído dos veces
    expect(sumarSegundo(una, 900, 11, 11.1)).toBe(una);
    expect(sumarSegundo(una, 2_000, null, 11.1)).toBe(una);
    expect(sumarSegundo(una, 2_000, 11, Number.NaN)).toBe(una);
    expect(sumarSegundo(una, 2_000, 11, 11.1)).toHaveLength(2);
  });

  it('conserva solo los últimos 15 minutos', () => {
    let serie: { t: number; bid: number; ask: number }[] = [];
    for (let t = 0; t <= 20 * 60_000; t += 1_000) serie = sumarSegundo(serie, t, 1, 1);
    expect(serie).toHaveLength(900);
    expect(serie[0].t).toBe(20 * 60_000 - 899_000);
  });
});

const nota = (id: string, galaxia = 'Datos', extra: Partial<Nota> = {}): Nota => ({
  id, titulo: id, origen: 'claude', tipo: 'Código', galaxia, fuente: '', fecha: '2026-11-05', cuerpo: 'texto', ...extra,
});

describe('formatos', () => {
  it('no inventa valores cuando falta el dato', () => {
    expect(usd(null)).toBe('sin dato');
    expect(pctSigno(Number.NaN)).toBe('sin dato');
  });
  it('muestra el signo positivo', () => {
    expect(pctSigno(0.0123)).toBe('+1.23 %');
    expect(pctSigno(-0.5, 0)).toBe('-50 %');
  });
  it('cuenta atrás nunca es negativa', () => {
    expect(cuentaAtras(3_661_000)).toBe('01:01:01');
    expect(cuentaAtras(-5)).toBe('00:00:00');
  });
});

describe('precio', () => {
  it('ajusta los decimales a la escala del activo', () => {
    expect(precio(80498.631)).toBe('80,498.63');
    expect(precio(0.00001234)).toBe('0.00001234');
    expect(precio(null)).toBe('sin dato');
  });
});

describe('series', () => {
  it('sma deja vacíos los primeros valores', () => {
    expect(sma([1, 2, 3, 4], 2)).toEqual([null, 1.5, 2.5, 3.5]);
  });
  it('indexar100 parte de 100', () => {
    expect(indexar100([50, 75])).toEqual([100, 150]);
    expect(indexar100([])).toEqual([]);
  });
});

describe('universo', () => {
  const notas = [nota('a'), nota('b'), nota('c', 'Riesgo'), nota('d', 'Riesgo'), nota('v', 'Visión')];

  it('da posición finita a cada nota', () => {
    const p = posicionesUniverso(notas);
    expect(p.size).toBe(notas.length);
    for (const q of p.values()) expect(Number.isFinite(q.x + q.y + q.z)).toBe(true);
  });
  it('es determinista', () => {
    expect([...posicionesUniverso(notas).entries()]).toEqual([...posicionesUniverso(notas).entries()]);
  });
  it('las notas de una galaxia quedan más cerca entre sí que de otra galaxia', () => {
    const p = posicionesUniverso(notas);
    const d = (a: string, b: string) => Math.hypot(p.get(a)!.x - p.get(b)!.x, p.get(a)!.y - p.get(b)!.y, p.get(a)!.z - p.get(b)!.z);
    expect(d('a', 'b')).toBeLessThan(d('a', 'c'));
  });
  it('la visión queda en el centro', () => {
    const c = centroDeGalaxia(notas, posicionesUniverso(notas), 'Visión')!;
    expect(Math.hypot(c.x, c.y, c.z)).toBeLessThan(10);
  });
  it('el polvo de una galaxia queda alrededor de su centro', () => {
    const centro = { x: 50, y: -20, z: 10 };
    const polvo = polvoDeGalaxia('Datos', centro, 4, 40);
    expect(polvo).toHaveLength(40);
    for (const p of polvo) expect(Math.hypot(p.x - centro.x, p.y - centro.y, p.z - centro.z)).toBeLessThan(70);
  });
  it('la proyección conserva el centro', () => {
    expect(proyectar({ x: 0, y: 0, z: 0 }, 1, 1)).toEqual({ x: 0, y: 0, z: 0, profundidad: 1 });
  });
  it('filtra por texto, autor y galaxia', () => {
    const lista = [nota('uno', 'Datos', { cuerpo: 'ventanas' }), nota('dos', 'Riesgo', { origen: 'codex' })];
    expect(filtrarNotas(lista, { texto: 'VENTANAS' }).map((n) => n.id)).toEqual(['uno']);
    expect(filtrarNotas(lista, { origen: 'codex' }).map((n) => n.id)).toEqual(['dos']);
    expect(filtrarNotas(lista, { galaxia: 'Datos' }).map((n) => n.id)).toEqual(['uno']);
  });
  it('conectadas solo sigue enlaces reales', () => {
    const lista = [nota('a'), nota('b'), nota('c')];
    expect(conectadas('a', lista, [{ origen: 'b', destino: 'a' }]).map((n) => n.id)).toEqual(['b']);
  });
});

describe('rutasDeEsquema', () => {
  it('lista cada método y ruta del esquema, ordenados, con la primera línea de su descripción', () => {
    const esquema = {
      paths: {
        '/api/radar': { get: { summary: 'Radar', description: 'Radar de la cartera.\nDetalle largo.' } },
        '/api/config': { put: { summary: 'Cambiar Config', description: 'Cambia límites.' }, get: { summary: 'Ver Config' } },
      },
    };
    expect(rutasDeEsquema(esquema)).toEqual([
      { metodo: 'GET', ruta: '/api/config', descripcion: 'Ver Config' },
      { metodo: 'PUT', ruta: '/api/config', descripcion: 'Cambia límites.' },
      { metodo: 'GET', ruta: '/api/radar', descripcion: 'Radar de la cartera.' },
    ]);
  });

  it('sin esquema no inventa rutas', () => {
    expect(rutasDeEsquema(null)).toEqual([]);
    expect(rutasDeEsquema({})).toEqual([]);
  });
});

describe('validarNuevaClave', () => {
  it('pide al menos 10 caracteres sin contar espacios en los extremos', () => {
    expect(validarNuevaClave('corta', 'corta')).toBe('Usa al menos 10 caracteres.');
    expect(validarNuevaClave('   nueve9   ', '   nueve9   ')).toBe('Usa al menos 10 caracteres.');
  });

  it('pide que las dos coincidan y acepta una válida', () => {
    expect(validarNuevaClave('cielo-de-astrolabio', 'cielo-de-astrolabi0')).toBe('Las dos contraseñas no coinciden.');
    expect(validarNuevaClave('cielo-de-astrolabio', 'cielo-de-astrolabio')).toBeNull();
  });

  it('no acepta más de 128 caracteres', () => {
    const larga = 'a'.repeat(129);
    expect(validarNuevaClave(larga, larga)).toBe('Usa como máximo 128 caracteres.');
  });
});

describe('avisoEnergia', () => {
  it('alerta si está con batería y Windows puede suspender el equipo', () => {
    const a = avisoEnergia({ conectada: false, bateria: 41, sin_suspender: false });
    expect(a.alerta).toBe(true);
    expect(a.texto).toContain('41%');
    expect(a.texto).toContain('BOT_SIN_SUSPENDER=1');
  });

  it('enchufado y pidiendo no suspender queda tranquilo', () => {
    expect(avisoEnergia({ conectada: true, bateria: 90, sin_suspender: true }).alerta).toBe(false);
  });

  it('pidiendo no suspender con batería avisa que se gastará', () => {
    const a = avisoEnergia({ conectada: false, bateria: 30, sin_suspender: true });
    expect(a.alerta).toBe(true);
    expect(a.texto).toContain('batería');
  });

  it('sin datos no inventa nada', () => {
    expect(avisoEnergia(null).alerta).toBe(false);
    expect(avisoEnergia({ conectada: null, bateria: null, sin_suspender: false }).texto).toContain('no informó');
  });
});


describe('interruptor del bot', () => {
  it('apagado o en pausa ofrece activar con la ruta iniciar', () => {
    for (const estado of ['detenido', 'pausado', 'bloqueado']) {
      expect(interruptor(estado, true)).toMatchObject({ texto: 'Activar bot', ruta: 'iniciar', espera: 'Activando…' });
    }
  });

  it('activo ofrece desactivar con la ruta detener, nunca apagar la aplicación', () => {
    expect(interruptor('activo', true)).toMatchObject({ texto: 'Desactivar bot', ruta: 'detener', espera: 'Desactivando…' });
  });

  it('sin conexión dice estado desconocido y no permite pulsar', () => {
    const i = interruptor('activo', false);
    expect(i.texto).toBe('Estado desconocido');
    expect(i.ruta).toBeNull();
    expect(interruptor(undefined, true).ruta).toBeNull();
  });

  it('sin modelo no se puede activar y explica por qué', () => {
    const i = interruptor('sin_modelo', true);
    expect(i.ruta).toBeNull();
    expect(i.motivo).toContain('modelo');
  });
});

describe('avisoDetener', () => {
  it('advierte que las posiciones abiertas no se cierran', () => {
    expect(avisoDetener(11)).toBe('Quedan 11 posiciones abiertas. Se detienen compras y ventas automáticas; las posiciones no se cierran.');
    expect(avisoDetener(1)).toBe('Queda 1 posición abierta. Se detienen compras y ventas automáticas; la posición no se cierra.');
  });

  it('sin posiciones no pide confirmación', () => {
    expect(avisoDetener(0)).toBeNull();
    expect(avisoDetener(null)).toBeNull();
  });
});

describe('registrarCambio', () => {
  const inicio = { valor: null, veces: 0, sube: null };

  it('la primera carga no cuenta como cambio', () => {
    expect(registrarCambio(inicio, 101)).toEqual({ valor: 101, veces: 0, sube: null });
  });

  it('un cambio real cuenta y guarda su dirección', () => {
    const a = registrarCambio(inicio, 101);
    const b = registrarCambio(a, 99);
    expect(b).toEqual({ valor: 99, veces: 1, sube: false });
    expect(registrarCambio(b, 100)).toEqual({ valor: 100, veces: 2, sube: true });
  });

  it('el mismo valor no vuelve a animar', () => {
    const a = registrarCambio(registrarCambio(inicio, 'comprar'), 'mantener');
    expect(registrarCambio(a, 'mantener')).toBe(a);
    expect(a.veces).toBe(1);
  });
});

describe('idsNuevos', () => {
  it('la primera carga no marca filas nuevas', () => {
    expect(idsNuevos(null, [3, 2, 1]).size).toBe(0);
  });

  it('solo marca identificadores que no se habían visto', () => {
    expect([...idsNuevos(new Set([1, 2]), [4, 3, 2, 1])]).toEqual([4, 3]);
    expect(idsNuevos(new Set([1, 2]), [2, 1]).size).toBe(0);
  });
});

describe('puntosNuevos', () => {
  it('la primera carga no se anima como si fuera nueva', () => {
    expect(puntosNuevos(null, ['2026-11-04', '2026-11-05'])).toBeNull();
  });

  it('el mismo último punto no es nuevo', () => {
    expect(puntosNuevos('2026-11-05', ['2026-11-04', '2026-11-05'])).toBeNull();
  });

  it('devuelve el último punto conocido cuando llega uno nuevo, también si la ventana se desliza', () => {
    expect(puntosNuevos('2026-11-05', ['2026-11-04', '2026-11-05', '2026-11-06'])).toBe(1);
    expect(puntosNuevos('2026-11-05', ['2026-11-05', '2026-11-06'])).toBe(0);
  });

  it('si el punto anterior ya no está, no inventa un tramo nuevo', () => {
    expect(puntosNuevos('2026-10-01', ['2026-11-04', '2026-11-05'])).toBeNull();
  });
});

describe('valorCuenta', () => {
  it('valora en USDT con el precio de compra del radar y separa lo que no tiene precio', () => {
    const v = valorCuenta([{ activo: 'USDT', libre: 100, bloqueado: 0 }, { activo: 'BTC', libre: 0.001, bloqueado: 0.001 }, { activo: 'XYZ', libre: 5, bloqueado: 0 }], { BTCUSDT: 70000 });
    expect(v.total).toBeCloseTo(240);
    expect(v.filas.map((f) => f.valor)).toEqual([100, 140, null]);
    expect(v.sinPrecio).toEqual(['XYZ']);
  });
});

describe('indicadores iguales a los de bot/features.py', () => {
  // Cierres y valores esperados salidos de bot/features.add_indicators con estos mismos 60 cierres
  const CIERRES = [100.4, 102.2106, 104.9089, 107.9759, 109.1695, 107.5852, 104.9415, 102.1603, 99.8685, 99.8479, 102.2107, 105.0521, 107.4553, 108.8742, 107.7222,
    104.4594, 101.611, 99.9844, 99.7106, 101.7022, 105.1131, 107.5324, 108.2633, 107.4383, 104.5573, 101.1081, 99.5357, 99.8897, 101.5423, 104.616, 107.6184, 108.2422,
    106.7586, 104.3149, 101.1919, 99.0467, 99.5456, 101.7685, 104.3987, 107.1023, 108.3259, 106.6364, 103.6187, 101.0249, 99.1363, 99.0769, 101.5107, 104.6393,
    106.7897, 107.781, 106.7112, 103.4224, 100.3675, 99.0653, 99.1753, 101.043, 104.4369, 107.0038, 107.3537, 106.1589];

  it('Bollinger: SMA20 ± 2 desviaciones poblacionales', () => {
    const b = bollinger(CIERRES);
    expect(b[18]).toBeNull();
    expect(b[40]?.media).toBeCloseTo(104.13984, 6);
    expect(b[40]?.sup).toBeCloseTo(110.7510269595, 6);
    expect(b[59]?.inf).toBeCloseTo(97.1623301906, 6);
  });

  it('RSI de Wilder que arranca con la media de los primeros 14 cambios; 50 sin movimiento', () => {
    const r = rsi(CIERRES);
    expect(r[13]).toBeNull();
    expect(r[40]).toBeCloseTo(59.2906156223, 6);
    expect(r[59]).toBeCloseTo(55.1259846221, 6);
    expect(rsi(Array(20).fill(5))[19]).toBe(50);
  });

  it('EMA 20, ATR 14 de Wilder y volatilidad muestral de 20 días', () => {
    const e = ema(CIERRES);
    expect(e[18]).toBeNull();
    expect(e[40]).toBeCloseTo(104.0138573034, 6);
    expect(e[59]).toBeCloseTo(103.8785464468, 6);
    const a = atr(CIERRES.map((c) => ({ high: c * 1.01, low: c * 0.99, close: c })));
    expect(a[12]).toBeNull();
    expect(a[40]).toBeCloseTo(3.075799093, 6);
    expect(a[59]).toBeCloseTo(3.0331911186, 6);
    const v = volatilidad(CIERRES);
    expect(v[19]).toBeNull();
    expect(v[40]).toBeCloseTo(0.021440509104, 9);
    expect(v[59]).toBeCloseTo(0.021180638543, 9);
  });

  it('MACD 12/26/9 con el histograma en precio y sin valor hasta tener la señal', () => {
    const m = macd(CIERRES);
    expect(m[32]).toBeNull();
    expect(m[40]?.hist).toBeCloseTo(0.3676407903, 6);
    expect(m[59]?.hist).toBeCloseTo(0.4522867831, 6);
  });
});

describe('comprasPosibles', () => {
  it('cuenta las compras de monto completo que caben en el USDT libre y en el cupo que queda del tope', () => {
    expect(comprasPosibles(40.04, 0, 50, 10)).toBe(4); // manda el saldo
    expect(comprasPosibles(100, 0, 50, 10)).toBe(5); // manda el tope
    expect(comprasPosibles(100, 45, 50, 10)).toBe(0); // quedan 5 de cupo: no alcanza para una orden completa
    expect(comprasPosibles(9.99, 0, 50, 10)).toBe(0);
    expect(comprasPosibles(30, 0, 50, 10)).toBe(3); // sin perder una por redondeo
    expect(comprasPosibles(40, 60, 50, 10)).toBe(0); // invertido por encima del tope
  });
});

describe('detalleDeError', () => {
  it('dice en español el 404 genérico del servidor', () => {
    expect(detalleDeError(404, 'Not Found')).toBe('Esta parte del panel todavía no está activa en el servidor.');
  });

  it('respeta los mensajes propios del bot y no inventa uno si falta', () => {
    expect(detalleDeError(409, 'No hay modelo cargado.')).toBe('No hay modelo cargado.');
    expect(detalleDeError(500, undefined)).toBe('El servidor respondió 500.');
  });
});

describe('metricasOperaciones', () => {
  const o = (id: number, simbolo: string, creado: string, lado: string, cantidad: number, precio: number, comision: number, resultado: number | null = null, estado = 'ejecutada') =>
    ({ id, simbolo, creado, lado, cantidad, precio, comision, resultado, estado });

  it('cierra cada compra con la venta siguiente del mismo activo y contrasta el resultado', () => {
    const m = metricasOperaciones([
      o(1, 'AUSDT', '2026-11-06T04:00:00+00:00', 'comprar', 10, 100, 1),
      o(2, 'BUSDT', '2026-11-06T05:00:00+00:00', 'comprar', 5, 200, 1),
      o(3, 'AUSDT', '2026-11-06T10:00:00+00:00', 'vender', 10, 110, 1.1, 97.9),
      o(4, 'BUSDT', '2026-11-07T05:00:00+00:00', 'vender', 5, 190, 0.95, -51.95),
      o(5, 'CUSDT', '2026-11-07T06:00:00+00:00', 'comprar', 1, 50, 0),
    ]);
    expect([m.cerradas, m.abiertas, m.descuadres, m.acierto]).toEqual([2, 1, 0, 0.5]);
    expect(m.factorBeneficio).toBeCloseTo(97.9 / 51.95);
    expect(m.resultadoNeto).toBeCloseTo(45.95);
    expect(m.duracionMediaH).toBeCloseTo(15);
  });

  it('sin operaciones cerradas no inventa cifras', () => {
    const m = metricasOperaciones([o(1, 'AUSDT', '2026-11-06T04:00:00+00:00', 'comprar', 10, 100, 1)]);
    expect(m).toEqual({ cerradas: 0, abiertas: 1, acierto: null, factorBeneficio: null, resultadoNeto: 0, duracionMediaH: null, descuadres: 0 });
  });
});

describe('historial de operaciones', () => {
  it('pinta la compra según su altura en el rango del día anterior', () => {
    expect(tonoAltura('en baja')).toBe('baja');
    expect(tonoAltura('bajo el mínimo del día anterior')).toBe('baja');
    expect(tonoAltura('a media altura')).toBe('media');
    expect(tonoAltura('en alta')).toBe('alta');
    expect(tonoAltura('sobre el máximo del día anterior')).toBe('alta');
    expect(tonoAltura('sin dato')).toBe('sin');
  });

  it('cuenta compras en baja y en alta y suma solo el resultado de las cerradas', () => {
    const r = resumenHistorial([
      { etiqueta: 'en baja', estado: 'cerrada', resultado: 12.5 },
      { etiqueta: 'sobre el máximo del día anterior', estado: 'cerrada', resultado: -20 },
      { etiqueta: 'a media altura', estado: 'abierta', resultado: null },
    ]);
    expect(r).toEqual({ compras: 3, enBaja: 1, enAlta: 1, cerradas: 2, resultado: -7.5 });
  });
});

describe('hora local', () => {
  it('pasa la hora UTC del bot a la hora local, aunque cambie el día', () => {
    expect(horaLocal('2026-11-12T05:47:53+00:00', false, 360)).toBe('11-11 23:47');
    expect(horaLocal('2026-11-12T05:47:53+00:00', true, 360)).toBe('2026-11-11 23:47:53');
    expect(horaLocal('2026-11-12T05:47:53+00:00', false, 0)).toBe('11-12 05:47');
  });

  it('deja vacío lo que no tiene hora y devuelve tal cual lo que no entiende', () => {
    expect(horaLocal(null)).toBe('');
    expect(horaLocal('sin fecha')).toBe('sin fecha');
  });
});

describe('conexión de cada activo', () => {
  it('cuenta los activos con precio en vivo y nombra los que no tienen', () => {
    expect(conexionActivos([{ simbolo: 'BTCUSDT', bid: 70000 }, { simbolo: 'ETHUSDT', bid: null }, { simbolo: 'XRPUSDT' }]))
      .toEqual({ conPrecio: 1, total: 3, sinPrecio: ['ETH', 'XRP'] });
  });
});

describe('conexión con MEXC en la cabecera', () => {
  const filas: { simbolo: string; bid: number | null }[] = [{ simbolo: 'BTCUSDT', bid: 70000 }, { simbolo: 'ETHUSDT', bid: 3000 }];
  const radar = (ultimo: number | null, servidor = 10_000, f = filas) => ({ filas: f, estadisticas: { ultimo_barrido_ms: ultimo }, servidor_ms: servidor });

  it('en vivo cuando el último barrido es reciente y todos tienen precio', () => {
    expect(estadoMexc(radar(8_000), null)).toMatchObject({ tono: 'vivo', texto: 'en vivo 2/2' });
  });

  it('parcial cuando a algún activo le falta precio, y lo nombra', () => {
    const r = estadoMexc(radar(9_500, 10_000, [filas[0], { simbolo: 'ETHUSDT', bid: null }]), null);
    expect(r).toMatchObject({ tono: 'parcial', texto: '1/2 con precio' });
    expect(r.detalle).toContain('ETH');
  });

  it('sin conexión si el barrido se atrasó, si no hay barridos o si falla la consulta', () => {
    expect(estadoMexc(radar(1_000), null)).toMatchObject({ tono: 'caido', texto: 'sin conexión' });
    expect(estadoMexc(radar(null), null).tono).toBe('caido');
    expect(estadoMexc(null, 'Failed to fetch').tono).toBe('caido');
  });
});
