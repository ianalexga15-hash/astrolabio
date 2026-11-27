import { memo, type RefObject, useEffect, useRef, useState } from 'react';
import { atr, bollinger, ema, horaLocal, macd, pct, precio as precioEje, rsi, volatilidad } from '../logica';

export interface VelaOHLC {
  open_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

const NOMBRE: Record<string, string> = { '1d': 'Velas diarias', '5m': 'Velas de 5 min', '60m': 'Velas de 1 h' };
const X0 = 18, ANCHO = 660;
// Un solo formateador: toLocaleString con opciones crea uno nuevo en cada llamada, y con años de velas son miles por segundo.
const PRECIO = new Intl.NumberFormat('es-MX', { maximumSignificantDigits: 8 });
type Lectura = { titulo: string; filas: [string, string, string?][] };

/** Cruz que sigue al puntero: línea vertical en la vela (y en todos los paneles), línea horizontal con su precio sobre las velas y una
 *  burbuja con la fecha y los valores de esa vela. Va aparte de Velas para que mover el puntero no redibuje miles de velas. */
function Cruz({ lienzo, svgPrecio, n, rangoY, lectura }:
  { lienzo: RefObject<HTMLDivElement | null>; svgPrecio: RefObject<SVGSVGElement | null>; n: number; rangoY: [number, number]; lectura: (i: number) => Lectura }) {
  const [p, setP] = useState<{ x: number; y: number } | null>(null);
  useEffect(() => {
    const el = lienzo.current;
    if (!el) return;
    const mover = (e: PointerEvent) => { const r = el.getBoundingClientRect(); setP({ x: e.clientX - r.left, y: e.clientY - r.top }); };
    const salir = () => setP(null);
    el.addEventListener('pointermove', mover);
    el.addEventListener('pointerleave', salir);
    return () => { el.removeEventListener('pointermove', mover); el.removeEventListener('pointerleave', salir); };
  }, [lienzo]);
  const el = lienzo.current;
  if (!p || !n || !el) return null;
  const ancho = el.clientWidth, escala = ancho / 780, paso = ANCHO / n;  // todos los paneles comparten el ancho del viewBox
  const i = Math.max(0, Math.min(n - 1, Math.floor((p.x / escala - X0) / paso)));
  const x = (X0 + paso * (i + .5)) * escala;
  const altoPrecio = svgPrecio.current?.getBoundingClientRect().height ?? 0;  // las velas van arriba del lienzo
  const ySvg = altoPrecio ? p.y / altoPrecio * 310 : -1;
  const l = lectura(i);
  const derecha = x < ancho * .6;
  return <div className="cruz" aria-hidden="true">
    <i className="cruz-v" style={{ left: x }} />
    {ySvg >= 24 && ySvg <= 270 && <>
      <i className="cruz-h" style={{ top: p.y }} />
      <b className="cruz-precio" style={{ top: p.y }}>{precioEje(rangoY[0] + (270 - ySvg) / 246 * (rangoY[1] - rangoY[0]))}</b>
    </>}
    <div className={`burbuja cruz-burbuja${derecha ? '' : ' a-la-izquierda'}`} style={{ left: derecha ? x + 14 : x - 14, top: 8 }}>
      <strong>{l.titulo}</strong>
      {l.filas.map(([nombre, valor, tono]) => <div key={nombre} className="burbuja-fila"><span>{nombre}</span><b className={tono}>{valor}</b></div>)}
    </div>
  </div>;
}

/** Presentación de OHLC de MEXC; nunca reconstruye velas a partir de cierres. Las diarias van por fecha UTC; las de 5 min y 1 h, en hora local.
 *  Con indicadores: sobre las velas van los que se miden en precio (bandas de Bollinger con los cierres atípicos, SMA 20 y EMA 20);
 *  debajo, cada uno con su nombre y alineado vela por vela, los que tienen su propia escala: RSI, MACD, ATR y volatilidad.
 *  Se calculan con toda la serie recibida (como bot/features.py) y se muestran las últimas `ventana` velas. */
// memo: Mercado se repinta cada segundo por su cuenta atrás; la gráfica solo cuando cambian sus velas.
export const Velas = memo(function Velas({ datos, simbolo, intervalo = '1d', ventana = 60, indicadores = false, enCurso = false }:
  { datos: VelaOHLC[]; simbolo: string; intervalo?: string; ventana?: number; indicadores?: boolean; enCurso?: boolean }) {
  const intradia = intervalo !== '1d';
  const recientes = datos.slice(-ventana);
  const inicio = datos.length - recientes.length;
  const desplazamiento = useRef<HTMLDivElement>(null);
  const lienzo = useRef<HTMLDivElement>(null);
  const svgPrecio = useRef<SVGSVGElement>(null);
  const [tabla, setTabla] = useState(false);  // con años de velas, la tabla se arma solo al abrirla
  // En pantallas estrechas la gráfica se desplaza: empieza mostrando las velas más recientes y no se mueve sola con cada vela nueva.
  useEffect(() => { const d = desplazamiento.current; if (d) d.scrollLeft = d.scrollWidth; }, [simbolo, intervalo, recientes.length]);
  const ok = recientes.map(v => [v.open_time, v.open, v.high, v.low, v.close].every(Number.isFinite)
    && v.low > 0 && v.high >= Math.max(v.open, v.close) && v.low <= Math.min(v.open, v.close));
  const validas = recientes.filter((_, i) => ok[i]);
  if (!validas.length) return <p className="vacio">Sin datos OHLC válidos para mostrar velas.</p>;
  const cierres = datos.map(v => v.close);
  const bandas = indicadores ? bollinger(cierres).slice(inicio) : [];
  const media20 = indicadores ? ema(cierres).slice(inicio) : [];
  const fuerza = indicadores ? rsi(cierres).slice(inicio) : [];
  const impulso = indicadores ? macd(cierres).slice(inicio) : [];
  const rango = indicadores ? atr(datos).slice(inicio) : [];
  const vol20 = indicadores ? volatilidad(cierres).slice(inicio) : [];
  const extremos = [...validas.flatMap(v => [v.low, v.high]), ...bandas.flatMap(b => (b ? [b.inf, b.sup] : []))];
  const minimo = Math.min(...extremos), maximo = Math.max(...extremos);
  const margen = (maximo - minimo || maximo * .01) * .06;
  const inferior = minimo - margen, superior = maximo + margen;
  const y = (v: number) => 270 - (v - inferior) / (superior - inferior) * 246;
  const paso = ANCHO / recientes.length;
  const xDe = (i: number) => X0 + paso * (i + .5);
  const grosor = Math.max(paso * .6, .6);
  const punto = Math.min(3.2, Math.max(1.6, paso));  // con años de velas, los puntos se achican para no tapar el precio
  const cadaFecha = Math.max(1, Math.ceil(recientes.length / 6));
  const precio = (v: number) => PRECIO.format(v);
  const fecha = (v: VelaOHLC) => intradia ? horaLocal(new Date(v.open_time).toISOString()) : new Date(v.open_time).toISOString().slice(0, 10);
  const linea = (valores: (number | null | undefined)[], escala: (v: number) => number) =>
    valores.flatMap((v, i) => (v == null ? [] : [`${xDe(i).toFixed(1)},${escala(v).toFixed(1)}`])).join(' ');
  const conBanda = bandas.flatMap((b, i) => (b ? [{ i, b }] : []));
  const atipicos = recientes.flatMap((v, i) => {
    const b = bandas[i];
    return b && (v.close > b.sup || v.close < b.inf) ? [{ i, v, arriba: v.close > b.sup }] : [];
  });
  const ultimoRsi = [...fuerza].reverse().find(v => v != null);
  const ultimoMacd = [...impulso].reverse().find(v => v != null);
  const yR = (v: number) => 104 - v * .92;
  const escalaMacd = Math.max(...impulso.flatMap(m => (m ? [Math.abs(m.macd), Math.abs(m.senal), Math.abs(m.hist)] : [])), 1e-12);
  const yM = (v: number) => 62 - v / escalaMacd * 50;
  // ATR y volatilidad: escala propia del mínimo (abajo, y = 82) al máximo (arriba, y = 12) de lo visible
  const escalaLibre = (valores: (number | null)[]) => {
    const vistos = valores.filter((v): v is number => v != null);
    const lo = vistos.length ? Math.min(...vistos) : 0, hi = vistos.length ? Math.max(...vistos) : 1;
    return { lo, hi, y: (v: number) => 82 - (v - lo) / (hi - lo || 1) * 70, ultimo: vistos[vistos.length - 1] };
  };
  const eAtr = escalaLibre(rango), eVol = escalaLibre(vol20);
  const ultima = recientes.length - 1;
  // Primera y última fecha en las orillas; las intermedias, centradas y solo si no chocan con ellas (una fecha mide unas 60 unidades).
  const ejeFechas = (alto: number) => recientes.map((v, i) => ok[i] && (i === 0 || i === ultima || (i % cadaFecha === 0 && xDe(i) - xDe(0) > 105 && xDe(ultima) - xDe(i) > 105))
    && <text key={v.open_time} x={xDe(i)} y={alto} textAnchor={i === 0 ? 'start' : i === ultima ? 'end' : 'middle'} fill="var(--ceniza)" fontSize="10">{fecha(v)}</text>);
  const enVivo = enCurso ? ' en vivo' : '';
  // Lo que dice la cruz de la vela i: fecha, OHLC con su cambio y, con indicadores, el valor de cada uno en esa vela
  const lectura = (i: number): Lectura => {
    const v = recientes[i];
    if (!ok[i]) return { titulo: 'Vela inválida', filas: [] };
    const previo = i ? recientes[i - 1] : datos[inicio - 1];
    const cambio = previo ? v.close / previo.close - 1 : null;
    const filas: Lectura['filas'] = [['Apertura', precio(v.open)], ['Máximo', precio(v.high)], ['Mínimo', precio(v.low)],
      ['Cierre', `${precio(v.close)}${cambio == null ? '' : ` (${cambio >= 0 ? '+' : ''}${(cambio * 100).toFixed(2)} %)`}`, cambio == null ? undefined : cambio >= 0 ? 'positivo' : 'negativo']];
    const b = bandas[i], m = impulso[i], e = media20[i], r = fuerza[i], a = rango[i], s = vol20[i];
    if (b) filas.push(['Bollinger', `${precio(b.inf)} a ${precio(b.sup)}`, v.close > b.sup || v.close < b.inf ? 'aviso-alta' : 'cian'], ['SMA 20', precio(b.media), 'aviso-alta']);
    if (e != null) filas.push(['EMA 20', precio(e), 'azul']);
    if (r != null) filas.push(['RSI 14', r.toFixed(1), r > 70 || r < 30 ? 'aviso-alta' : undefined]);
    if (m) filas.push(['MACD histograma', precio(m.hist), m.hist >= 0 ? 'positivo' : 'negativo']);
    if (a != null) filas.push(['ATR 14', precio(a)]);
    if (s != null) filas.push(['Volatilidad 20', pct(s)]);
    return { titulo: `${fecha(v)}${enCurso && i === ultima ? ' · en curso, en vivo' : ''}`, filas };
  };

  return <figure className="grafica velas-terminal">
    <figcaption>
      <strong>{simbolo} · {NOMBRE[intervalo] ?? intervalo}</strong>
      <span className="leyenda">{recientes.length.toLocaleString('es-MX')} velas {intradia ? 'de MEXC · hora local' : `desde ${fecha(validas[0])} · UTC`}{enCurso ? (intradia ? ' · la vela en curso, en vivo' : ' · la de hoy, en vivo') : ''}</span>
    </figcaption>
    <div className="velas-desplazamiento" ref={desplazamiento}>
     <div className="velas-lienzo" ref={lienzo}>
      <svg ref={svgPrecio} viewBox="0 0 780 310" role="img" aria-label={`${NOMBRE[intervalo] ?? 'Velas'} de ${simbolo}${indicadores ? ' con bandas de Bollinger y cierres atípicos marcados' : ''}. Verde: cierre mayor o igual a apertura; rojo: cierre menor. Datos en la tabla inferior.`}>
        {[0, 1, 2, 3, 4].map(i => { const valor = inferior + (superior - inferior) * i / 4; return <g key={i}>
          <line x1={X0} x2="685" y1={y(valor)} y2={y(valor)} stroke="var(--polvo-suave)" />
          {/* El rótulo es una posición del eje, no un dato de MEXC: va con los decimales del resto del panel; la tabla conserva toda la precisión */}
          <text x="695" y={y(valor) + 4} fill="var(--ceniza)" fontSize="11">{precioEje(valor)}</text>
        </g>; })}
        {conBanda.length > 1 && <g className="bandas-bollinger">
          <path d={`M${conBanda.map(p => `${xDe(p.i).toFixed(1)},${y(p.b.sup).toFixed(1)}`).join(' L')} L${[...conBanda].reverse().map(p => `${xDe(p.i).toFixed(1)},${y(p.b.inf).toFixed(1)}`).join(' L')} Z`} fill="rgba(95, 208, 226, .07)" />
          <polyline points={linea(bandas.map(b => b?.sup), y)} fill="none" stroke="rgba(95, 208, 226, .6)" strokeWidth="1" />
          <polyline points={linea(bandas.map(b => b?.inf), y)} fill="none" stroke="rgba(95, 208, 226, .6)" strokeWidth="1" />
          <polyline points={linea(bandas.map(b => b?.media), y)} fill="none" stroke="var(--ambar)" strokeWidth="1" strokeDasharray="4 3" opacity=".75" />
          <polyline points={linea(media20, y)} fill="none" stroke="var(--azul)" strokeWidth="1.2" opacity=".85" />
        </g>}
        {recientes.map((v, i) => {
          if (!ok[i]) return null;
          const x = xDe(i), color = v.close >= v.open ? 'var(--positivo)' : 'var(--negativo)', hoy = enCurso && i === recientes.length - 1;
          return <g key={v.open_time} className={hoy ? 'vela-en-curso' : undefined}>
            <title>{`${fecha(v)}${hoy ? ' (en curso, en vivo)' : ''} · Apertura ${precio(v.open)} · Máximo ${precio(v.high)} · Mínimo ${precio(v.low)} · Cierre ${precio(v.close)}`}</title>
            <line x1={x} x2={x} y1={y(v.high)} y2={y(v.low)} stroke={color} />
            <rect x={x - grosor / 2} y={Math.min(y(v.open), y(v.close))} width={grosor} height={Math.max(1, Math.abs(y(v.open) - y(v.close)))} fill={color} />
          </g>;
        })}
        {atipicos.map(({ i, v, arriba }) => <circle key={`a${v.open_time}`} cx={xDe(i)} cy={arriba ? y(v.high) - 2 * punto - 1 : y(v.low) + 2 * punto + 1} r={punto} fill="var(--ambar)" stroke="var(--vacio)" strokeWidth="1">
          <title>{`${fecha(v)}: atípico, el cierre ${precio(v.close)} quedó ${arriba ? 'arriba de la banda superior' : 'debajo de la banda inferior'} de Bollinger`}</title>
        </circle>)}
        {ejeFechas(298)}
      </svg>
      {indicadores && <>
        <div className="indicador-cabeza"><strong>RSI 14</strong><span>{ultimoRsi == null ? 'sin dato' : ultimoRsi.toFixed(1) + enVivo}</span><small>arriba de 70: sobrecompra · abajo de 30: sobreventa</small></div>
        <svg viewBox="0 0 780 118" role="img" aria-label={`RSI de 14 días de ${simbolo}: ${ultimoRsi == null ? 'sin dato' : ultimoRsi.toFixed(1)}. Límites en 70 y 30.`}>
          <rect x={X0} y={yR(70)} width={ANCHO} height={yR(30) - yR(70)} fill="rgba(129, 184, 255, .05)" />
          {[70, 50, 30].map(n => <g key={n}>
            <line x1={X0} x2="685" y1={yR(n)} y2={yR(n)} stroke={n === 50 ? 'var(--polvo-suave)' : 'var(--polvo)'} strokeDasharray={n === 50 ? undefined : '4 4'} />
            <text x="695" y={yR(n) + 4} fill="var(--ceniza)" fontSize="11">{n}</text>
          </g>)}
          <polyline points={linea(fuerza, yR)} fill="none" stroke="var(--cian)" strokeWidth="1.6" />
          {fuerza.map((v, i) => v != null && (v > 70 || v < 30) && <circle key={i} cx={xDe(i)} cy={yR(v)} r={punto * .8} fill="var(--ambar)">
            <title>{`${fecha(recientes[i])}: RSI ${v.toFixed(1)}, ${v > 70 ? 'sobrecompra' : 'sobreventa'}`}</title>
          </circle>)}
        </svg>
        <div className="indicador-cabeza"><strong>MACD 12/26/9</strong><span>{ultimoMacd ? precioEje(ultimoMacd.hist) + enVivo : 'sin dato'}</span><small>barras: histograma · azul: MACD · ámbar: señal</small></div>
        <svg viewBox="0 0 780 120" role="img" aria-label={`MACD 12/26/9 de ${simbolo}; histograma ${ultimoMacd ? precioEje(ultimoMacd.hist) : 'sin dato'}.`}>
          <line x1={X0} x2="685" y1={yM(0)} y2={yM(0)} stroke="var(--polvo)" />
          <text x="695" y={yM(0) + 4} fill="var(--ceniza)" fontSize="11">0</text>
          {impulso.map((m, i) => m && <rect key={i} x={xDe(i) - grosor / 2} y={Math.min(yM(0), yM(m.hist))} width={grosor} height={Math.max(.5, Math.abs(yM(m.hist) - yM(0)))}
            fill={m.hist >= 0 ? 'var(--positivo)' : 'var(--negativo)'} opacity=".55"><title>{`${fecha(recientes[i])}: histograma ${precio(m.hist)}`}</title></rect>)}
          <polyline points={linea(impulso.map(m => m?.macd), yM)} fill="none" stroke="var(--azul)" strokeWidth="1.5" />
          <polyline points={linea(impulso.map(m => m?.senal), yM)} fill="none" stroke="var(--ambar)" strokeWidth="1.3" />
        </svg>
        <div className="indicador-cabeza"><strong>ATR 14</strong><span>{eAtr.ultimo == null ? 'sin dato' : precioEje(eAtr.ultimo) + enVivo}</span><small>rango verdadero promedio, en precio · con él el bot fija el stop y el tamaño de cada compra</small></div>
        <svg viewBox="0 0 780 92" role="img" aria-label={`ATR de 14 días de ${simbolo}: ${eAtr.ultimo == null ? 'sin dato' : precioEje(eAtr.ultimo)}.`}>
          {[eAtr.hi, eAtr.lo].map((v, k) => <g key={k}>
            <line x1={X0} x2="685" y1={eAtr.y(v)} y2={eAtr.y(v)} stroke="var(--polvo-suave)" />
            <text x="695" y={eAtr.y(v) + 4} fill="var(--ceniza)" fontSize="11">{precioEje(v)}</text>
          </g>)}
          <polyline points={linea(rango, eAtr.y)} fill="none" stroke="var(--flujo-propuesta)" strokeWidth="1.5" />
        </svg>
        <div className="indicador-cabeza"><strong>Volatilidad 20 días</strong><span>{eVol.ultimo == null ? 'sin dato' : pct(eVol.ultimo) + enVivo}</span><small>desviación de los últimos 20 rendimientos diarios</small></div>
        <svg viewBox="0 0 780 112" role="img" aria-label={`Volatilidad de 20 días de ${simbolo}: ${pct(eVol.ultimo)}.`}>
          {[eVol.hi, eVol.lo].map((v, k) => <g key={k}>
            <line x1={X0} x2="685" y1={eVol.y(v)} y2={eVol.y(v)} stroke="var(--polvo-suave)" />
            <text x="695" y={eVol.y(v) + 4} fill="var(--ceniza)" fontSize="11">{pct(v)}</text>
          </g>)}
          <polyline points={linea(vol20, eVol.y)} fill="none" stroke="var(--flujo-autorizacion)" strokeWidth="1.5" />
          {ejeFechas(106)}
        </svg>
      </>}
      <Cruz lienzo={lienzo} svgPrecio={svgPrecio} n={recientes.length} rangoY={[inferior, superior]} lectura={lectura} />
     </div>
    </div>
    <p className="leyenda">
      <span className="positivo">↑ Cierre ≥ apertura</span> · <span className="negativo">↓ Cierre &lt; apertura</span> · Mecha: mínimo–máximo
      {indicadores && <> · <span className="cian">Bandas de Bollinger 20 ± 2σ</span> · <span className="aviso-alta">SMA 20 punteada</span> · <span className="azul">EMA 20</span> · <span className="aviso-alta">● {atipicos.length} {atipicos.length === 1 ? 'cierre atípico' : 'cierres atípicos'}: fuera de las bandas</span></>}
    </p>
    {validas.length !== recientes.length && <p role="status">Hay velas inválidas; se muestran huecos, sin inventar precios.</p>}
    <details onToggle={e => setTabla(e.currentTarget.open)}><summary>Ver como tabla</summary>{tabla && <div className="tabla-scroll"><table><thead><tr><th>{intradia ? 'Hora local' : 'Fecha UTC'}</th><th>Apertura</th><th>Máximo</th><th>Mínimo</th><th>Cierre</th>
      {indicadores && <><th>Banda inferior</th><th>Banda superior</th><th>RSI</th><th>MACD</th><th>ATR</th><th>Volatilidad</th></>}</tr></thead><tbody>
      {recientes.map((v, i) => ok[i] && <tr key={v.open_time}><td>{fecha(v)}</td>{[v.open, v.high, v.low, v.close].map((n, j) => <td key={j}>{precio(n)}</td>)}
        {indicadores && <><td>{bandas[i] ? precio(bandas[i].inf) : '—'}</td><td>{bandas[i] ? precio(bandas[i].sup) : '—'}</td><td>{fuerza[i] == null ? '—' : fuerza[i].toFixed(1)}</td><td>{impulso[i] ? precio(impulso[i].macd) : '—'}</td>
          <td>{rango[i] == null ? '—' : precio(rango[i])}</td><td>{vol20[i] == null ? '—' : pct(vol20[i])}</td></>}</tr>)}
    </tbody></table></div>}</details>
  </figure>;
});
