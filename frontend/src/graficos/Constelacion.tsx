import { useCallback, useEffect, useRef, useState } from 'react';
import type { EventoBot } from '../api';

export interface NodoCerebro {
  id: string;
  etiqueta: string;
  grupo: string;
  estado: 'activo' | 'atencion' | 'detenido' | 'reposo';
  eventos: number;
  ultimo: number | null;
}

export interface EnlaceCerebro {
  origen: string;
  destino: string;
  tipo: string;
}

// Lugar de cada estrella en un plano de 0 a 1. El orden sigue el camino de una decisión, de izquierda a derecha.
const LUGAR: Record<string, [number, number]> = {
  mexc_velas: [0.07, 0.25], mexc_ticker: [0.07, 0.5], grabador: [0.19, 0.14], validador: [0.2, 0.36],
  variables: [0.33, 0.42], modelo: [0.47, 0.53],
  analista: [0.53, 0.28], herramientas: [0.42, 0.13], gateway: [0.66, 0.15], ollama: [0.8, 0.11], asistente: [0.9, 0.28],
  riesgo: [0.66, 0.52], reflejo: [0.68, 0.74], ejecutar: [0.82, 0.62], cuenta: [0.94, 0.5], registro: [0.88, 0.86], panel: [0.56, 0.9],
  entrenamiento: [0.28, 0.58], diagnostico: [0.12, 0.84], replay: [0.42, 0.93], notas: [0.26, 0.93],
};
const ZONA: Record<string, [number, number]> = {
  'Percepción': [0.03, 0.05], Modelo: [0.4, 0.42], 'Cerebro LLM': [0.55, 0.04], 'Núcleo determinista': [0.75, 0.44], Laboratorio: [0.03, 0.76],
};
const COLOR_ESTADO = { activo: '#7cc4ff', atencion: '#f5b95c', detenido: '#ff5c8a', reposo: '#55618a' } as const;
// Mismos tonos que --flujo-* en estilos.css; validados para visión normal y daltonismo sobre la superficie oscura.
const COLOR_TIPO: Record<string, string> = {
  datos: '#2463c8', decision: '#9180e6', bloqueo: '#c98500', autorizacion: '#139fc0', ordenes: '#4a9e2c', aprendizaje: '#7d88aa', error: '#ff5c8a',
};
const ESTRELLAS = Array.from({ length: 420 }, (_, i) => {
  const a = Math.abs(Math.sin(i * 127.1) * 43758.5453) % 1;
  const b = Math.abs(Math.sin(i * 311.7) * 12435.192) % 1;
  const c = Math.abs(Math.sin(i * 74.7) * 9182.34) % 1;
  return { x: a, y: b, r: 0.3 + c * 0.9, alfa: 0.12 + c * 0.45 };
});

interface Particula {
  a: [number, number];
  b: [number, number];
  c: [number, number];
  inicio: number;
  color: string;
}

interface Props {
  nodos: NodoCerebro[];
  enlaces: EnlaceCerebro[];
  seleccion: string | null;
  alSeleccionar: (id: string | null) => void;
  registrarEmisor: (emisor: (e: EventoBot) => void) => void;
}

function control(a: [number, number], b: [number, number]): [number, number] {
  const mx = (a[0] + b[0]) / 2;
  const my = (a[1] + b[1]) / 2;
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  return [mx - dy * 0.16, my + dx * 0.16];
}

function bezier(a: [number, number], c: [number, number], b: [number, number], t: number): [number, number] {
  const u = 1 - t;
  return [u * u * a[0] + 2 * u * t * c[0] + t * t * b[0], u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]];
}

/** Cada estrella es un componente real. Las partículas solo aparecen cuando el backend emite un evento. */
export function Constelacion({ nodos, enlaces, seleccion, alSeleccionar, registrarEmisor }: Props) {
  const lienzo = useRef<HTMLCanvasElement>(null);
  const particulas = useRef<Particula[]>([]);
  const destellos = useRef<Map<string, number>>(new Map());
  const llegadas = useRef<Set<number>>(new Set());
  const datos = useRef({ nodos, enlaces, seleccion });
  datos.current = { nodos, enlaces, seleccion };
  const [sobre, setSobre] = useState<string | null>(null);
  const sobreRef = useRef<string | null>(null);
  const redibujar = useRef<() => void>(() => {});
  const puntero = useRef({ x: 0, y: 0 });
  const [ambiente, setAmbiente] = useState(() => {
    try { return localStorage.getItem('astrolabio.ambiente-estelar') !== 'quieto'; }
    catch { return true; }
  });
  const ambienteRef = useRef(ambiente);
  ambienteRef.current = ambiente;
  sobreRef.current = sobre;

  useEffect(() => {
    try { localStorage.setItem('astrolabio.ambiente-estelar', ambiente ? 'animado' : 'quieto'); }
    catch { /* La preferencia sigue funcionando durante esta visita. */ }
    redibujar.current();
  }, [ambiente]);

  const emitir = useCallback((e: EventoBot) => {
    const a = LUGAR[e.origen];
    const b = LUGAR[e.destino];
    const ahora = performance.now();
    if (LUGAR[e.origen]) destellos.current.set(e.origen, ahora);
    redibujar.current();
    if (!a || !b) return;
    // Bajo carga se agrupan: una sola partícula por conexión cada 150 ms; el conteo real se muestra aparte.
    for (let k = particulas.current.length - 1; k >= 0 && ahora - particulas.current[k].inicio < 150; k--) {
      if (particulas.current[k].a === a && particulas.current[k].b === b) return;
    }
    if (particulas.current.length >= 160) particulas.current.shift();
    particulas.current.push({ a, b, c: control(a, b), inicio: ahora, color: COLOR_TIPO[e.tipo] ?? COLOR_TIPO.datos });
    // Límite global de callbacks pendientes durante ráfagas de eventos.
    if (llegadas.current.size < 160) {
      const timer = window.setTimeout(() => {
        llegadas.current.delete(timer);
        destellos.current.set(e.destino, performance.now());
        redibujar.current();
      }, 950);
      llegadas.current.add(timer);
    }
  }, []);

  useEffect(() => {
    registrarEmisor(emitir);
    return () => {
      registrarEmisor(() => {});
      for (const timer of llegadas.current) window.clearTimeout(timer);
      llegadas.current.clear();
      particulas.current = [];
      destellos.current.clear();
    };
  }, [registrarEmisor, emitir]);

  useEffect(() => {
    const canvas = lienzo.current!;
    const ctx = canvas.getContext('2d')!;
    const reducido = matchMedia('(prefers-reduced-motion: reduce)');
    let cuadro = 0;
    let ultimoCuadro = -Infinity;
    let visible = true;
    let px = 0, py = 0;
    // La nebulosa se pinta una sola vez por tamaño, no en cada cuadro.
    const fondoCache = document.createElement('canvas');
    const pintarFondo = (w: number, h: number) => {
      fondoCache.width = Math.ceil(w);
      fondoCache.height = Math.ceil(h);
      const f = fondoCache.getContext('2d')!;
      f.fillStyle = '#050914';
      f.fillRect(0, 0, w, h);
      f.globalCompositeOperation = 'screen';
      for (let i = 0; i < 100; i++) {
        const t = i / 99;
        const x = (0.08 + t * 0.86) * w;
        const y = (0.64 - t * 0.33 + Math.sin(t * 13) * 0.13) * h;
        const radio = (0.09 + Math.abs(Math.sin(i * 7.1)) * 0.12) * h;
        const g = f.createRadialGradient(x, y, 0, x, y, radio);
        g.addColorStop(0, i % 3 ? 'rgba(56,75,151,0.045)' : 'rgba(79,137,160,0.045)');
        g.addColorStop(0.45, 'rgba(67,47,109,0.025)');
        g.addColorStop(1, 'rgba(0,0,0,0)');
        f.fillStyle = g;
        f.fillRect(x - radio, y - radio, radio * 2, radio * 2);
      }
      f.globalCompositeOperation = 'source-over';
    };

    const dibujar = (ahora: number) => {
      cuadro = reducido.matches || document.hidden || !visible ? 0 : requestAnimationFrame(dibujar);
      if (document.hidden || !visible) return;
      if (!reducido.matches && ahora - ultimoCuadro < 32) return;
      ultimoCuadro = ahora;
      const r = canvas.getBoundingClientRect();
      if (!r.width) return;
      const dpr = Math.min(devicePixelRatio || 1, 2);
      const w = r.width;
      const h = r.height;
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (fondoCache.width !== Math.ceil(w) || fondoCache.height !== Math.ceil(h)) pintarFondo(w, h);
      ctx.drawImage(fondoCache, 0, 0, w, h);
      const animado = !reducido.matches && ambienteRef.current;
      px += ((animado ? puntero.current.x : 0) - px) * 0.07;
      py += ((animado ? puntero.current.y : 0) - py) * 0.07;
      if (!animado) { px = 0; py = 0; }
      for (const [i, s] of ESTRELLAS.entries()) {
        const brillo = animado ? 0.82 + 0.18 * Math.sin(ahora * 0.0006 + i * 2.7) : 1;
        ctx.globalAlpha = s.alfa * brillo;
        ctx.fillStyle = i % 7 === 0 ? '#f4d9b1' : '#c8dfff';
        const x = s.x * w + px * s.r * 9;
        const y = s.y * h + py * s.r * 9;
        ctx.beginPath();
        ctx.arc(x, y, s.r * 0.8, 0, Math.PI * 2);
        ctx.fill();
        if (s.r > 1.12) {
          ctx.globalAlpha *= 0.3;
          ctx.fillRect(x - 3.5, y - 0.35, 7, 0.7);
          ctx.fillRect(x - 0.35, y - 3.5, 0.7, 7);
        }
      }
      ctx.globalAlpha = 1;
      const P = (p: [number, number]): [number, number] => [p[0] * w, p[1] * h];

      ctx.font = '500 13px Bahnschrift, "Segoe UI Variable Display", system-ui';
      ctx.textAlign = 'left';
      ctx.fillStyle = '#97a3c8'; // nombres de zona legibles sobre el fondo estelar
      for (const [nombre, lugar] of Object.entries(ZONA)) ctx.fillText(nombre, lugar[0] * w, lugar[1] * h);

      const { nodos, enlaces, seleccion } = datos.current;
      for (const e of enlaces) {
        const a = LUGAR[e.origen];
        const b = LUGAR[e.destino];
        if (!a || !b) continue;
        const c = control(a, b);
        const foco = seleccion && (seleccion === e.origen || seleccion === e.destino);
        ctx.strokeStyle = COLOR_TIPO[e.tipo] ?? '#6fb7ff';
        ctx.globalAlpha = foco ? 0.85 : seleccion ? 0.12 : 0.42; // los tonos validados son más oscuros: más opacidad para que las conexiones se lean
        ctx.lineWidth = foco ? 1.6 : 1;
        ctx.setLineDash(e.tipo === 'aprendizaje' ? [3, 5] : []);
        ctx.beginPath();
        ctx.moveTo(...P(a));
        ctx.quadraticCurveTo(...P(c), ...P(b));
        ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;

      particulas.current = particulas.current.filter((p) => ahora - p.inicio < 950);
      for (const p of reducido.matches ? [] : particulas.current) {
        const t = (ahora - p.inicio) / 950;
        for (let k = 0; k < 7; k++) {
          const q = Math.max(0, t - k * 0.022);
          const [x, y] = P(bezier(p.a, p.c, p.b, q));
          ctx.globalAlpha = (1 - k / 7) * 0.95;
          ctx.fillStyle = p.color;
          ctx.beginPath();
          ctx.arc(x, y, Math.max(0.6, 2.6 - k * 0.3), 0, Math.PI * 2);
          ctx.fill();
        }
      }
      ctx.globalAlpha = 1;

      for (const n of nodos) {
        const lugar = LUGAR[n.id];
        if (!lugar) continue;
        const [x, y] = P(lugar);
        const color = COLOR_ESTADO[n.estado];
        const destello = destellos.current.get(n.id);
        const brillo = !reducido.matches && destello ? Math.max(0, 1 - (ahora - destello) / 900) : 0;
        const foco = seleccion === n.id || sobreRef.current === n.id;
        const radio = (n.estado === 'reposo' ? 3.6 : 5) + brillo * 3 + (foco ? 1.5 : 0);
        const halo = ctx.createRadialGradient(x, y, 0, x, y, radio * (n.estado === 'reposo' ? 3 : 6) + brillo * 18);
        halo.addColorStop(0, color);
        halo.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.globalAlpha = n.estado === 'reposo' ? 0.25 : 0.5 + brillo * 0.4;
        ctx.fillStyle = halo;
        ctx.beginPath();
        ctx.arc(x, y, radio * 6 + brillo * 18, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.fillStyle = n.estado === 'reposo' ? color : '#ffffff';
        ctx.beginPath();
        ctx.arc(x, y, radio * 0.62, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.3;
        ctx.beginPath();
        ctx.arc(x, y, radio + 4, -1.2, 1.1);
        ctx.stroke();
        if (n.estado === 'detenido') {
          ctx.beginPath();
          ctx.moveTo(x - 4, y - 4);
          ctx.lineTo(x + 4, y + 4);
          ctx.moveTo(x + 4, y - 4);
          ctx.lineTo(x - 4, y + 4);
          ctx.strokeStyle = '#ffffff';
          ctx.stroke();
        }
        if (brillo > 0 && !reducido.matches) {
          ctx.globalAlpha = brillo * 0.65;
          ctx.strokeStyle = color;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(x, y, radio + 8 + (1 - brillo) * 26, 0, Math.PI * 2);
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
        if (foco) {
          ctx.strokeStyle = '#c5ddff';
          ctx.globalAlpha = 0.65;
          ctx.lineWidth = 0.8;
          ctx.beginPath();
          ctx.ellipse(x, y, 23, 13, -0.45, 0, Math.PI * 2);
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
        ctx.font = `${foco ? '600 ' : ''}13px "Segoe UI Variable Text", "Segoe UI", system-ui`;
        ctx.textAlign = 'center';
        ctx.fillStyle = foco ? '#ffffff' : n.estado === 'reposo' ? '#a7b2d2' : '#dbe3fb';
        // Mantener las etiquetas completas dentro del lienzo, también junto al borde.
        const mitadTexto = ctx.measureText(n.etiqueta).width / 2;
        const textoX = Math.max(mitadTexto + 10, Math.min(w - mitadTexto - 10, x));
        ctx.shadowColor = '#050914';
        ctx.shadowBlur = 6;
        ctx.fillText(n.etiqueta, textoX, Math.min(h - 12, y + radio + 20));
        ctx.shadowBlur = 0;
      }
    };
    cuadro = requestAnimationFrame(dibujar);
    const reanudar = () => {
      cancelAnimationFrame(cuadro);
      ultimoCuadro = -Infinity;
      cuadro = requestAnimationFrame(dibujar);
    };
    // Con movimiento reducido no hay cuadros continuos: se redibuja estático cuando cambian datos, selección, tamaño o visibilidad.
    redibujar.current = () => {
      if (reducido.matches) reanudar();
    };
    const tamano = new ResizeObserver(() => redibujar.current());
    tamano.observe(canvas);
    const alVolver = () => reanudar();
    const observador = new IntersectionObserver(([entrada]) => {
      visible = entrada.isIntersecting;
      reanudar();
    });
    observador.observe(canvas);
    document.addEventListener('visibilitychange', alVolver);
    reducido.addEventListener('change', reanudar);
    return () => {
      cancelAnimationFrame(cuadro);
      tamano.disconnect();
      redibujar.current = () => {};
      observador.disconnect();
      document.removeEventListener('visibilitychange', alVolver);
      reducido.removeEventListener('change', reanudar);
    };
  }, []);

  useEffect(() => redibujar.current(), [nodos, enlaces, seleccion, sobre]);

  const buscar = (e: React.PointerEvent | React.MouseEvent) => {
    const r = lienzo.current!.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width;
    const y = (e.clientY - r.top) / r.height;
    let mejor: string | null = null;
    let distancia = 26;
    for (const [id, p] of Object.entries(LUGAR)) {
      const d = Math.hypot((p[0] - x) * r.width, (p[1] - y) * r.height);
      if (d < distancia) {
        distancia = d;
        mejor = id;
      }
    }
    return mejor;
  };

  return (
    <>
    <div className="ambiente-estelar">
      <button type="button" aria-pressed={ambiente} onClick={() => setAmbiente(!ambiente)}>
        Ambiente estelar: {ambiente ? 'animado' : 'quieto'}
      </button>
    </div>
    <canvas
      ref={lienzo}
      className="lienzo-cerebro"
      role="img"
      aria-label="Constelación de componentes del bot. La lista de abajo tiene la misma información."
      style={{ cursor: sobre ? 'pointer' : 'default' }}
      onPointerMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        puntero.current = { x: (e.clientX - r.left) / r.width - 0.5, y: (e.clientY - r.top) / r.height - 0.5 };
        setSobre(buscar(e));
      }}
      onPointerLeave={() => { setSobre(null); puntero.current = { x: 0, y: 0 }; }}
      onClick={(e) => alSeleccionar(buscar(e))}
    />
    </>
  );
}
