import { useEffect, useMemo, useRef } from 'react';
import { centroDeGalaxia, type EnlaceNota, type Nota, polvoDeGalaxia, posicionesUniverso, proyectar } from '../logica';

const COLOR_AUTOR: Record<string, string> = { codex: '#4f9dff', claude: '#ec8a52', alex: '#f2c14e' };
const color = (o: string) => COLOR_AUTOR[o] ?? '#9fb3c8';
const partes = (o: string) => (o === 'ambos' ? ['codex', 'claude'] : [o]);
const ESTRELLAS = Array.from({ length: 320 }, (_, i) => {
  const a = Math.abs(Math.sin(i * 12.9898) * 43758.5453) % 1;
  const b = Math.abs(Math.sin(i * 78.233) * 12543.123) % 1;
  const c = Math.abs(Math.sin(i * 37.719) * 3758.91) % 1;
  return { x: a, y: b, r: 0.25 + c * 0.85, alfa: 0.08 + c * 0.42 };
});

interface Props {
  notas: Nota[];
  enlaces: EnlaceNota[];
  seleccion: string | null;
  alSeleccionar: (id: string | null) => void;
}

/** Red 3D del desarrollo. Las galaxias agrupan por tema; los pulsos viajan solo por enlaces [[Título]] reales. */
export function Universo({ notas, enlaces, seleccion, alSeleccionar }: Props) {
  const lienzo = useRef<HTMLCanvasElement>(null);
  const vista = useRef({ giro: 0.5, inclinacion: 0.25, zoom: 1 });
  const arrastre = useRef<{ x: number; y: number; total: number } | null>(null);
  const proyectados = useRef<{ id: string; x: number; y: number }[]>([]);

  const posiciones = useMemo(() => posicionesUniverso(notas), [notas]);
  const galaxias = useMemo(() => {
    const nombres = [...new Set(notas.map((n) => n.galaxia))];
    return nombres.map((g) => {
      const centro = centroDeGalaxia(notas, posiciones, g)!;
      const cuantas = notas.filter((n) => n.galaxia === g).length;
      return { nombre: g, centro, cuantas, polvo: polvoDeGalaxia(g, centro, cuantas) };
    });
  }, [notas, posiciones]);
  const datos = useRef({ notas, enlaces, seleccion, posiciones, galaxias });
  datos.current = { notas, enlaces, seleccion, posiciones, galaxias };

  useEffect(() => {
    const canvas = lienzo.current!;
    const ctx = canvas.getContext('2d')!;
    const reducido = matchMedia('(prefers-reduced-motion: reduce)');
    let cuadro = 0;

    const dibujar = (ahora: number) => {
      cuadro = requestAnimationFrame(dibujar);
      if (document.hidden) return;
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
      const fondo = ctx.createRadialGradient(w * 0.5, h * 0.5, 10, w * 0.5, h * 0.5, Math.max(w, h) * 0.7);
      fondo.addColorStop(0, '#1a2048');
      fondo.addColorStop(0.55, '#0e1330');
      fondo.addColorStop(1, '#070a18');
      ctx.fillStyle = fondo;
      ctx.fillRect(0, 0, w, h);
      for (const s of ESTRELLAS) {
        ctx.globalAlpha = s.alfa;
        ctx.fillStyle = '#d4dcff';
        ctx.beginPath();
        ctx.arc(s.x * w, s.y * h, s.r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      const v = vista.current;
      if (!reducido.matches && !arrastre.current && !datos.current.seleccion) v.giro += 0.0009;
      const escala = (Math.min(w, h) / 500) * v.zoom;
      const { notas, enlaces, seleccion, posiciones, galaxias } = datos.current;
      const proyectar2 = (p: { x: number; y: number; z: number }) => {
        const q = proyectar(p, v.giro, v.inclinacion);
        return { sx: w / 2 + q.x * escala, sy: h / 2 + q.y * escala, z: q.z, profundidad: q.profundidad };
      };

      // Cajas de texto ya dibujadas: los títulos de notas no se enciman con ellas ni con los nombres de galaxia.
      const etiquetas: { x: number; y: number; w: number }[] = [];
      // Galaxias: una nebulosa tenue y su nombre
      for (const g of galaxias) {
        const c = proyectar2(g.centro);
        const radio = (34 + Math.sqrt(g.cuantas) * 14) * escala * c.profundidad;
        const n = ctx.createRadialGradient(c.sx, c.sy, 0, c.sx, c.sy, radio);
        n.addColorStop(0, 'rgba(120,140,255,0.16)');
        n.addColorStop(1, 'rgba(120,140,255,0)');
        ctx.fillStyle = n;
        ctx.beginPath();
        ctx.arc(c.sx, c.sy, radio, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#c9d4ff';
        g.polvo.forEach((q, i) => {
          const s = proyectar2(q);
          ctx.globalAlpha = 0.12 + (i % 5) * 0.05;
          ctx.fillRect(s.sx, s.sy, 1.3, 1.3);
        });
        ctx.globalAlpha = 1;
        ctx.font = '500 13px Bahnschrift, "Segoe UI Variable Display", system-ui';
        ctx.textAlign = 'center';
        ctx.fillStyle = 'rgba(190,202,240,0.72)';
        ctx.shadowColor = '#050914';
        ctx.shadowBlur = 6;
        ctx.fillText(g.nombre, c.sx, c.sy - radio * 0.72);
        ctx.shadowBlur = 0;
        const anchoGalaxia = ctx.measureText(g.nombre).width;
        etiquetas.push({ x: c.sx - anchoGalaxia / 2, y: c.sy - radio * 0.72 - 11, w: anchoGalaxia });
      }

      const mapa = new Map(notas.map((n) => [n.id, { nota: n, ...proyectar2(posiciones.get(n.id)!) }]));
      enlaces.forEach((e, i) => {
        const a = mapa.get(e.origen);
        const b = mapa.get(e.destino);
        if (!a || !b) return;
        const foco = seleccion && (seleccion === e.origen || seleccion === e.destino);
        const ca = color(partes(a.nota.origen).at(-1)!);
        const cb = color(partes(b.nota.origen)[0]);
        const g = ctx.createLinearGradient(a.sx, a.sy, b.sx, b.sy);
        g.addColorStop(0, ca);
        g.addColorStop(1, cb);
        ctx.strokeStyle = g;
        ctx.globalAlpha = foco ? 0.95 : seleccion ? 0.08 : 0.3;
        ctx.lineWidth = foco ? 1.8 : 0.9;
        ctx.beginPath();
        ctx.moveTo(a.sx, a.sy);
        ctx.lineTo(b.sx, b.sy);
        ctx.stroke();
        if (!reducido.matches) {
          const t = (ahora / 3800 + i * 0.137) % 1;
          ctx.globalAlpha = foco ? 1 : seleccion ? 0.2 : 0.75;
          ctx.fillStyle = t < 0.5 ? ca : cb;
          ctx.beginPath();
          ctx.arc(a.sx + (b.sx - a.sx) * t, a.sy + (b.sy - a.sy) * t, foco ? 2.4 : 1.5, 0, Math.PI * 2);
          ctx.fill();
        }
      });
      ctx.globalAlpha = 1;

      const orden = [...mapa.values()].sort((a, b) => b.z - a.z);
      proyectados.current = orden.map((p) => ({ id: p.nota.id, x: p.sx, y: p.sy }));
      const textos: { titulo: string; x: number; y: number; foco: boolean }[] = []; // se dibujan al final, encima de todas las estrellas
      for (const p of orden) {
        const { nota: n } = p;
        const foco = seleccion === n.id;
        const vision = n.tipo === 'Visión';
        const curso = n.tipo === 'En curso';
        const pendiente = n.tipo === 'Pendiente';
        const radio = (foco ? 8 : vision ? 8 : curso ? 6.5 : 5) * p.profundidad * Math.max(0.85, v.zoom * 0.8);
        ctx.globalAlpha = seleccion && !foco ? 0.65 : 1;
        ctx.shadowBlur = foco || vision ? 26 : 12;
        ctx.shadowColor = color(partes(n.origen)[0]);
        const autores = partes(n.origen);
        if (pendiente) {
          ctx.setLineDash([3, 3]);
          ctx.lineWidth = 1.8;
          ctx.strokeStyle = color(autores[0]);
          ctx.beginPath();
          ctx.arc(p.sx, p.sy, radio, 0, Math.PI * 2);
          ctx.stroke();
          ctx.setLineDash([]);
        } else {
          autores.forEach((o, i) => {
            ctx.fillStyle = color(o);
            ctx.beginPath();
            if (autores.length === 1) ctx.arc(p.sx, p.sy, radio, 0, Math.PI * 2);
            else {
              const a0 = Math.PI / 2 + i * Math.PI;
              ctx.moveTo(p.sx, p.sy);
              ctx.arc(p.sx, p.sy, radio, a0, a0 + Math.PI);
              ctx.closePath();
            }
            ctx.fill();
          });
        }
        ctx.shadowBlur = 0;
        if (curso) {
          const pulso = reducido.matches ? 0.5 : (Math.sin(ahora / 380) + 1) / 2;
          ctx.strokeStyle = color(autores[0]);
          ctx.globalAlpha = 0.35 + 0.5 * pulso;
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(p.sx, p.sy, radio + 4 + 5 * pulso, 0, Math.PI * 2);
          ctx.stroke();
        }
        if (vision) {
          ctx.strokeStyle = '#ffe9a8';
          ctx.lineWidth = 1.4;
          ctx.beginPath();
          ctx.arc(p.sx, p.sy, radio + 5, 0, Math.PI * 2);
          ctx.stroke();
        }
        if (foco) {
          ctx.strokeStyle = '#ffffff';
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.arc(p.sx, p.sy, radio + 3, 0, Math.PI * 2);
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
        if (foco || vision || curso) {
          ctx.font = `${foco ? '600 13px' : '12px'} "Segoe UI Variable Text", "Segoe UI", system-ui`;
          ctx.textAlign = 'center';
          ctx.fillStyle = foco ? '#ffffff' : '#d8e0f8';
          const titulo = n.titulo.slice(0, 44);
          const ancho = ctx.measureText(titulo).width;
          const x = p.sx - ancho / 2;
          const y = p.sy + radio + 8;
          if (foco || !etiquetas.some((b) => x < b.x + b.w && x + ancho > b.x && Math.abs(y - b.y) < 16)) {
            textos.push({ titulo, x: p.sx, y: p.sy + radio + 19, foco });
            etiquetas.push({ x, y, w: ancho });
          }
        }
      }
      ctx.textAlign = 'center';
      ctx.shadowColor = '#050914';
      ctx.shadowBlur = 6;
      for (const t of textos) {
        ctx.font = `${t.foco ? '600 13px' : '12px'} "Segoe UI Variable Text", "Segoe UI", system-ui`;
        ctx.fillStyle = t.foco ? '#ffffff' : '#d8e0f8';
        ctx.fillText(t.titulo, t.x, t.y);
      }
      ctx.shadowBlur = 0;
    };
    cuadro = requestAnimationFrame(dibujar);
    return () => cancelAnimationFrame(cuadro);
  }, []);

  const elegir = (x: number, y: number) => {
    const c = lienzo.current!.getBoundingClientRect();
    const hallado = [...proyectados.current].reverse().find((p) => Math.hypot(p.x - (x - c.left), p.y - (y - c.top)) < 15);
    alSeleccionar(hallado?.id ?? null);
  };

  return (
    <canvas
      ref={lienzo}
      className="lienzo-universo"
      tabIndex={0}
      role="img"
      aria-label="Universo de notas del desarrollo. Arrastra para girar y usa la rueda para acercar. La lista cronológica tiene la misma información."
      onPointerDown={(e) => {
        arrastre.current = { x: e.clientX, y: e.clientY, total: 0 };
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        const d = arrastre.current;
        if (!d) return;
        const dx = e.clientX - d.x;
        const dy = e.clientY - d.y;
        d.total += Math.abs(dx) + Math.abs(dy);
        vista.current.giro += dx * 0.007;
        vista.current.inclinacion = Math.max(-1.4, Math.min(1.4, vista.current.inclinacion + dy * 0.007));
        d.x = e.clientX;
        d.y = e.clientY;
      }}
      onPointerUp={(e) => {
        if (arrastre.current && arrastre.current.total < 6) elegir(e.clientX, e.clientY);
        arrastre.current = null;
      }}
      onPointerCancel={() => {
        arrastre.current = null;
      }}
      onWheel={(e) => {
        vista.current.zoom = Math.max(0.5, Math.min(3.2, vista.current.zoom - e.deltaY * 0.001));
      }}
      onKeyDown={(e) => {
        const v = vista.current;
        if (e.key === 'ArrowLeft') v.giro -= 0.12;
        else if (e.key === 'ArrowRight') v.giro += 0.12;
        else if (e.key === 'ArrowUp') v.inclinacion -= 0.12;
        else if (e.key === 'ArrowDown') v.inclinacion += 0.12;
        else if (e.key === '+') v.zoom = Math.min(3.2, v.zoom + 0.2);
        else if (e.key === '-') v.zoom = Math.max(0.5, v.zoom - 0.2);
        else return;
        e.preventDefault();
      }}
    />
  );
}
