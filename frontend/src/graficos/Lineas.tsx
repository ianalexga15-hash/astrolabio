import { useEffect, useMemo, useRef, useState } from 'react';
import { ejeX } from '../logica';
import { useCola } from '../movimiento';

export interface Serie {
  nombre: string;
  color: string;
  valores: (number | null)[];
  punteada?: boolean;
}

export interface Marca {
  i: number;
  tipo: 'comprar' | 'vender';
  etiqueta: string;
}

interface Props {
  titulo: string;
  etiquetas: string[];
  series: Serie[];
  marcas?: Marca[];
  formato?: (v: number) => string;
  alto?: number;
  referencia?: number;
  identidad?: string;
  /** Serie que recibe un dato cada segundo: se dibuja sin trazo ni pulso, para no animar cada precio (documento de Alex, §26.6). */
  quieta?: boolean;
}

const MARGEN = { izq: 70, der: 18, sup: 12, inf: 28 };
const SIN_COLA = { desde: null, veces: 0 };

function escalaLimpia(min: number, max: number, cuantas = 5) {
  const rango = max - min || Math.abs(max) || 1;
  const bruto = rango / (cuantas - 1);
  const potencia = 10 ** Math.floor(Math.log10(bruto));
  const paso = [1, 2, 2.5, 5, 10].map((m) => m * potencia).find((p) => p >= bruto) ?? bruto;
  const lineas: number[] = [];
  const tope = Math.ceil(max / paso - 1e-9) * paso; // la escala siempre cubre el valor máximo
  for (let v = Math.floor(min / paso) * paso; v <= tope + paso * 0.001; v += paso) lineas.push(Number(v.toPrecision(12)));
  return lineas;
}

/** Gráfica de líneas con un solo eje, cursor que sigue al puntero y tabla alternativa. */
export function Lineas({ titulo, etiquetas, series, marcas = [], formato = (v) => v.toLocaleString('es-MX'), alto = 280, referencia, identidad, quieta = false }: Props) {
  const colaViva = useCola(etiquetas, identidad);
  const cola = quieta ? SIN_COLA : colaViva;
  const caja = useRef<HTMLDivElement>(null);
  const [ancho, setAncho] = useState(720);
  const [cursor, setCursor] = useState<number | null>(null);

  useEffect(() => {
    if (!caja.current) return;
    const o = new ResizeObserver(([e]) => setAncho(Math.max(280, e.contentRect.width)));
    o.observe(caja.current);
    return () => o.disconnect();
  }, [etiquetas.length > 0]); // sin datos no hay caja que medir: se vuelve a enganchar cuando llegan

  const { x, y, lineas, trazos } = useMemo(() => {
    const todos = series.flatMap((s) => s.valores).filter((v): v is number => v != null && Number.isFinite(v));
    if (referencia != null) todos.push(referencia);
    const min = todos.length ? Math.min(...todos) : 0;
    const max = todos.length ? Math.max(...todos) : 1;
    const lineas = escalaLimpia(min, max);
    const y0 = lineas[0];
    const y1 = lineas[lineas.length - 1];
    const n = Math.max(1, etiquetas.length - 1);
    const x = (i: number) => MARGEN.izq + (i / n) * (ancho - MARGEN.izq - MARGEN.der);
    const y = (v: number) => alto - MARGEN.inf - ((v - y0) / (y1 - y0 || 1)) * (alto - MARGEN.sup - MARGEN.inf);
    // Los huecos (valores vacíos) cortan la línea; no se inventan puntos entre muestras.
    const tramo = (valores: (number | null)[], desde: number, hasta: number) => {
      let d = '';
      let abierto = false;
      for (let i = desde; i <= hasta; i++) {
        const v = valores[i];
        if (v == null || !Number.isFinite(v)) {
          abierto = false;
          continue;
        }
        d += `${abierto ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
        abierto = true;
      }
      return d;
    };
    const trazos = series.map((s) => {
      const fin = s.valores.length - 1;
      return cola.desde == null ? { historia: tramo(s.valores, 0, fin), nuevo: '' } : { historia: tramo(s.valores, 0, cola.desde), nuevo: tramo(s.valores, cola.desde, fin) };
    });
    return { x, y, lineas, trazos };
  }, [series, etiquetas.length, ancho, alto, referencia, cola.desde]);

  if (!etiquetas.length) return <p className="vacio">Sin datos para graficar todavía.</p>;

  const mover = (clienteX: number) => {
    const r = caja.current!.getBoundingClientRect();
    const fraccion = (clienteX - r.left - MARGEN.izq) / (r.width - MARGEN.izq - MARGEN.der);
    setCursor(Math.round(Math.min(1, Math.max(0, fraccion)) * (etiquetas.length - 1)));
  };
  const saltoEje = Math.max(1, Math.ceil(etiquetas.length / Math.max(2, Math.floor(ancho / 110))));

  return (
    <figure className="grafica">
      <figcaption>{titulo}</figcaption>
      {series.length > 1 && (
        <ul className="leyenda" aria-label="Leyenda">
          {series.map((s) => (
            <li key={s.nombre}>
              <svg width="24" height="6" aria-hidden="true">
                <line x1="0" y1="3" x2="24" y2="3" stroke={s.color} strokeWidth="2.5" strokeDasharray={s.punteada ? '4 3' : undefined} />
              </svg>
              {s.nombre}
            </li>
          ))}
        </ul>
      )}
      <div
        ref={caja}
        className="lienzo-grafica"
        tabIndex={0}
        role="img"
        aria-label={`${titulo}. Usa las flechas para recorrer los valores; también hay una tabla debajo.`}
        onPointerMove={(e) => mover(e.clientX)}
        onPointerLeave={() => setCursor(null)}
        onKeyDown={(e) => {
          if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
          e.preventDefault();
          setCursor((c) => Math.min(etiquetas.length - 1, Math.max(0, (c ?? etiquetas.length - 1) + (e.key === 'ArrowLeft' ? -1 : 1))));
        }}
      >
        <svg width={ancho} height={alto} aria-hidden="true">
          {lineas.map((v) => (
            <g key={v}>
              <line x1={MARGEN.izq} x2={ancho - MARGEN.der} y1={y(v)} y2={y(v)} className="rejilla" />
              <text x={MARGEN.izq - 8} y={y(v) + 4} textAnchor="end" className="eje">{formato(v)}</text>
            </g>
          ))}
          {referencia != null && <line x1={MARGEN.izq} x2={ancho - MARGEN.der} y1={y(referencia)} y2={y(referencia)} className="referencia" />}
          {/* Cerca del borde derecho la fecha se alinea a la derecha para no cortarse */}
          {etiquetas.map((t, i) => (i % saltoEje === 0 ? <text key={t + i} x={x(i)} y={alto - 8} textAnchor={x(i) > ancho - MARGEN.der - 36 ? 'end' : 'middle'} className="eje">{ejeX(t)}</text> : null))}
          {trazos.map((t, i) => (
            <g key={series[i].nombre}>
              <path d={t.historia} fill="none" stroke={series[i].color} strokeWidth="2" strokeDasharray={series[i].punteada ? '5 4' : undefined} strokeLinejoin="round" />
              {t.nuevo && (
                <path key={cola.veces} d={t.nuevo} pathLength={series[i].punteada ? undefined : 1} className={series[i].punteada ? 'cola-aparece' : 'cola-traza'} fill="none"
                  stroke={series[i].color} strokeWidth="2" strokeDasharray={series[i].punteada ? '5 4' : undefined} strokeLinejoin="round" />
              )}
            </g>
          ))}
          {cola.desde != null && series[0].valores.at(-1) != null && (
            <circle key={`pulso-${cola.veces}`} cx={x(series[0].valores.length - 1)} cy={y(series[0].valores.at(-1) as number)} r="4" fill={series[0].color} className="pulso-extremo" />
          )}
          {marcas.map((m) => {
            const v = series[0].valores[m.i];
            if (v == null) return null;
            return m.tipo === 'comprar' ? (
              <path key={`${m.i}c`} d={`M${x(m.i)} ${y(v) + 7}l6 10h-12z`} className="marca-compra"><title>{m.etiqueta}</title></path>
            ) : (
              <path key={`${m.i}v`} d={`M${x(m.i)} ${y(v) - 7}l6 -10h-12z`} className="marca-venta"><title>{m.etiqueta}</title></path>
            );
          })}
          {cursor != null && <line x1={x(cursor)} x2={x(cursor)} y1={MARGEN.sup} y2={alto - MARGEN.inf} className="cursor" />}
          {cursor != null && series.map((s) => (s.valores[cursor] != null ? <circle key={s.nombre} cx={x(cursor)} cy={y(s.valores[cursor] as number)} r="4" fill={s.color} stroke="var(--nebulosa)" strokeWidth="2" /> : null))}
        </svg>
        {cursor != null && (
          <div className="burbuja" style={{ left: Math.min(x(cursor) + 12, ancho - 190), top: 8 }}>
            <strong>{etiquetas[cursor]}</strong>
            {series.map((s) => (
              <div key={s.nombre} className="burbuja-fila">
                <svg width="14" height="4" aria-hidden="true"><line x1="0" y1="2" x2="14" y2="2" stroke={s.color} strokeWidth="2" /></svg>
                <b>{s.valores[cursor] == null ? 'sin dato' : formato(s.valores[cursor] as number)}</b>
                <span>{s.nombre}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <details className="tabla-grafica">
        <summary>Ver como tabla</summary>
        <div className="tabla-scroll">
          <table>
            <thead><tr><th>Fecha</th>{series.map((s) => <th key={s.nombre}>{s.nombre}</th>)}</tr></thead>
            <tbody>
              {etiquetas.slice(-60).map((t, k) => {
                const i = etiquetas.length - Math.min(60, etiquetas.length) + k;
                return <tr key={t + i}><td>{t}</td>{series.map((s) => <td key={s.nombre}>{s.valores[i] == null ? 'sin dato' : formato(s.valores[i] as number)}</td>)}</tr>;
              })}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
