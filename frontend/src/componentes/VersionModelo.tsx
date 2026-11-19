import { useDatos } from '../api';
interface Versiones { modelos: {version:string;tipo:string;activos:string[];horizonte:string;lookback:number;variables:string[];validado_entrega:boolean}[]; trabajos_pendientes:number; salidas:Record<string,{estado:string;motivo:string;demora_ms?:number}> }
export function VersionModelo() {
  const {datos,error}=useDatos<Versiones>('/api/modelos/versiones',2000);
  return <section className="observatorio"><h2>Versión del machine learning y salidas</h2>
    {error ? <p className="aviso-error" role="alert">No se pudo consultar el estado: {error}</p> : <>
    <div className="obs-resumen">{datos?.modelos.map(m=><div key={m.version}><small>ML · {m.tipo}</small><strong>{m.version}</strong><small>{m.activos.length} {m.activos.length === 1 ? 'activo' : 'activos'} · horizonte {m.horizonte}</small><small className={`tag ${m.validado_entrega?'tag-bien':'tag-atencion'}`}>{m.validado_entrega?'Validado en T4':'Desarrollo · validación final pendiente'}</small><details><summary>Detalles del modelo</summary><p>Ventana: {m.lookback} velas. Variables: {m.variables.join(', ')}.</p><p>{m.activos.join(', ')}</p></details></div>)}</div>
    <p>Salidas Paper prioritarias · {datos?.trabajos_pendientes ?? 0} revisiones en curso</p>
    <div className="tabla-scroll"><table className="tabla-salidas"><thead><tr><th>Activo</th><th>Salida</th><th>Motivo</th><th>Detección → cierre</th></tr></thead><tbody>{Object.entries(datos?.salidas??{}).map(([s,f])=><tr key={s}><td>{s}</td><td><span className={`etiqueta-estado s-${f.estado}`}>{f.estado.replaceAll('_',' ')}</span></td><td>{f.motivo}</td><td>{f.demora_ms==null?'—':`${f.demora_ms.toFixed(0)} ms`}</td></tr>)}</tbody></table></div>
    <small>Tiempo observado en simulación, no garantía de ejecución real. Detener el bot también desactiva las salidas automáticas. Sin liquidez suficiente, la posición permanece pendiente.</small>
    </>}
  </section>;
}
