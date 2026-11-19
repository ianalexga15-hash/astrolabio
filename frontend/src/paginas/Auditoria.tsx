import { type Decision, useDatos } from '../api';
import { horaLocal, pct, pctSigno, precio } from '../logica';

interface ErrorBot {
  id: number;
  creado: string;
  etapa: string;
  error: string;
  causa: string;
  accion: string;
  resultado: string;
}

export function Auditoria() {
  const { datos: decisiones, error: errorDecisiones } = useDatos<Decision[]>('/api/decisiones', 20_000);
  const { datos: errores, error: errorBitacora } = useDatos<ErrorBot[]>('/api/errores', 20_000);
  const lista = [...(decisiones ?? [])].reverse();
  const rechazadas = lista.filter((d) => !d.aprobada).length;

  // «Sin errores» solo se afirma con la bitácora leída: si la lectura falla, se dice (documento de Alex, §14.3).
  return (
    <>
      <section>
        <h2>Decisiones</h2>
        <p className="explicacion">Cada vela procesada deja este registro: pronóstico, propuesta, control de riesgo y acción final.{decisiones && ` ${lista.length} decisiones, ${rechazadas} rechazadas por riesgo.`}</p>
        {errorDecisiones && <p className="aviso-error" role="alert">No se pudieron leer las decisiones: {errorDecisiones}</p>}
        {!decisiones ? !errorDecisiones && <p className="vacio">Leyendo las decisiones…</p> : lista.length === 0 ? <p className="vacio">Sin decisiones todavía.</p> : (
          <div className="tabla-scroll tabla-alta">
            <table className="tabla-decisiones">
              {/* Primero lo que Alex lee antes (§14.4): vela, activo, acción final, riesgo y motivo; después el detalle técnico */}
              <thead><tr><th>Vela</th><th>Activo</th><th>Acción final</th><th>Riesgo</th><th>Justificación o motivo</th><th>Precio</th><th>Pronóstico</th><th>Umbral</th><th>Señal</th><th>Propuesta</th><th>Origen</th></tr></thead>
              <tbody>
                {lista.map((d) => {
                  const motivos: string[] = JSON.parse(d.motivos || '[]');
                  return (
                    <tr key={d.id} className={d.aprobada ? '' : 'fila-rechazada'}>
                      <td>{d.fecha_vela}</td>
                      <td>{d.simbolo?.replace('USDT', '')}</td>
                      <td><span className={`tag accion-${d.accion_final}`}>{d.accion_final}</span></td>
                      <td><span className={`tag ${d.aprobada ? 'tag-bien' : 'tag-mal'}`}>{d.aprobada ? 'Aprobó' : 'Rechazó'}</span></td>
                      {/* Dos líneas a la vista; un clic despliega el texto completo, que nunca se recorta en el documento */}
                      <td className="celda-texto"><details className="texto-largo"><summary>{motivos.length ? motivos.join(' ') : d.justificacion}</summary></details></td>
                      <td>{precio(d.precio)}</td>
                      <td>{pctSigno(d.pronostico, 3)}</td>
                      <td>{pct(d.umbral, 3)}</td>
                      <td>{d.senal ? 'Sí' : 'No'}</td>
                      <td>{d.accion_propuesta}</td>
                      <td>{d.origen === 'llm' ? d.llm_modelo : 'regla'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2>Bitácora de errores</h2>
        <p className="explicacion">Qué falló, por qué, qué hizo el bot y cómo terminó. Ante cualquier duda el bot no opera.</p>
        {errorBitacora && <p className="aviso-error" role="alert">No se pudo leer la bitácora de errores: {errorBitacora}</p>}
        {!errores ? !errorBitacora && <p className="vacio">Leyendo la bitácora…</p> : errores.length === 0 ? <p className="vacio">Sin errores registrados.</p> : (
          <div className="tabla-scroll tabla-alta">
            <table className="tabla-errores">
              <thead><tr><th>Fecha</th><th>Etapa</th><th>Error</th><th>Causa</th><th>Acción correctiva</th><th>Resultado</th></tr></thead>
              <tbody>
                {[...errores].reverse().map((e) => (
                  <tr key={e.id}><td>{horaLocal(e.creado, true)}</td><td><code>{e.etapa}</code></td><td className="celda-texto">{e.error}</td><td><code>{e.causa}</code></td><td className="celda-texto">{e.accion}</td><td>{e.resultado}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
