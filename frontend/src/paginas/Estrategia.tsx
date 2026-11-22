import { useMemo, useState } from 'react';
import { useDatos } from '../api';
import { Lineas } from '../graficos/Lineas';
import { num, pct, pctSigno } from '../logica';
import { Observatorio } from '../componentes/Observatorio';
import { VersionModelo } from '../componentes/VersionModelo';
import { type Avanzados, ModelosInvestigacion } from '../componentes/ModelosInvestigacion';

interface Lab {
  modelo: { version: string; nombre?: string; tipo: string; umbral: number; filtro: string; variables: string[]; valido_para_entrega?: boolean } | null;
  seleccion: {
    regla: { umbral: number; filtro: string; rendimiento: number; drawdown: number; operaciones: number; win_rate: number | null; costos: number };
    metricas_va: { RMSE: number; MAE: number; direccional: number | null; R2: number | null; sesgo_modelo: number | null };
    rmse_cero_va: number;
    comprar_y_mantener_va: { rendimiento: number; drawdown: number };
    periodo_va: [string, string];
    particion: { conjunto: string; ejemplos: number; primera_emision: string; ultima_emision: string; primer_objetivo: string; ultimo_objetivo: string }[];
  } | null;
  experimentos: Record<string, string>[];
  reglas: Record<string, string>[];
  diagnostico: { modelo: string; estrategia: string; mse: number; varianza: number; sesgo2_mas_ruido: number; reentrenamientos: number }[];
  curvas: Record<string, { loss: number[]; val_loss: number[] }>;
  ventanas: Record<string, string>[];
  conjunto: {
    version: string;
    nombre?: string;
    umbral: number;
    filtro: string;
    seleccion: Lab['seleccion'] & { activos?: number };
    por_activo: Record<string, string>[];
  } | null;
  avanzados?: Avanzados | null;
}

const n = (v: string | undefined) => (v === undefined || v === '' ? null : Number(v));

export function Estrategia() {
  const { datos: lab, error } = useDatos<Lab>('/api/laboratorio');
  const minimo = useDatos<{ filtro_minimo?: string }>('/api/config').datos?.filtro_minimo?.toUpperCase();  // el riesgo lo exige si la regla de VA no trae filtro
  const [curva, setCurva] = useState('');
  const claves = Object.keys(lab?.curvas ?? {});
  const elegida = curva || claves[0];
  const datosCurva = elegida ? lab?.curvas[elegida] : null;

  const experimentos = useMemo(() => [...(lab?.experimentos ?? [])].sort((a, b) => (n(a.RMSE_VA) ?? 9) - (n(b.RMSE_VA) ?? 9)), [lab]);
  const base = lab?.diagnostico?.find((d) => d.estrategia === 'Referencia');
  const maxVarianza = Math.max(1e-12, ...(lab?.diagnostico ?? []).map((d) => d.varianza));
  const s = lab?.seleccion;

  if (error) return <p className="aviso-error" role="alert">{error}</p>;
  if (!lab) return <p className="vacio">Leyendo el laboratorio…</p>; // sin esto, la carga se leía como «no hay modelo»
  if (!lab.modelo) return <><Observatorio /><p className="vacio">No hay un modelo cargado todavía. Genera uno con el notebook de Colab o con research/entrenar_cpu.py.</p></>;

  return (
    <>
      <VersionModelo />
      <Observatorio />
      <section className="titular">
        <div>
          <h2>Sistema elegido con validación</h2>
          <p className="cifra-media">{lab.modelo.nombre ?? lab.modelo.tipo}</p>
          <p className="cifra-nota">Compra si el pronóstico supera {pct(lab.modelo.umbral, 3)}{lab.modelo.filtro === 'sma20' ? ' y el cierre está sobre SMA20' : minimo ? ` y el precio está sobre su ${minimo} (filtro mínimo de riesgo; en validación se eligió sin filtro)` : ', sin filtro técnico'}.</p>
          <p className="cifra-nota">Variables: {lab.modelo.variables.join(', ')}. Ventana de 20 días.</p>
        </div>
        {s && (
          <dl className="lecturas">
            <div><dt>RMSE en validación</dt><dd>{num(Number(s.metricas_va.RMSE.toFixed(6)))}</dd><small>pronóstico cero: {num(Number(s.rmse_cero_va.toFixed(6)))}</small></div>
            <div><dt>Acierto de dirección</dt><dd>{s.metricas_va.direccional == null ? 'no definido' : pct(s.metricas_va.direccional, 1)}</dd><small>no equivale a operaciones ganadoras</small></div>
            <div><dt>Simulación en validación</dt><dd>{pctSigno(s.regla.rendimiento, 1)}</dd><small>comprar y mantener: {pctSigno(s.comprar_y_mantener_va.rendimiento, 1)}</small></div>
            <div><dt>Caída máxima</dt><dd>{pct(s.regla.drawdown, 1)}</dd><small>comprar y mantener: {pct(s.comprar_y_mantener_va.drawdown, 1)}</small></div>
          </dl>
        )}
      </section>

      {s && (
        <section>
          <h2>Por qué estas cifras no prometen nada</h2>
          <p className="explicacion">
            La validación ({s.periodo_va[0]} a {s.periodo_va[1]}) sirvió para elegir entre muchos modelos y reglas, y coincidió con un periodo alcista. Por eso el resultado es optimista. El conjunto de prueba sigue cerrado: solo se abre una vez, con el sistema congelado y entrenado en T4.
          </p>
          <div className="tabla-scroll">
            <table>
              <thead><tr><th>Conjunto</th><th>Ejemplos</th><th>Primera emisión</th><th>Última emisión</th><th>Primer objetivo</th><th>Último objetivo</th></tr></thead>
              <tbody>{s.particion.map((p) => <tr key={p.conjunto}><td>{p.conjunto}</td><td>{p.ejemplos}</td><td>{p.primera_emision}</td><td>{p.ultima_emision}</td><td>{p.primer_objetivo}</td><td>{p.ultimo_objetivo}</td></tr>)}</tbody>
            </table>
          </div>
        </section>
      )}

      {lab.conjunto?.seleccion && (
        <section>
          <h2>Modelo conjunto de los demás activos</h2>
          <p className="explicacion">
            {lab.conjunto.nombre}: se entrena con todos los activos juntos y usa el mismo umbral de {pct(lab.conjunto.umbral, 2)}{lab.conjunto.filtro === 'sma20' ? ' con filtro SMA20' : minimo ? ` sin filtro técnico en validación; el control de riesgo le exige el filtro mínimo ${minimo}` : ' sin filtro técnico'}. Simulación de la cartera a cupos iguales en validación: {pctSigno(lab.conjunto.seleccion.regla.rendimiento, 1)} con caída de {pct(lab.conjunto.seleccion.regla.drawdown, 1)}; comprar y mantener la canasta: {pctSigno(lab.conjunto.seleccion.comprar_y_mantener_va.rendimiento, 1)} con caída de {pct(lab.conjunto.seleccion.comprar_y_mantener_va.drawdown, 1)}. Los activos se eligieron por su volumen de hoy, lo que favorece a los sobrevivientes: esta cifra es optimista.
          </p>
          <div className="tabla-scroll tabla-alta">
            <table>
              <thead><tr><th>Activo</th><th>Ejemplos VA</th><th>RMSE</th><th>RMSE pronóstico cero</th><th>Dirección</th><th>Rendimiento</th><th>Comprar y mantener</th><th>Caída</th><th>Operaciones</th></tr></thead>
              <tbody>
                {[...lab.conjunto.por_activo].sort((a, b) => Number(b.rendimiento) - Number(a.rendimiento)).map((a) => (
                  <tr key={a.simbolo}>
                    <td>{a.simbolo.replace('USDT', '')}</td><td>{a.ejemplos}</td><td>{Number(a.RMSE).toFixed(5)}</td><td>{Number(a.RMSE_cero).toFixed(5)}</td><td>{a.direccional ? pct(Number(a.direccional), 1) : 'no definido'}</td>
                    <td>{pctSigno(Number(a.rendimiento), 1)}</td><td>{pctSigno(Number(a.comprar_y_mantener), 1)}</td><td>{pct(Number(a.drawdown), 1)}</td><td>{a.operaciones}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section>
        <h2>Sesgo y varianza, medidos con estos datos</h2>
        <p className="explicacion">
          Error total = sesgo² + varianza + ruido irreducible. La varianza se mide de verdad: es cuánto cambian las predicciones al reentrenar. El sesgo² y el ruido se reportan juntos, porque con precios reales nadie conoce la función verdadera.
        </p>
        {lab.diagnostico.length === 0 ? <p className="vacio">Sin diagnóstico en este modelo.</p> : (
          <div className="tabla-scroll">
            <table>
              <thead><tr><th>Táctica</th><th>Modelo</th><th>Error total frente a la base</th><th>Varianza</th><th>Sesgo² + ruido</th><th>Reentrenos</th></tr></thead>
              <tbody>
                {lab.diagnostico.map((d) => (
                  <tr key={d.modelo}>
                    <td>{d.estrategia}</td>
                    <td>{d.modelo}</td>
                    <td>{base ? pctSigno(d.mse / base.mse - 1, 2) : d.mse.toExponential(3)}</td>
                    <td>
                      <span className="barra-celda"><i style={{ width: `${(d.varianza / maxVarianza) * 100}%` }} /></span>
                      {d.varianza.toExponential(2)}
                    </td>
                    <td>{d.sesgo2_mas_ruido.toExponential(3)}</td>
                    <td>{d.reentrenamientos}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {lab.avanzados && <ModelosInvestigacion datos={lab.avanzados} />}

      <section>
        <h2>Experimentos</h2>
        <p className="explicacion">De menor a mayor error en validación. Pronóstico cero y regresión lineal son las referencias que el modelo profundo tendría que superar.</p>
        <div className="tabla-scroll tabla-alta">
          <table>
            <thead><tr><th>Etapa</th><th>Variables</th><th>Modelo</th><th>Configuración</th><th>Semilla</th><th>RMSE TR</th><th>RMSE VA</th><th>MAE VA</th><th>Dirección VA</th><th>Dispositivo</th></tr></thead>
            <tbody>
              {experimentos.map((e, i) => (
                <tr key={i}>
                  <td>{e.capitulo ? Number(e.capitulo) - 6 : ''}</td><td>{e.variables}</td><td>{e.modelo}</td><td className="celda-config">{e.configuracion}</td><td>{e.semilla ? Math.round(Number(e.semilla)) : 'no aplica'}</td>
                  <td>{n(e.RMSE_TR)?.toFixed(6) ?? 'sin dato'}</td><td>{n(e.RMSE_VA)?.toFixed(6) ?? 'sin dato'}</td><td>{n(e.MAE_VA)?.toFixed(6) ?? 'sin dato'}</td>
                  <td>{e.direccional_VA ? pct(Number(e.direccional_VA), 1) : 'no definido'}</td><td>{e.dispositivo}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {lab.ventanas.length > 0 && (
        <section>
          <h2>Validación con ventanas expansivas dentro de entrenamiento</h2>
          <p className="explicacion">Cada entrenamiento termina antes del bloque que evalúa. Sirve para ver si el resultado depende de un solo periodo favorable.</p>
          <div className="tabla-scroll tabla-alta">
            <table>
              <thead><tr><th>Variables</th><th>Ventana</th><th>Bloque</th><th>Modelo</th><th>RMSE</th><th>MAE</th><th>Dirección</th></tr></thead>
              <tbody>
                {lab.ventanas.map((v, i) => (
                  <tr key={i}><td>{v.variables}</td><td>{v.ventana}</td><td>{v.bloque_desde} a {v.bloque_hasta}</td><td>{v.modelo}</td><td>{Number(v.RMSE).toFixed(5)}</td><td>{Number(v.MAE).toFixed(5)}</td><td>{v.direccional ? pct(Number(v.direccional), 1) : 'no definido'}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {datosCurva && (
        <section>
          <div className="fila-control">
            <label>
              Curva de aprendizaje
              <select value={elegida} onChange={(e) => setCurva(e.target.value)}>
                {claves.map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
            </label>
          </div>
          <Lineas
            titulo="Pérdida por época en entrenamiento y validación"
            etiquetas={datosCurva.loss.map((_, i) => `  ${i + 1}`)}
            series={[{ nombre: 'Entrenamiento', color: '#3D8BEB', valores: datosCurva.loss }, { nombre: 'Validación', color: '#C08226', valores: datosCurva.val_loss }]}
            formato={(v) => v.toFixed(3)}
            alto={230}
          />
        </section>
      )}

      {lab.reglas.length > 0 && (
        <section>
          <h2>Umbrales y filtro técnico probados en validación</h2>
          <p className="explicacion">El umbral no equivale a una probabilidad de acierto. Se elige por rendimiento neto; en empate, por menor caída.</p>
          <div className="tabla-scroll tabla-alta">
            <table>
              <thead><tr><th>Variables</th><th>Modelo</th><th>Umbral</th><th>Filtro</th><th>Rendimiento</th><th>Caída</th><th>Operaciones</th><th>Ganadoras</th></tr></thead>
              <tbody>
                {[...lab.reglas].sort((a, b) => Number(b.rendimiento) - Number(a.rendimiento)).slice(0, 40).map((r, i) => (
                  <tr key={i}><td>{r.variables}</td><td>{r.modelo}</td><td>{pct(Number(r.umbral), 2)}</td><td>{r.filtro}</td><td>{pctSigno(Number(r.rendimiento), 1)}</td><td>{pct(Number(r.drawdown), 1)}</td><td>{r.operaciones}</td><td>{r.win_rate ? pct(Number(r.win_rate), 0) : 'no definido'}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
