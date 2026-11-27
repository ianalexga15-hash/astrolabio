import { useCallback, useEffect, useRef, useState } from 'react';
import { detalleDeError } from './logica';

export class ErrorApi extends Error {
  constructor(public estado: number, mensaje: string) {
    super(mensaje);
  }
}

export async function pedir<T>(ruta: string, opciones: RequestInit = {}): Promise<T> {
  let r: Response;
  try {
    r = await fetch(ruta, { credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, ...opciones });
  } catch {
    throw new ErrorApi(0, 'Sin conexión con Astrolabio: revisa que siga encendido. El panel vuelve a intentarlo solo.');
  }
  if (r.status === 401 && ruta !== '/api/login') window.dispatchEvent(new Event('sesion-perdida'));
  if (!r.ok) {
    const cuerpo = await r.json().catch(() => ({}));
    throw new ErrorApi(r.status, detalleDeError(r.status, cuerpo.detail));
  }
  return r.json();
}

export const enviar = <T,>(ruta: string, cuerpo?: unknown, metodo = 'POST') =>
  pedir<T>(ruta, { method: metodo, body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo) });

/** Consulta periódica. Mantiene el último dato válido si una consulta falla y dice qué falló. */
export function useDatos<T>(ruta: string, cadaMs = 0) {
  const [datos, setDatos] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const vivo = useRef(true);

  const recargar = useCallback(async () => {
    try {
      const d = await pedir<T>(ruta);
      if (vivo.current) {
        setDatos(d);
        setError(null);
      }
    } catch (e) {
      if (vivo.current) setError((e as Error).message);
    }
  }, [ruta]);

  useEffect(() => {
    vivo.current = true;
    recargar();
    const t = cadaMs ? window.setInterval(() => document.hidden || recargar(), cadaMs) : 0;
    return () => {
      vivo.current = false;
      if (t) clearInterval(t);
    };
  }, [recargar, cadaMs]);

  return { datos, error, recargar };
}

export interface EventoBot {
  id: number;
  ts: number;
  origen: string;
  destino: string;
  tipo: string;
  detalle: string;
}

/** Eventos reales del backend. La constelación se mueve solo con esto. */
export function useEventos(alRecibir: (e: EventoBot) => void) {
  const manejador = useRef(alRecibir);
  manejador.current = alRecibir;
  const [conectado, setConectado] = useState(false);
  useEffect(() => {
    const fuente = new EventSource('/api/eventos');
    fuente.onopen = () => setConectado(true);
    fuente.onerror = () => setConectado(false);
    fuente.onmessage = (m) => manejador.current(JSON.parse(m.data));
    return () => fuente.close();
  }, []);
  return conectado;
}

export interface Condicion {
  id: string;
  nombre: string;
  cumple: boolean;
  detalle: string;
}

export interface FilaRadar {
  simbolo: string;
  estado: string;
  bot?: string;
  motivo?: string;
  bid?: number | null;
  ask?: number | null;
  spread_bps?: number | null;
  pronostico?: number | null;
  condiciones: Condicion[];
  cumplidas: number;
  cantidad?: number;
  entrada?: number | null;
  stop?: number | null;
  objetivo?: number | null;
  resultado_abierto?: number | null;
  espera?: { precio: number; hasta_ms: number } | null;
  valor?: number;
}

export interface ResumenCartera {
  patrimonio: number;
  capital_inicial: number;
  rendimiento: number;
  caida: number;
  posiciones: number;
  armadas: number;
  activos: number;
  exposicion: number;
  efectivo: number;
  costos: number;
  bloqueo_entradas: string | null;
  aviso_capital: string | null;
  sin_modelo: string[];
  cupo: number;
}

export interface EstadisticasReflejo {
  barridos: number;
  activos: number;
  latencia_ms: number;
  p99_ms: number;
  ultimo_barrido_ms: number | null;
}

export interface Radar {
  filas: FilaRadar[];
  estadisticas: EstadisticasReflejo | null;
  resumen: ResumenCartera | null;
  error: string | null;
  servidor_ms?: number;
}

export interface Decision {
  id: number;
  simbolo?: string;
  vela: number;
  fecha_vela: string;
  creado: string;
  modelo_version: string;
  pronostico: number | null;
  senal: number;
  umbral: number | null;
  filtro: string | null;
  accion_propuesta: string;
  justificacion: string;
  origen: string;
  llm_modelo: string;
  latencia_ms: number | null;
  herramientas: string;
  aprobada: number;
  accion_final: string;
  motivos: string;
  precio: number;
  indicadores: string;
}

export interface Orden {
  id: number;
  simbolo?: string;
  creado: string;
  lado: string;
  cantidad: number;
  precio: number;
  comision: number;
  estado: string;
  motivo: string;
  resultado: number | null;
  vela: number | null;
  modelo_costos?: string | null;
}

export interface Estado {
  modo: string;
  simbolo: string;
  simbolos: string[];
  activo: { estado: string; motivo: string } | null;
  alertas: { simbolo: string; estado: string; motivo: string }[];
  cartera: ResumenCartera | null;
  reflejo: EstadisticasReflejo | null;
  intervalo: string;
  servidor_ms: number;
  bot: { estado: string; motivo: string; por_fallo: boolean; proximo_reintento: number };
  mercado: {
    precio: number | null;
    edad_s: number | null;
    error: string | null;
    ultima_vela: { open_time: number; open: number; high: number; low: number; close: number; close_time: number } | null;
    proxima_vela_ms: number;
    edad_vela_horas: number | null;
    radar: FilaRadar | null;
  };
  cuenta: {
    efectivo: number;
    cantidad: number;
    precio_medio: number;
    stop: number | null;
    objetivo: number | null;
    costos: number;
    patrimonio: number;
    rendimiento: number;
    caida: number;
    capital_inicial: number;
    armada: { fecha: string; cierre: number; pronostico: number } | null;
  };
  ultima_decision: Decision | null;
  modelo: {
    version: string;
    tipo: string;
    nombre?: string;
    lookback: number;
    variables: string[];
    umbral: number;
    filtro: string;
    valido_para_entrega?: boolean;
    motivo?: string;
    conjunto_variables?: string;
  } | null;
  limites: Record<string, number | string>;
  llm: { modelo: string; decisor: string; ultimo: { modelo: string; latencia_ms: number; ts: number } | null };
}

export interface OrdenReal {
  id: number;
  creado: string;
  simbolo: string;
  lado: string;
  modo: string;
  estado: string;
  monto_usdt: number | null;
  ejecutado: number | null;
  cotizado: number | null;
  resultado: number | null;
  motivo: string | null;
}

export interface EstadoReal {
  modo: 'apagada' | 'sombra' | 'real';
  compras_bloqueadas: boolean;
  motivo: string;
  verificacion: { ok: boolean; mensaje: string; fecha: string } | null;
  topes: { tope_total_usdt: number; max_orden_usdt: number; perdida_diaria_usdt: number };
  clave_configurada: boolean;
  confirmacion: string;
  solo_paper?: boolean;  // la entrega rechaza el endpoint real: solo Apagada y Sombra
  posiciones: { simbolo: string; cantidad: number; costo: number }[];
  ordenes: OrdenReal[];
  expuesto: number;
  resultado_hoy: number;
}

export interface Corrida {
  run: string;
  tipo: string;
  etiqueta: string;
  activos?: number;
  ciclos: number;
  periodo: [string, string] | null;
  rendimiento: number | null;
  drawdown: number | null;
  comprar_y_mantener: number | null;
  operaciones: number;
  win_rate: number | null;
  costos: number;
  ordenes_rechazadas: number;
  acciones_rechazadas: number;
  latencia_media_ms: number | null;
  patrimonio_final: number | null;
  sharpe?: number | null;
  sortino?: number | null;
  var?: number | null;
  cvar?: number | null;
  /** Solo en vivo: activos que salieron de la cartera con operaciones cerradas; ya no suman al patrimonio. */
  salidos?: { simbolo: string; operaciones: number; resultado: number }[];
}
