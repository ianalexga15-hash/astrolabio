// Lógica pura del panel: formatos y geometría del universo. Sin React, para poder probarla.

export interface Nota {
  id: string;
  titulo: string;
  origen: string;
  tipo: string;
  galaxia: string;
  fuente: string;
  fecha: string;
  cuerpo: string;
}

export interface EnlaceNota {
  origen: string;
  destino: string;
}

export interface Punto3D {
  x: number;
  y: number;
  z: number;
}

const moneda = new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
const numero = new Intl.NumberFormat('es-MX', { maximumFractionDigits: 6 });

export const usd = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? 'sin dato' : moneda.format(v));
export const pct = (v: number | null | undefined, decimales = 2) =>
  v == null || !Number.isFinite(v) ? 'sin dato' : `${(v * 100).toFixed(decimales)} %`;
export const pctSigno = (v: number | null | undefined, decimales = 2) =>
  v == null || !Number.isFinite(v) ? 'sin dato' : `${v > 0 ? '+' : ''}${(v * 100).toFixed(decimales)} %`;
export const num = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? 'sin dato' : numero.format(v));
/** Precios de activos muy distintos: pocos decimales en BTC y los necesarios en monedas de fracción de centavo. */
export function precio(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return 'sin dato';
  const a = Math.abs(v);
  const decimales = a >= 1000 ? 2 : a >= 1 ? 4 : a >= 0.01 ? 5 : 8;
  return v.toLocaleString('es-MX', { minimumFractionDigits: Math.min(decimales, 2), maximumFractionDigits: decimales });
}

export const fechaHora = (ms: number) => new Date(ms).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' });

/** Rótulo del eje de Lineas: una fecha ISO va como dd/mm/aa (mismo ancho que antes); lo demás pierde sus dos primeros caracteres. */
export const ejeX = (t: string) => (/^\d{4}-\d{2}-\d{2}$/.test(t) ? `${t.slice(8, 10)}/${t.slice(5, 7)}/${t.slice(2, 4)}` : t.slice(2));

/** Tiempo restante en formato HH:MM:SS. Nunca negativo. */
export function cuentaAtras(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const dos = (n: number) => String(n).padStart(2, '0');
  return `${dos(Math.floor(s / 3600))}:${dos(Math.floor(s / 60) % 60)}:${dos(s % 60)}`;
}

/** Media móvil simple. Los primeros valores quedan vacíos: nunca se rellenan hacia atrás. */
export function sma(valores: number[], ventana: number): (number | null)[] {
  let suma = 0;
  return valores.map((v, i) => {
    suma += v;
    if (i >= ventana) suma -= valores[i - ventana];
    return i >= ventana - 1 ? suma / ventana : null;
  });
}

/** Índice con base 100 para comparar series en un solo eje. */
export function indexar100(valores: number[]): number[] {
  if (!valores.length || valores[0] === 0) return [];
  return valores.map((v) => (v / valores[0]) * 100);
}

function hash(texto: string): number {
  let h = 2166136261;
  for (const c of texto) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return (h >>> 0) / 4294967295;
}

/**
 * Posiciones del universo. Cada galaxia ocupa un punto de una esfera y sus notas forman un disco en espiral.
 * La galaxia de la visión queda en el centro. Es determinista: la misma nota siempre cae en el mismo lugar.
 */
export function posicionesUniverso(notas: Nota[], radio = 175): Map<string, Punto3D> {
  const galaxias = [...new Set(notas.map((n) => n.galaxia))].sort();
  const externas = galaxias.filter((g) => g !== 'Visión');
  const centros = new Map<string, Punto3D>();
  externas.forEach((g, i) => {
    const y = externas.length === 1 ? 0 : 1 - (2 * (i + 0.5)) / externas.length;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const a = i * 2.399963;
    centros.set(g, { x: Math.cos(a) * r * radio, y: y * radio * 0.8, z: Math.sin(a) * r * radio });
  });
  centros.set('Visión', { x: 0, y: 0, z: 0 });

  const salida = new Map<string, Punto3D>();
  for (const g of galaxias) {
    const miembros = notas.filter((n) => n.galaxia === g);
    const centro = centros.get(g)!;
    const inclinacion = hash(g) * Math.PI;
    const giro = hash(`${g}giro`) * Math.PI * 2;
    miembros.forEach((n, i) => {
      const a = i * 2.399963 + giro;
      const r = (g === 'Visión' ? 19 : 11) * Math.sqrt(i + (miembros.length === 1 ? 0 : 0.6)); // en el centro las etiquetas necesitan más aire
      const local = { x: Math.cos(a) * r, y: 0, z: Math.sin(a) * r };
      const altura = (hash(n.id) - 0.5) * 8;
      const y = local.y * Math.cos(inclinacion) - local.z * Math.sin(inclinacion) + altura;
      const z = local.y * Math.sin(inclinacion) + local.z * Math.cos(inclinacion);
      salida.set(n.id, { x: centro.x + local.x, y: centro.y + y, z: centro.z + z });
    });
  }
  return salida;
}

/** Polvo decorativo de cada galaxia: dos brazos en espiral en el mismo plano que sus notas. No representa datos. */
export function polvoDeGalaxia(galaxia: string, centro: Punto3D, cuantas: number, cantidad = 90): Punto3D[] {
  const inclinacion = hash(galaxia) * Math.PI;
  const giro = hash(`${galaxia}giro`) * Math.PI * 2;
  const alcance = 26 + Math.sqrt(cuantas) * 15;
  return Array.from({ length: cantidad }, (_, i) => {
    const t = (i + 1) / cantidad;
    const brazo = i % 2 === 0 ? 0 : Math.PI;
    const a = giro + brazo + t * 5.2 + (hash(`${galaxia}${i}`) - 0.5) * 0.7;
    const r = alcance * t;
    const x = Math.cos(a) * r;
    const z0 = Math.sin(a) * r;
    return {
      x: centro.x + x,
      y: centro.y - z0 * Math.sin(inclinacion) + (hash(`${galaxia}y${i}`) - 0.5) * 5,
      z: centro.z + z0 * Math.cos(inclinacion),
    };
  });
}

export function centroDeGalaxia(notas: Nota[], posiciones: Map<string, Punto3D>, galaxia: string): Punto3D | null {
  const puntos = notas.filter((n) => n.galaxia === galaxia).map((n) => posiciones.get(n.id)).filter(Boolean) as Punto3D[];
  if (!puntos.length) return null;
  const media = (f: (p: Punto3D) => number) => puntos.reduce((s, p) => s + f(p), 0) / puntos.length;
  return { x: media((p) => p.x), y: media((p) => p.y), z: media((p) => p.z) };
}

export function proyectar(p: Punto3D, giro: number, inclinacion: number) {
  const x = p.x * Math.cos(giro) + p.z * Math.sin(giro);
  const z0 = -p.x * Math.sin(giro) + p.z * Math.cos(giro);
  const y = p.y * Math.cos(inclinacion) - z0 * Math.sin(inclinacion);
  const z = p.y * Math.sin(inclinacion) + z0 * Math.cos(inclinacion);
  const profundidad = 560 / (560 + z);
  return { x: x * profundidad, y: y * profundidad, z, profundidad };
}

export function filtrarNotas(notas: Nota[], filtro: { texto?: string; origen?: string; galaxia?: string }): Nota[] {
  const q = (filtro.texto ?? '').toLocaleLowerCase();
  return notas.filter(
    (n) =>
      (!filtro.origen || n.origen === filtro.origen) &&
      (!filtro.galaxia || n.galaxia === filtro.galaxia) &&
      `${n.titulo} ${n.cuerpo} ${n.fuente}`.toLocaleLowerCase().includes(q),
  );
}

export function conectadas(id: string, notas: Nota[], enlaces: EnlaceNota[]): Nota[] {
  const ids = new Set(enlaces.flatMap((e) => (e.origen === id ? [e.destino] : e.destino === id ? [e.origen] : [])));
  return notas.filter((n) => ids.has(n.id));
}

export interface RutaApi {
  metodo: string;
  ruta: string;
  descripcion: string;
}

export interface EsquemaApi {
  paths?: Record<string, Record<string, { summary?: string; description?: string }>>;
}

/** Filas legibles del esquema OpenAPI del backend: método, ruta y primera línea de su descripción, ordenadas por ruta. */
export function rutasDeEsquema(esquema: EsquemaApi | null): RutaApi[] {
  return Object.entries(esquema?.paths ?? {})
    .flatMap(([ruta, operaciones]) =>
      Object.entries(operaciones).map(([metodo, op]) => ({ metodo: metodo.toUpperCase(), ruta, descripcion: (op.description ?? op.summary ?? '').split('\n')[0] })),
    )
    .sort((a, b) => a.ruta.localeCompare(b.ruta) || a.metodo.localeCompare(b.metodo));
}

/** Reglas de la contraseña personal, las mismas que exige el backend. Devuelve el problema o null. */
export function validarNuevaClave(nueva: string, repetida: string): string | null {
  if (nueva.trim().length < 10) return 'Usa al menos 10 caracteres.';
  if (nueva.length > 128) return 'Usa como máximo 128 caracteres.';
  if (nueva !== repetida) return 'Las dos contraseñas no coinciden.';
  return null;
}

export interface Energia {
  conectada: boolean | null;
  bateria: number | null;
  sin_suspender: boolean;
}

/** Qué tan expuesto está el bot a detenerse porque Windows suspenda el equipo. */
export function avisoEnergia(e: Energia | null | undefined): { texto: string; alerta: boolean } {
  if (!e) return { texto: 'Sin datos de energía todavía.', alerta: false };
  const bateria = e.bateria == null ? '' : ` al ${e.bateria}%`;
  if (e.sin_suspender) {
    return e.conectada === false
      ? { texto: `El bot pide a Windows no suspender el equipo, pero estás con batería${bateria}: se gastará más rápido.`, alerta: true }
      : { texto: 'El bot pide a Windows no suspender el equipo mientras corre.', alerta: false };
  }
  if (e.conectada === false) {
    return {
      texto: `Con batería${bateria}. Si Windows suspende el equipo por inactividad, el bot se detiene hasta que lo despiertes. Para evitarlo, enchúfalo y agrega BOT_SIN_SUSPENDER=1 a .env.`,
      alerta: true,
    };
  }
  if (e.conectada === true) {
    return { texto: 'Enchufado. Si Windows suspende el equipo por inactividad, el bot se detiene; BOT_SIN_SUSPENDER=1 en .env lo evita.', alerta: false };
  }
  return { texto: 'Windows no informó el estado de energía.', alerta: false };
}

export interface Interruptor { texto: string; ruta: 'iniciar' | 'detener' | null; espera?: string; motivo?: string }

/** Control global del bot. Activar evalúa y opera solo cuando se cumplen condiciones; nunca usa /api/apagar. */
export function interruptor(estado: string | null | undefined, conectado: boolean): Interruptor {
  if (!conectado || !estado) return { texto: 'Estado desconocido', ruta: null, motivo: 'Sin respuesta del bot: no se sabe si está encendido.' };
  if (estado === 'activo') return { texto: 'Desactivar bot', ruta: 'detener', espera: 'Desactivando…' };
  if (estado === 'sin_modelo') return { texto: 'Activar bot', ruta: null, motivo: 'No hay modelo cargado: genera uno o copia el aprobado en models/.' };
  return { texto: 'Activar bot', ruta: 'iniciar', espera: 'Activando…' };
}

/** Aviso antes de detener: desactivar no liquida posiciones y también suspende sus salidas automáticas. */
export function avisoDetener(posiciones: number | null | undefined): string | null {
  if (!posiciones) return null;
  return posiciones === 1
    ? 'Queda 1 posición abierta. Se detienen compras y ventas automáticas; la posición no se cierra.'
    : `Quedan ${posiciones} posiciones abiertas. Se detienen compras y ventas automáticas; las posiciones no se cierran.`;
}

/** Con el bot detenido el reflejo no envía órdenes de salida: mientras haya posiciones, el panel lo dice siempre. */
export function avisoDetenido(estado: string | undefined, posiciones: number | null | undefined): string | null {
  if (estado !== 'detenido' || !posiciones) return null;
  return posiciones === 1
    ? 'El bot está detenido con 1 posición abierta: no hay ventas automáticas, así que su stop y su objetivo no se ejecutan.'
    : `El bot está detenido con ${posiciones} posiciones abiertas: no hay ventas automáticas, así que sus stops y objetivos no se ejecutan.`;
}

export interface Cambio { valor: number | string | null | undefined; veces: number; sube: boolean | null }

/** Cuenta solo cambios reales: la primera carga no es una subida y repetir el valor no vuelve a animar. */
export function registrarCambio(c: Cambio, valor: Cambio['valor']): Cambio {
  if (valor === c.valor) return c;
  const cuenta = c.valor != null && valor != null;
  const sube = cuenta && typeof valor === 'number' && typeof c.valor === 'number' ? valor > c.valor : c.sube;
  return { valor, veces: c.veces + (cuenta ? 1 : 0), sube };
}

/** Identificadores que no estaban en la lectura anterior; la primera lectura no marca nada como nuevo. */
export function idsNuevos(vistos: Set<number> | null, ids: number[]): Set<number> {
  return new Set(vistos ? ids.filter((id) => !vistos.has(id)) : []);
}

export const NOMBRE_BOT: Record<string, string> = {
  activo: 'Activo', pausado: 'En pausa', detenido: 'Detenido', bloqueado: 'Bloqueado', sin_modelo: 'Sin modelo', desconocido: 'Sin conexión',
};

/** Último punto ya dibujado cuando llegan puntos nuevos al final de una serie; null en la primera carga o si la serie no continúa. */
export function puntosNuevos(ultimaConocida: string | null, etiquetas: string[]): number | null {
  if (ultimaConocida == null) return null;
  const i = etiquetas.lastIndexOf(ultimaConocida);
  return i < 0 || i === etiquetas.length - 1 ? null : i;
}

export interface SaldoMexc { activo: string; libre: number; bloqueado: number }

/** Valor estimado en USDT de la cuenta real con el precio de compra del radar; lo que no tiene precio queda aparte, sin inventarle valor. */
export function valorCuenta(saldos: SaldoMexc[], precios: Record<string, number>) {
  const filas = saldos.map((s) => {
    const cantidad = s.libre + s.bloqueado;
    const precio = s.activo === 'USDT' ? 1 : precios[`${s.activo}USDT`];
    return { ...s, cantidad, valor: precio == null ? null : cantidad * precio };
  });
  return { filas, total: filas.reduce((t, f) => t + (f.valor ?? 0), 0), sinPrecio: filas.filter((f) => f.valor == null).map((f) => f.activo) };
}

/** Mensaje de error para la persona: los genéricos del servidor, en inglés, se dicen en español. */
export function detalleDeError(estado: number, detalle: unknown): string {
  if (estado === 404 && detalle === 'Not Found') return 'Esta parte del panel todavía no está activa en el servidor.';
  return typeof detalle === 'string' ? detalle : `El servidor respondió ${estado}.`;
}

export interface OrdenCuenta { id: number; simbolo?: string; creado: string; lado: string; estado: string; cantidad: number; precio: number; comision: number; resultado: number | null }

/** Operaciones cerradas: cada venta cierra la compra anterior del mismo activo y su resultado se contrasta con precios, cantidades y comisiones. */
export function metricasOperaciones(ordenes: OrdenCuenta[]) {
  const abiertas = new Map<string, OrdenCuenta>();
  const cerradas: { resultado: number; horas: number; descuadre: boolean }[] = [];
  const ejecutadas = ordenes.filter((o) => o.estado === 'ejecutada').sort((a, b) => a.creado.localeCompare(b.creado) || a.id - b.id);
  for (const o of ejecutadas) {
    const clave = o.simbolo ?? '';
    const compra = abiertas.get(clave);
    if (o.lado === 'comprar') abiertas.set(clave, o);
    else if (o.lado === 'vender' && compra && o.resultado != null) {
      abiertas.delete(clave);
      const calculado = o.cantidad * o.precio - o.comision - (compra.cantidad * compra.precio + compra.comision);
      cerradas.push({ resultado: o.resultado, horas: (Date.parse(o.creado) - Date.parse(compra.creado)) / 3_600_000, descuadre: Math.abs(calculado - o.resultado) > 0.01 });
    }
  }
  const n = cerradas.length;
  const ganado = cerradas.reduce((t, c) => t + Math.max(c.resultado, 0), 0);
  const perdido = -cerradas.reduce((t, c) => t + Math.min(c.resultado, 0), 0);
  return {
    cerradas: n,
    abiertas: abiertas.size,
    acierto: n ? cerradas.filter((c) => c.resultado > 0).length / n : null,
    factorBeneficio: perdido ? ganado / perdido : null,
    resultadoNeto: cerradas.reduce((t, c) => t + c.resultado, 0),
    duracionMediaH: n ? cerradas.reduce((t, c) => t + c.horas, 0) / n : null,
    descuadres: cerradas.filter((c) => c.descuadre).length,
  };
}

/** Color de la compra según su altura en el rango del día anterior: comprar abajo es «baja», arriba es «alta». */
export function tonoAltura(etiqueta: string): 'baja' | 'media' | 'alta' | 'sin' {
  if (etiqueta === 'en baja' || etiqueta.startsWith('bajo')) return 'baja';
  if (etiqueta === 'en alta' || etiqueta.startsWith('sobre')) return 'alta';
  return etiqueta === 'a media altura' ? 'media' : 'sin';
}

export function resumenHistorial(filas: { etiqueta: string; estado: string; resultado: number | null }[]) {
  const cerradas = filas.filter((f) => f.estado === 'cerrada');
  return {
    compras: filas.length,
    enBaja: filas.filter((f) => tonoAltura(f.etiqueta) === 'baja').length,
    enAlta: filas.filter((f) => tonoAltura(f.etiqueta) === 'alta').length,
    cerradas: cerradas.length,
    resultado: cerradas.reduce((t, f) => t + (f.resultado ?? 0), 0),
  };
}

/** Fecha y hora local de un ISO con zona; las del bot vienen en UTC. `desfaseMin` sigue a getTimezoneOffset: 360 en UTC-6. */
export function horaLocal(iso: string | null | undefined, segundos = false, desfaseMin?: number): string {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const d = new Date(t - (desfaseMin ?? new Date(t).getTimezoneOffset()) * 60_000);
  const p = (n: number) => String(n).padStart(2, '0');
  const dia = `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
  return segundos ? `${d.getUTCFullYear()}-${dia}:${p(d.getUTCSeconds())}` : dia;
}

/** Cuántos activos tienen precio en vivo de MEXC y cuáles no: «Sin compra hoy» no es lo mismo que sin conexión. */
export function conexionActivos(filas: { simbolo: string; bid?: number | null }[]) {
  const sinPrecio = filas.filter((f) => f.bid == null).map((f) => f.simbolo.replace('USDT', ''));
  return { conPrecio: filas.length - sinPrecio.length, total: filas.length, sinPrecio };
}

/** Nombre del primer límite que quedó vacío: el servidor no acepta texto vacío como número. */
export const limiteVacio = (formulario: Record<string, unknown>, campos: readonly (readonly string[])[]) => campos.find(([k]) => formulario[k] === '')?.[1] ?? null;

export interface PuntoSegundo { t: number; bid: number; ask: number }

/** Serie de 1 s de un activo: suma la lectura del barrido `t` si es nueva y tiene precio, y conserva solo la ventana (15 min). */
export function sumarSegundo(serie: PuntoSegundo[], t: number, bid: number | null | undefined, ask: number | null | undefined, ventanaMs = 15 * 60_000): PuntoSegundo[] {
  if (bid == null || ask == null || !Number.isFinite(bid) || !Number.isFinite(ask) || (serie.length > 0 && t <= serie[serie.length - 1].t)) return serie;
  return [...serie.filter((p) => p.t > t - ventanaMs), { t, bid, ask }];
}

type RadarMinimo = { filas: { simbolo: string; bid?: number | null }[]; estadisticas: { ultimo_barrido_ms: number | null } | null; servidor_ms?: number };

/** Conexión con MEXC para la cabecera: edad del último barrido del reflejo y cuántos activos tienen precio. Más de 5 s sin barrido es sin conexión. */
export function estadoMexc(radar: RadarMinimo | null, error: string | null) {
  const ultimo = radar?.estadisticas?.ultimo_barrido_ms;
  const edad = ultimo && radar?.servidor_ms ? (radar.servidor_ms - ultimo) / 1000 : null;
  if (error || !radar || edad == null || edad > 5) {
    const detalle = error ? `No se pudo leer el radar: ${error}` : edad == null ? 'Todavía no hay barridos del reflejo.' : `El último precio de MEXC llegó hace ${Math.round(edad)} s.`;
    return { tono: 'caido' as const, texto: 'sin conexión', detalle };
  }
  const c = conexionActivos(radar.filas);
  if (c.sinPrecio.length) return { tono: 'parcial' as const, texto: `${c.conPrecio}/${c.total} con precio`, detalle: `Sin precio: ${c.sinPrecio.join(', ')}` };
  return { tono: 'vivo' as const, texto: `en vivo ${c.conPrecio}/${c.total}`, detalle: `Precio de MEXC hace ${edad.toFixed(1)} s en los ${c.total} activos.` };
}
