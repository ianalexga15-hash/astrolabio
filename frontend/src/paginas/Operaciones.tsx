import { useEffect, useRef, useState } from 'react';
import { type Estado, type Orden, type Radar, useDatos } from '../api';
import { horaLocal, metricasOperaciones, num, pct, pctSigno, precio, resumenHistorial, tonoAltura, usd } from '../logica';
import { useNuevos } from '../movimiento';
import { ActivoCompacto } from '../componentes/IdentidadActivo';

const MOTIVO: Record<string, string> = { stop: 'Stop de pérdida', objetivo: 'Objetivo alcanzado', manual: 'Cierre manual', senal: 'Señal y condiciones cumplidas', decision: 'Decisión del ciclo' };
interface FilaHistorial {
  simbolo: string;
  compra: string;
  precio_compra: number;
  altura: number | null;
  etiqueta: string;
  estado: string;
  venta: string | null;
  precio_venta: number | null;
  motivo_venta: string | null;
  resultado: number | null;
  rendimiento: number | null;
  horas: number | null;
}

const NOMBRE_ORDEN: Record<string, string> = { ejecutada: 'Ejecutada en Paper', rechazada: 'Bloqueada', expirada: 'Expirada' };

export function Operaciones({ estado }: { estado: Estado | null }) {
  const { datos: ordenes, error } = useDatos<Orden[]>('/api/ordenes', 5000);
  const { datos: radar, error: errorRadar } = useDatos<Radar>('/api/radar', 2000);
  const { datos: historial, error: errorHistorial } = useDatos<FilaHistorial[]>('/api/historial', 10_000);
  const resumen = resumenHistorial(historial ?? []);
  const nuevas = useNuevos(ordenes);
  const tabla = useRef<HTMLDivElement>(null);
  const [aviso, setAviso] = useState<{ texto: string; arriba: boolean } | null>(null);
  const abiertas = (radar?.filas ?? []).filter((f) => (f.cantidad ?? 0) > 0);
  const abierto = new Map(abiertas.map((f) => [f.simbolo, f.resultado_abierto ?? 0]));
  const lista = [...(ordenes ?? [])].reverse().slice(0, 300);
  const metricas = metricasOperaciones(ordenes ?? []);

  useEffect(() => {
    // Solo órdenes Paper confirmadas y nuevas por identificador; la primera lectura no avisa.
    const confirmadas = (ordenes ?? []).filter((o) => nuevas.has(o.id) && o.estado === 'ejecutada');
    if (!confirmadas.length) return;
    const o = confirmadas[confirmadas.length - 1];
    setAviso({
      texto: confirmadas.length === 1 ? `Nueva ${o.lado === 'vender' ? 'venta' : 'compra'} Paper: ${o.simbolo?.replace('USDT', '')}` : `${confirmadas.length} órdenes Paper nuevas`,
      arriba: (tabla.current?.scrollTop ?? 0) > 0,
    });
  }, [nuevas, ordenes]);

  useEffect(() => {
    if (!aviso) return;
    const t = window.setTimeout(() => setAviso(null), 6000);
    return () => window.clearTimeout(t);
  }, [aviso]);

  const claseFila = (o: Orden) =>
    [o.estado === 'rechazada' ? 'fila-rechazada' : o.estado === 'expirada' ? 'fila-expirada' : '', nuevas.has(o.id) && o.estado === 'ejecutada' ? 'fila-nueva' : '']
      .filter(Boolean).join(' ') || undefined;

  return (
    <>
      <section className="historial">
        <h2>Historial de operaciones</h2>
        <p className="explicacion">Cada compra con su venta. La altura dice dónde compró dentro del rango del día anterior: 0 % es su mínimo y 100 % su máximo. Horas en tu hora local.</p>
        <dl className="lecturas">
          <div><dt>Compras</dt><dd>{resumen.compras}</dd><small>{resumen.cerradas === 1 ? '1 ya vendida' : `${resumen.cerradas} ya vendidas`}</small></div>
          <div><dt>Compró en baja</dt><dd className="positivo">{resumen.enBaja}</dd><small>en el tercio bajo del día anterior o por debajo</small></div>
          <div><dt>Compró en alta</dt><dd className="aviso-alta">{resumen.enAlta}</dd><small>en el tercio alto del día anterior o por encima</small></div>
          <div><dt>Resultado de las vendidas</dt><dd className={resumen.resultado >= 0 ? 'positivo' : 'negativo'}>{usd(resumen.resultado)}</dd><small>después de comisiones</small></div>
        </dl>
        {errorHistorial && <p className="aviso-error" role="alert">No se pudo leer el historial: {errorHistorial}</p>}
        {historial && historial.length > 0 && (
          <div className="tabla-scroll tabla-alta">
            <table className="tabla-historial">
              <thead><tr><th>Activo</th><th>Compra</th><th>Precio de compra</th><th>¿En alta o en baja?</th><th>Venta</th><th>Precio de venta</th><th>Motivo</th><th>Resultado</th><th>Duración</th></tr></thead>
              <tbody>
                {historial.map((h) => (
                  <tr key={`${h.simbolo}-${h.compra}`}>
                    <td><ActivoCompacto simbolo={h.simbolo} /></td>
                    <td>{horaLocal(h.compra)}</td>
                    <td>{precio(h.precio_compra)}</td>
                    <td>
                      <span className={`altura altura-${tonoAltura(h.etiqueta)}`}>{h.etiqueta}{h.altura != null && ` (${Math.round(h.altura * 100)} %)`}</span>
                      {/* Punto en el rango del día anterior: izquierda es su mínimo, derecha su máximo; fuera del rango queda en el borde. */}
                      {h.altura != null && <span className="rango-dia" aria-hidden="true"><i style={{ left: `${Math.min(100, Math.max(0, h.altura * 100))}%` }} /></span>}
                    </td>
                    <td>{h.estado === 'abierta' ? <span className="tenue">abierta</span> : horaLocal(h.venta)}</td>
                    <td>{h.precio_venta == null ? '' : precio(h.precio_venta)}</td>
                    <td>{h.motivo_venta ? MOTIVO[h.motivo_venta] ?? h.motivo_venta : ''}</td>
                    <td className={h.resultado == null ? 'tenue' : h.resultado >= 0 ? 'positivo' : 'negativo'}>
                      {h.resultado != null ? `${usd(h.resultado)} (${pctSigno(h.rendimiento)})` : abierto.has(h.simbolo)
                        ? <><span className={(abierto.get(h.simbolo) ?? 0) >= 0 ? 'positivo' : 'negativo'}>{pctSigno(abierto.get(h.simbolo))}</span> sin cerrar</>
                        : 'sin cerrar'}
                    </td>
                    <td>{h.horas == null ? '' : `${h.horas.toFixed(1)} h`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2>Posiciones abiertas{radar && `: ${abiertas.length}`}</h2>
        {errorRadar && <p className="aviso-error" role="alert">No se pudieron leer las posiciones: {errorRadar}</p>}
        {!radar ? !errorRadar && <p className="vacio">Leyendo las posiciones…</p> : abiertas.length === 0 ? (
          <p className="explicacion">Sin posiciones abiertas. Efectivo disponible en la cartera: {usd(estado?.cartera?.efectivo)}.</p>
        ) : (
          <div className="tabla-scroll">
            <table className="tabla-posiciones">
              <thead><tr><th>Activo</th><th>Cantidad</th><th>Entrada</th><th>Precio ahora</th><th>Resultado sin cerrar</th><th>Stop de pérdida</th><th>Objetivo</th><th>Valor</th></tr></thead>
              <tbody>
                {abiertas.map((f) => (
                  <tr key={f.simbolo}>
                    <td><ActivoCompacto simbolo={f.simbolo} /></td><td>{num(f.cantidad)}</td><td>{precio(f.entrada)}</td><td>{precio(f.bid)}</td>
                    <td className={(f.resultado_abierto ?? 0) >= 0 ? 'positivo' : 'negativo'}>{pctSigno(f.resultado_abierto)}</td>
                    <td>{precio(f.stop)}</td><td>{precio(f.objetivo)}</td><td>{usd(f.valor)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2>Operaciones cerradas{ordenes && `: ${metricas.cerradas}`}</h2>
        {!ordenes ? !error && <p className="vacio">Leyendo las órdenes…</p> : metricas.cerradas === 0 ? (
          <p className="explicacion">Todavía no hay operaciones cerradas en vivo: {metricas.abiertas === 1 ? 'la posición sigue abierta' : `las ${metricas.abiertas} posiciones siguen abiertas`}.</p>
        ) : (
          <dl className="lecturas">
            <div><dt>Acierto</dt><dd>{pct(metricas.acierto, 0)}</dd><small>con resultado positivo</small></div>
            <div><dt>Factor de beneficio</dt><dd>{metricas.factorBeneficio == null ? 'sin pérdidas' : metricas.factorBeneficio.toFixed(2)}</dd><small>ganancias entre pérdidas</small></div>
            <div><dt>Resultado neto</dt><dd className={metricas.resultadoNeto >= 0 ? 'positivo' : 'negativo'}>{usd(metricas.resultadoNeto)}</dd><small>después de comisiones</small></div>
            <div><dt>Duración media</dt><dd>{metricas.duracionMediaH == null ? 'sin dato' : `${metricas.duracionMediaH.toFixed(1)} h`}</dd><small>de la compra a la venta</small></div>
          </dl>
        )}
        {metricas.descuadres > 0 && <p className="aviso-error" role="alert">{metricas.descuadres} operaciones tienen un resultado que no cuadra con sus precios y comisiones.</p>}
      </section>

      <section>
        <h2>Órdenes simuladas</h2>
        <p className="explicacion">Ejecutada: la orden simulada ocurrió. Bloqueada: las reglas la rechazaron. Expirada: compra autorizada que no se ejecutó ese día. El motivo explica cada caso.</p>
        {aviso && (
          <p className="aviso-orden" role="status">
            {aviso.texto}
            {aviso.arriba && <button className="enlace" onClick={() => { tabla.current?.scrollTo({ top: 0 }); setAviso(null); }}>Ver arriba</button>}
          </p>
        )}
        {error && <p className="aviso-error" role="alert">{error}</p>}
        {lista.length === 0 ? (
          <p className="vacio">Sin órdenes todavía. El reflejo compra solo cuando un activo autorizado cumple todas sus condiciones.</p>
        ) : (
          <div className="tabla-scroll tabla-alta" ref={tabla}>
            <table className="tabla-ordenes">
              <thead><tr><th>Fecha</th><th>Activo</th><th>Lado</th><th>Cantidad</th><th>Precio</th><th>Comisión</th><th>Resultado neto</th><th>Estado</th><th>Costos supuestos</th><th>Motivo</th></tr></thead>
              <tbody>
                {lista.map((o) => (
                  <tr key={o.id} className={claseFila(o)}>
                    <td>{horaLocal(o.creado, true)}</td>
                    <td>{o.simbolo ? <ActivoCompacto simbolo={o.simbolo} /> : '—'}</td>
                    <td><span className={`lado lado-${o.lado}`}>{o.lado}</span></td>
                    <td>{o.estado !== 'ejecutada' ? 'no aplica' : num(o.cantidad)}</td>
                    <td>{o.estado !== 'ejecutada' ? 'no aplica' : precio(o.precio)}</td>
                    <td>{o.estado !== 'ejecutada' ? 'no aplica' : usd(o.comision)}</td>
                    <td className={o.resultado == null ? 'tenue' : o.resultado >= 0 ? 'positivo' : 'negativo'}>{o.resultado == null ? 'no aplica' : usd(o.resultado)}</td>
                    <td><span className={`etiqueta-estado o-${o.estado}`}>{NOMBRE_ORDEN[o.estado] ?? o.estado}</span></td>
                    <td className="tenue">{o.estado !== 'ejecutada' ? 'no aplica' : o.modelo_costos ?? 'sin registro'}</td>
                    <td>{MOTIVO[o.motivo] ?? o.motivo}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
