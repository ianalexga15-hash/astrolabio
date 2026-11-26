import { useEffect, useState } from 'react';
import { useDatos } from '../api';
import { fechaHora } from '../logica';
import '../observatorio.css';

type Ficha = { id: number; run: string; creado: string; modelo_version: string; pronostico: number; umbral: number; accion_propuesta: string; accion_final: string; motivos: string; ordenes: Orden[] };
type Orden = { id: number; run?: string; lado: string; estado: string; precio: number; cantidad: number; comision: number; motivo: string; modelo_costos: string | null };
type Captura = { id: number; ts: number; ultimo_libro_ms: number; radar: Record<string, { bid?: number; ask?: number; estado?: string; bot?: string; cantidad?: number; pronostico?: number; condiciones?: { nombre: string; cumple: boolean; detalle: string }[] }> };
interface Datos {
  estado: string; error: string | null; politica: string;
  captura: { n: number; desde: number | null; hasta: number | null };
  datos: { edad_s: number | null; alerta: boolean };
  salud: { aviso: string; filas: { modelo: string; tr: number; va: number; brecha: number; razon: number | null }[] };
  concentracion: { pares: { a: string; b: string; correlacion: number; n: number }[]; pesos: Record<string, number>; exposicion: number; hhi: number; aviso?: string };
  sombra: { candidato: string; pendientes: number; error: string | null; comparacion: { simbolo: string; version: string; candidato: string; n: number; rmse: number; rmse_sombra: number }[] };
  deterioro: { simbolo: string; estado: string; n: number; mae_base?: number; mae_reciente?: number }[];
  fichas: { decisiones: Ficha[]; ordenes_sin_enlace: Orden[] };
}
const cifra = (v: number | null | undefined, dec = 4) => v == null ? '—' : v.toLocaleString('es-MX', { maximumFractionDigits: dec });
const fecha = (v: number | null) => v == null ? '—' : fechaHora(v);

export function Observatorio() {
  const { datos, error } = useDatos<Datos>('/api/observatorio', 15000);
  const [capturas, setCapturas] = useState<Captura[]>([]);
  const [indice, setIndice] = useState(0);
  const [reproduciendo, setReproduciendo] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [fallo, setFallo] = useState('');
  const [activo, setActivo] = useState('');
  useEffect(() => {
    if (!reproduciendo) return;
    const timer = window.setInterval(() => setIndice(i => {
      if (i + 1 >= capturas.length) { setReproduciendo(false); return i; }
      return i + 1;
    }), 1000);
    return () => clearInterval(timer);
  }, [reproduciendo, capturas.length]);
  const cargar = async (siguiente = false) => {
    setReproduciendo(false); setOcupado(true); setFallo('');
    try {
      const cursor = siguiente ? capturas.at(-1)?.id ?? 0 : 0;
      const r = await fetch(`/api/observatorio/replay?despues=${cursor}&limite=100`, { credentials: 'same-origin' });
      if (!r.ok) throw new Error('No se pudieron cargar las capturas.');
      const filas: Captura[] = await r.json();
      setCapturas(filas); setIndice(0);
    } catch (e) { setFallo((e as Error).message); }
    finally { setOcupado(false); }
  };
  const captura = capturas[indice];
  const simbolo = activo || Object.keys(captura?.radar ?? {})[0];
  const fila = captura?.radar[simbolo];
  if (error) return <section className="observatorio"><h2>Observatorio</h2><p className="aviso-error" role="alert">No disponible: {error}</p></section>;
  if (!datos) return <section className="observatorio"><h2>Observatorio</h2><p>Cargando evidencia…</p></section>;
  return <section className="observatorio">
    <div className="obs-titulo"><div><h2>Observatorio del modelo</h2></div><span className="chip">Solo observación · Paper</span></div>
    <div className="obs-resumen">
      <div><small>Datos de mercado</small><strong>{datos.datos.alerta ? 'Revisar conexión' : 'Recientes'}</strong><small>Edad: {cifra(datos.datos.edad_s, 1)} s</small></div>
      <div><small>Sesión registrada</small><strong>{datos.captura.n.toLocaleString()} capturas</strong><small>{fecha(datos.captura.hasta)}</small></div>
      <div><small>Modelo en sombra</small><strong>{datos.sombra.candidato}</strong><small>{datos.sombra.pendientes} resultados pendientes</small></div>
      <div><small>Exposición observada</small><strong>{cifra(datos.concentracion.exposicion * 100, 1)} %</strong><small>Sin cambios automáticos de límites</small></div>
    </div>
    {datos.error && <p className="aviso-error" role="alert">{datos.error}</p>}
    <details><summary>Salud del modelo · entrenamiento frente a validación</summary>
      <p>{datos.salud.aviso}</p>
      <div className="tabla-scroll"><table><thead><tr><th>Modelo</th><th>RMSE TR</th><th>RMSE VA</th><th>Brecha VA − TR</th></tr></thead><tbody>{datos.salud.filas.map((f,i)=><tr key={i}><td>{f.modelo}</td><td>{cifra(f.tr,6)}</td><td>{cifra(f.va,6)}</td><td>{cifra(f.brecha,6)}</td></tr>)}</tbody></table></div>
      {!datos.salud.filas.length && <p>Sin métricas comparables. Las curvas y baselines originales siguen disponibles debajo.</p>}
      <p>Errores altos en ambos conjuntos pueden indicar subajuste; una brecha grande puede indicar sobreajuste o cambio de distribución. Comparar también con los baselines y ventanas temporales de esta página.</p>
    </details>
    <details><summary>Comparador en sombra · sin ejecutar órdenes</summary>
      <p>Predicciones registradas cerca del cierre diario y evaluadas únicamente cuando madura su objetivo. Comparación de error predictivo; no es rentabilidad ni autorización para sustituir el modelo.</p>
      {datos.sombra.error && <p className="aviso-error" role="alert">{datos.sombra.error}</p>}
      <div className="tabla-scroll"><table><thead><tr><th>Activo</th><th>Modelo / candidato</th><th>Días evaluados</th><th>RMSE activo</th><th>RMSE sombra</th></tr></thead><tbody>{datos.sombra.comparacion.map(f=><tr key={`${f.simbolo}:${f.version}:${f.candidato}`}><td>{f.simbolo}</td><td>{f.version} / {f.candidato}</td><td>{f.n}</td><td>{cifra(f.rmse,6)}</td><td>{cifra(f.rmse_sombra,6)}</td></tr>)}</tbody></table></div>
      {!datos.sombra.comparacion.length && <p>Aún no hay resultados maduros. No se rellena el pasado ni se abre TE.</p>}
    </details>
    <details><summary>Concentración · activos que se mueven juntos</summary>
      <div className="obs-pesos">{Object.entries(datos.concentracion.pesos).map(([s,p])=><div key={s}><span>{s}</span><meter min="0" max="1" value={p} aria-label={`Exposición ${s}`} /><span>{cifra(p*100,1)} %</span></div>)}</div>
      <p>{datos.concentracion.aviso || 'Esperando historia diaria.'}</p>
      <div className="tabla-scroll"><table><thead><tr><th>Par</th><th>Correlación</th><th>Días comunes</th></tr></thead><tbody>{datos.concentracion.pares.map(p=><tr key={p.a+p.b}><td>{p.a} / {p.b}</td><td>{cifra(p.correlacion,2)}</td><td>{p.n}</td></tr>)}</tbody></table></div>
    </details>
    <details><summary>Deterioro · datos y resultados nuevos</summary>
      <p>Compara MAE de los últimos 30 días evaluados con los 30 anteriores por activo y versión. Avisa si crece más de 50 %. Es un indicador descriptivo, no una prueba estadística ni un bloqueo automático.</p>
      {datos.deterioro.length ? <ul>{datos.deterioro.map((f,i)=><li key={i}>{f.simbolo}: {f.estado === 'evidencia_insuficiente' ? `Evidencia insuficiente (${f.n}/60)` : f.estado === 'revisar' ? 'Revisar deterioro' : 'Sin alerta en esta comparación'}</li>)}</ul> : <p>Esperando predicciones maduras; los ticks repetidos no cuentan como días nuevos.</p>}
    </details>
    <details><summary>Grabador y reproducción de sesiones</summary>
      <p>Reproducción observacional, una captura por paso. No ejecuta órdenes ni reconstruye fills; puede haber intervalos perdidos. Retención máxima: 86 400 capturas.</p>
      <div className="controles"><button disabled={ocupado} onClick={()=>cargar()}>Abrir grabación</button><button disabled={ocupado || !capturas.length} onClick={()=>cargar(true)}>Siguiente bloque</button><button disabled={!capturas.length} onClick={()=>setReproduciendo(!reproduciendo)}>{reproduciendo ? 'Pausar reproducción' : 'Reproducir'}</button></div>
      {fallo && <p className="aviso-error" role="alert">{fallo}</p>}
      {captura && <><label>Captura {indice+1} de {capturas.length}<input type="range" min="0" max={capturas.length-1} value={indice} onChange={e=>{setReproduciendo(false);setIndice(Number(e.target.value));}} /></label><p>{fecha(captura.ts)} · dato de mercado: {fecha(captura.ultimo_libro_ms)}</p><label>Activo<select value={simbolo} onChange={e=>setActivo(e.target.value)}>{Object.keys(captura.radar).map(s=><option key={s}>{s}</option>)}</select></label><p>{fila?.estado ?? 'Sin dato'} · Bid {cifra(fila?.bid)} · Ask {cifra(fila?.ask)} · Cantidad {cifra(fila?.cantidad)}</p><ul>{fila?.condiciones?.map((c,i)=><li key={i}>{c.cumple ? '✓' : '○'} {c.nombre}: {c.detalle}</li>)}</ul></>}
    </details>
    <details><summary>¿Por qué actuó? · evidencia de cada decisión</summary>
      {datos.fichas.decisiones.map(f=><details key={f.id}><summary>{f.run.replace('live:','')} · {f.accion_final} · {f.creado}</summary><p>Modelo {f.modelo_version} · pronóstico {cifra(f.pronostico,6)} · umbral {cifra(f.umbral,6)}</p><p>Propuesta: {f.accion_propuesta} → decisión: {f.accion_final}</p><p>{f.motivos}</p>{f.ordenes.map(o=><p key={o.id}>Paper #{o.id}: {o.lado} · {o.estado} · {o.motivo} · precio {cifra(o.precio)} · comisión {cifra(o.comision)} · costes: {o.modelo_costos || 'No registrado'}</p>)}{!f.ordenes.length && <p>Sin orden enlazada: una decisión no equivale a ejecución.</p>}</details>)}
      <h3>Órdenes sin enlace a decisión</h3><p>Incluye ejecuciones del reflejo. Se muestra el motivo registrado sin inventar una relación.</p>{datos.fichas.ordenes_sin_enlace.map(o=><p key={o.id}>#{o.id} {o.run} · {o.lado} · {o.estado} · {o.motivo} · precio {cifra(o.precio)} · comisión {cifra(o.comision)}</p>)}
    </details>
  </section>;
}
