import { Fragment, useMemo, useState } from 'react';
import { type Estado, type FilaRadar, type Radar as DatosRadar, useDatos } from '../api';
import { conexionActivos, pct, pctSigno, precio, usd } from '../logica';
import { Condicion, Controles } from './Mercado';
import { Icono } from '../Icono';
import { CifraViva, useCambio } from '../movimiento';
import { IdentidadActivo } from '../componentes/IdentidadActivo';

const NOMBRE: Record<string, string> = {
  en_posicion: 'En posición', armada: 'Compra armada', sin_senal: 'Sin compra hoy', dato_atrasado: 'Dato atrasado', esperando: 'Esperando precio',
  pausado: 'En pausa', detenido: 'Detenido', bloqueado: 'Bloqueado',
};
const ORDEN: Record<string, number> = { en_posicion: 0, armada: 1, sin_senal: 2, esperando: 3, pausado: 4, detenido: 5, bloqueado: 6, dato_atrasado: 7 };

// El contador abre el detalle en una fila completa debajo: la tabla no se ensancha ni saca de vista Stop y Objetivo.
function Condiciones({ fila, abierta, alternar }: { fila: FilaRadar; abierta: boolean; alternar: () => void }) {
  if (!fila.condiciones?.length) return <span className="tenue">no aplica</span>;
  return (
    <button className="condiciones-boton" aria-expanded={abierta} aria-controls={`condiciones-${fila.simbolo}`} onClick={alternar}
      aria-label={`${fila.simbolo}: ${fila.cumplidas} de ${fila.condiciones.length} criterios. ${abierta ? 'Ocultar' : 'Ver'} detalle`}>
      <span className="condiciones-fila">
        {fila.condiciones.map((c) => <i key={c.id} className={c.cumple ? 'cond-si' : 'cond-no'} aria-hidden="true" />)}
        <span>{fila.cumplidas} de {fila.condiciones.length}</span>
      </span>
    </button>
  );
}

export function Radar({ estado, recargar, alElegir }: { estado: Estado | null; recargar: () => void; alElegir: (s: string) => void }) {
  const { datos, error } = useDatos<DatosRadar>('/api/radar', 1000);
  const [filtro, setFiltro] = useState('todos');
  const [busqueda, setBusqueda] = useState('');
  const [abierta, setAbierta] = useState<string | null>(null);
  const filas = useMemo(() => {
    const lista = [...(datos?.filas ?? [])];
    lista.sort((a, b) => (ORDEN[a.estado] ?? 9) - (ORDEN[b.estado] ?? 9) || (b.pronostico ?? -9) - (a.pronostico ?? -9));
    return lista.filter((f) => (filtro === 'todos' || f.estado === filtro) && f.simbolo.toLowerCase().includes(busqueda.trim().toLowerCase()));
  }, [datos, filtro, busqueda]);
  const r = datos?.resumen;
  const e = datos?.estadisticas;
  const conexion = conexionActivos(datos?.filas ?? []);
  const edad = e?.ultimo_barrido_ms && datos?.servidor_ms ? (datos.servidor_ms - e.ultimo_barrido_ms) / 1000 : null;
  const barrido = useCambio(e?.ultimo_barrido_ms ?? null); // pulso solo cuando termina un barrido real

  return (
    <>
      <div className="titulo-vista">
        <div><h2>Radar de la cartera<span className="marca-punto">.</span></h2><p>Todo el mercado a la vista. Cada señal, bajo control.</p></div>
        <div className="titulo-acciones"><span className="cadencia"><Icono nombre="radar" />Barrido objetivo: 1 s</span><Controles estado={estado} recargar={recargar} /></div>
      </div>
      <dl className="lecturas">
        <div><dt>Patrimonio</dt><dd>{usd(r?.patrimonio)}</dd><small>{pctSigno(r?.rendimiento)} desde {usd(r?.capital_inicial)}</small></div>
        <div><dt>Posiciones abiertas</dt><dd>{r?.posiciones ?? 0} de {r?.activos ?? 0}</dd><small>{r?.armadas ?? 0} compras armadas</small></div>
        <div><dt>Exposición</dt><dd>{pct(r?.exposicion, 1)}</dd><small>cupo de {usd(r?.cupo)} por activo</small></div>
        <div><dt>Latencia del reflejo</dt><dd>{e ? `${e.latencia_ms.toFixed(2)} ms` : 'sin dato'}</dd><small>{e ? `p99 ${e.p99_ms.toFixed(2)} ms` : ''}</small></div>
        <div>
          <dt>Universo monitoreado</dt>
          <dd>{e?.activos ?? '—'} activos</dd>
          <small>{barrido.veces > 0 && <i key={barrido.veces} className="pulso-barrido" aria-hidden="true" />}{edad == null ? 'Esperando el primer barrido.' : `Última revisión hace ${Math.max(0, edad).toFixed(1)} s`}</small>
          <small>{e ? `${e.barridos.toLocaleString('es-MX')} barridos realizados` : 'Conectando con el radar'}</small>
          {datos && conexion.sinPrecio.length === 0 && <small>{conexion.conPrecio} de {conexion.total} con precio en vivo de MEXC</small>}
        </div>
      </dl>
      {datos && conexion.sinPrecio.length > 0 && <p className="aviso-error" role="alert">{conexion.conPrecio} de {conexion.total} con precio en vivo de MEXC. Sin precio: {conexion.sinPrecio.join(', ')}</p>}
      {(error || datos?.error) && <p className="aviso-error" role="alert">{error || `Sin precios de MEXC: ${datos?.error} Se reintenta solo; mientras tanto no se opera.`}</p>}
      {r?.bloqueo_entradas && <p className="aviso-atencion" role="alert">{r.bloqueo_entradas} No se abren posiciones nuevas; los stops siguen activos.</p>}
      {r?.aviso_capital && <p className="aviso-atencion" role="alert">{r.aviso_capital}</p>}
      {r && r.sin_modelo.length > 0 && <p className="aviso-atencion">{r.sin_modelo.length} activos sin modelo aprobado quedaron fuera de la cartera.</p>}

      <section className="panel-radar">
      <div className="radar-herramientas">
        <div className="filtros-radar" role="group" aria-label="Filtrar activos">
          {[['todos', 'Todos'], ['en_posicion', 'En posición'], ['armada', 'Armadas'], ['sin_senal', 'Sin compra hoy']].map(([valor, nombre]) => <button key={valor} aria-pressed={filtro === valor} className={filtro === valor ? 'seleccionado' : ''} onClick={() => setFiltro(valor)}>{nombre}<span>{valor === 'todos' ? datos?.filas.length ?? 0 : datos?.filas.filter((f) => f.estado === valor).length ?? 0}</span></button>)}
        </div>
        <label className="buscar-activo"><Icono nombre="buscar" size={17} /><input aria-label="Buscar activo" value={busqueda} onChange={(ev) => setBusqueda(ev.target.value)} placeholder="Buscar activo…" type="search" /></label>
      </div>
      <div className="tabla-scroll">
        <table className="tabla-radar">
          <thead>
            <tr><th>Activo</th><th>Estado</th><th>Precio</th><th>Spread</th><th>Pronóstico</th><th>Condiciones de compra</th><th>Resultado</th><th>Stop</th><th>Objetivo</th></tr>
          </thead>
          <tbody>
            {filas.map((f) => {
              const nombre = f.bot === 'detenido' || f.bot === 'pausado' || f.bot === 'bloqueado' ? f.bot : f.estado;
              return (
                <Fragment key={f.simbolo}>
                <tr className={`fila-${f.estado}`}>
                  <td><button className="activo-enlace" onClick={() => alElegir(f.simbolo)}><IdentidadActivo simbolo={f.simbolo} /><span><strong>{f.simbolo.replace('USDT', '')}</strong><small>USDT</small></span></button></td>
                  <td><span className={`etiqueta-estado r-${f.estado}`}>{NOMBRE[f.estado === 'en_posicion' || f.estado === 'armada' ? f.estado : nombre] ?? nombre}</span>{f.espera && <small>en espera a {precio(f.espera.precio)}</small>}</td>
                  <CifraViva valor={f.ask} texto={precio(f.ask)} />
                  <td>{f.spread_bps == null ? 'sin dato' : `${f.spread_bps.toFixed(1)} pb`}</td>
                  <td>{f.pronostico == null ? 'sin dato' : pctSigno(f.pronostico, 2)}</td>
                  <td><Condiciones fila={f} abierta={abierta === f.simbolo} alternar={() => setAbierta(abierta === f.simbolo ? null : f.simbolo)} /></td>
                  <td className={f.resultado_abierto == null ? 'tenue' : f.resultado_abierto >= 0 ? 'positivo' : 'negativo'}>{f.resultado_abierto == null ? 'no aplica' : pctSigno(f.resultado_abierto)}</td>
                  <td className={f.stop == null ? 'tenue' : 'nivel-stop'}>{f.stop == null ? 'no aplica' : precio(f.stop)}</td>
                  <td className={f.objetivo == null ? 'tenue' : 'nivel-objetivo'}>{f.objetivo == null ? 'no aplica' : precio(f.objetivo)}</td>
                </tr>
                {abierta === f.simbolo && f.condiciones?.length ? (
                  <tr className="fila-detalle">
                    <td colSpan={9} id={`condiciones-${f.simbolo}`}>
                      <ul className="condiciones">{f.condiciones.map((c) => <Condicion key={c.id} cumple={c.cumple} texto={c.nombre} detalle={c.detalle} />)}</ul>
                    </td>
                  </tr>
                ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {filas.length === 0 && <p className="vacio radar-vacio">{datos ? 'No hay activos que coincidan con estos filtros.' : 'Esperando los datos de la cartera…'}</p>}
      <div className="tabla-pie"><span>{filas.length} activos en esta vista</span><span>Modelo y Ollama autorizan al día. El reflejo revisa las condiciones cada segundo. · Precios de MEXC · Resultados Paper</span></div>
      </section>
      <details className="explicacion">
        <summary>Cómo decide el radar</summary>
        <p>Condiciones de compra: señal del día, filtro técnico, spread y costo de recorrer el libro, no perseguir el precio y riesgo. Las salidas se revisan con el stop, el objetivo y el stop móvil. Abre el contador de condiciones para ver qué cumple y qué falta. El pronóstico usa velas diarias: estos cinco criterios no equivalen a cinco indicadores de scalping intradía.</p>
      </details>
    </>
  );
}
