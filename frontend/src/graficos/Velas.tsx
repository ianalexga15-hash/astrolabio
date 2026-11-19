import { useEffect, useRef } from 'react';
import { horaLocal, precio as precioEje } from '../logica';

export interface VelaOHLC {
  open_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

const NOMBRE: Record<string, string> = { '1d': 'Velas diarias', '5m': 'Velas de 5 min', '60m': 'Velas de 1 h' };

/** Presentación de OHLC de MEXC; nunca reconstruye velas a partir de cierres. Las diarias van por fecha UTC; las de 5 min y 1 h, en hora local. */
export function Velas({ datos, simbolo, intervalo = '1d' }: { datos: VelaOHLC[]; simbolo: string; intervalo?: string }) {
  const intradia = intervalo !== '1d';
  const recientes = datos.slice(-60);
  const desplazamiento = useRef<HTMLDivElement>(null);
  // En pantallas estrechas la gráfica se desplaza: empieza mostrando las velas más recientes y no se mueve sola con cada vela nueva.
  useEffect(() => { const d = desplazamiento.current; if (d) d.scrollLeft = d.scrollWidth; }, [simbolo, intervalo, recientes.length]);
  const validas = recientes.filter(v => [v.open_time, v.open, v.high, v.low, v.close].every(Number.isFinite)
    && v.low > 0 && v.high >= Math.max(v.open, v.close) && v.low <= Math.min(v.open, v.close));
  if (!validas.length) return <p className="vacio">Sin datos OHLC válidos para mostrar velas.</p>;
  const minimo = Math.min(...validas.map(v => v.low));
  const maximo = Math.max(...validas.map(v => v.high));
  const margen = (maximo - minimo || maximo * .01) * .06;
  const inferior = minimo - margen, superior = maximo + margen;
  const y = (v: number) => 270 - (v - inferior) / (superior - inferior) * 246;
  const paso = 660 / recientes.length;
  const precio = (v: number) => v.toLocaleString('es-MX', {maximumSignificantDigits: 8});
  const fecha = (v: VelaOHLC) => intradia ? horaLocal(new Date(v.open_time).toISOString()) : new Date(v.open_time).toISOString().slice(0, 10);
  return <figure className="grafica velas-terminal">
    <figcaption><strong>{simbolo} · {NOMBRE[intervalo] ?? intervalo}</strong><span className="leyenda">Últimas {recientes.length} velas {intradia ? 'de MEXC · hora local' : 'guardadas · UTC'}</span></figcaption>
    <div className="velas-desplazamiento" ref={desplazamiento}>
      <svg viewBox="0 0 780 310" role="img" aria-label={`${NOMBRE[intervalo] ?? 'Velas'} de ${simbolo}. Verde: cierre mayor o igual a apertura; rojo: cierre menor. Datos en la tabla inferior.`}>
        {[0, 1, 2, 3, 4].map(i => { const valor = inferior + (superior - inferior) * i / 4; return <g key={i}>
          <line x1="18" x2="685" y1={y(valor)} y2={y(valor)} stroke="var(--polvo-suave)" />
          {/* El rótulo es una posición del eje, no un dato de MEXC: va con los decimales del resto del panel; la tabla conserva toda la precisión */}
          <text x="695" y={y(valor) + 4} fill="var(--ceniza)" fontSize="11">{precioEje(valor)}</text>
        </g>; })}
        {recientes.map((v, i) => {
          if (!validas.includes(v)) return null;
          const x = 18 + paso * (i + .5), color = v.close >= v.open ? 'var(--positivo)' : 'var(--negativo)';
          return <g key={v.open_time}>
            <title>{fecha(v)} · Apertura {precio(v.open)} · Máximo {precio(v.high)} · Mínimo {precio(v.low)} · Cierre {precio(v.close)}</title>
            <line x1={x} x2={x} y1={y(v.high)} y2={y(v.low)} stroke={color} />
            <rect x={x - paso * .3} y={Math.min(y(v.open), y(v.close))} width={paso * .6} height={Math.max(1, Math.abs(y(v.open) - y(v.close)))} fill={color} />
            {(i === 0 || i === recientes.length - 1 || i % 15 === 0) && <text x={x} y="298" textAnchor={i === 0 ? 'start' : 'end'} fill="var(--ceniza)" fontSize="10">{fecha(v)}</text>}
          </g>;
        })}
      </svg>
    </div>
    <p className="leyenda"><span className="positivo">↑ Cierre ≥ apertura</span> · <span className="negativo">↓ Cierre &lt; apertura</span> · Mecha: mínimo–máximo</p>
    {validas.length !== recientes.length && <p role="status">Hay velas inválidas; se muestran huecos, sin inventar precios.</p>}
    <details><summary>Ver apertura, máximo, mínimo y cierre</summary><div className="tabla-scroll"><table><thead><tr><th>{intradia ? 'Hora local' : 'Fecha UTC'}</th><th>Apertura</th><th>Máximo</th><th>Mínimo</th><th>Cierre</th></tr></thead><tbody>
      {validas.map(v => <tr key={v.open_time}><td>{fecha(v)}</td>{[v.open, v.high, v.low, v.close].map((n, i) => <td key={i}>{precio(n)}</td>)}</tr>)}
    </tbody></table></div></details>
  </figure>;
}
