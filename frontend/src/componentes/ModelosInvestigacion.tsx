import { pct, pctSigno } from '../logica';

interface Metricas { RMSE: number; MAE: number; direccional: number | null }
interface Regla { rendimiento: number; drawdown: number; sharpe: number | null; operaciones: number }
interface Conjunto { ejemplos: number; desde: string; hasta: string }

export interface Avanzados {
  generado: string;
  conjuntos: { TR: Conjunto; SEL: Conjunto; EVAL: Conjunto };
  recurrentes: { elegida_por_validacion: string; filas: { modelo: string; parametros?: number; mejor_epoca?: number; medicion: Metricas; regla: Regla }[] };
  autoencoders: {
    elegido_por_validacion: string;
    referencia: { ridge_9_variables: Metricas; cero: Metricas };
    filas: { modelo: string; mse_reconstruccion_medicion: number; ridge_sobre_factores: Metricas }[];
  };
  generativos: { filas: { fuente: string; desviacion_diaria: number; var95_diario: number; cvar95_diario: number; media_16_dias: number; var95_16_dias: number; cvar95_16_dias: number; respuesta_a_la_volatilidad: number | null }[] };
  agente: {
    entrenamiento: { episodios: number; mejor_episodio: number };
    filas: { politica: string; rendimiento: number; drawdown: number; sharpe: number | null; sortino: number | null; dias_comprado: number; rotacion: number }[];
  };
}

const razon = (v: number | null | undefined) => (v == null ? 'sin dato' : v.toFixed(2));
const error = (v: number) => v.toFixed(5);
const direccion = (m: Metricas) => (m.direccional == null ? 'no definido' : pct(m.direccional, 1));

export function ModelosInvestigacion({ datos }: { datos: Avanzados }) {
  const { SEL, EVAL } = datos.conjuntos;
  return (
    <>
      <section>
        <h2>Modelos de investigación</h2>
        <p className="explicacion">
          Redes recurrentes, autoencoders, modelos generativos y un agente Double DQN, entrenados en CPU con BTC. Eligen épocas y arquitectura con la primera mitad de validación ({SEL.desde} a {SEL.hasta}) y se miden en la segunda ({EVAL.desde} a {EVAL.hasta}). El conjunto de prueba no se usó. Son simulaciones: el bot sigue decidiendo con el modelo entrenado en T4. Corrida del {datos.generado}.
        </p>
        <h3>Pronóstico del rendimiento del día siguiente</h3>
        <p className="explicacion">Regla simulada con cada pronóstico: comprar si supera 0.05 %, con 0.10 % de costo por lado. La validación eligió {datos.recurrentes.elegida_por_validacion}.</p>
        <div className="tabla-scroll">
          <table>
            <thead><tr><th>Modelo</th><th>Parámetros</th><th>Época elegida</th><th>RMSE</th><th>Dirección</th><th>Rendimiento de la regla</th><th>Caída</th><th>Sharpe</th><th>Operaciones</th></tr></thead>
            <tbody>
              {datos.recurrentes.filas.map((f) => (
                <tr key={f.modelo}>
                  <td>{f.modelo}</td><td>{f.parametros ?? 'no aplica'}</td><td>{f.mejor_epoca ?? 'no aplica'}</td><td>{error(f.medicion.RMSE)}</td><td>{direccion(f.medicion)}</td>
                  <td>{pctSigno(f.regla.rendimiento, 1)}</td><td>{pct(f.regla.drawdown, 1)}</td><td>{razon(f.regla.sharpe)}</td><td>{f.regla.operaciones}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h3>Autoencoders: comprimir 9 variables en 3 factores</h3>
        <p className="explicacion">
          Reconstrucción de las variables del día y pronóstico con Ridge sobre los 3 factores. Referencias: Ridge con las 9 variables, RMSE {error(datos.autoencoders.referencia.ridge_9_variables.RMSE)}; pronóstico cero, {error(datos.autoencoders.referencia.cero.RMSE)}. La validación eligió {datos.autoencoders.elegido_por_validacion}.
        </p>
        <div className="tabla-scroll">
          <table>
            <thead><tr><th>Modelo</th><th>Error de reconstrucción (MSE)</th><th>RMSE con Ridge sobre los factores</th><th>Dirección</th></tr></thead>
            <tbody>
              {datos.autoencoders.filas.map((f) => (
                <tr key={f.modelo}><td>{f.modelo}</td><td>{f.mse_reconstruccion_medicion.toFixed(4)}</td><td>{error(f.ridge_sobre_factores.RMSE)}</td><td>{direccion(f.ridge_sobre_factores)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h3>Escenarios de 16 días generados según la volatilidad previa</h3>
        <p className="explicacion">Las colas de los escenarios frente a las ventanas reales de validación. «Respuesta a la volatilidad» es la correlación entre la volatilidad de las 20 sesiones previas y la de la ventana: cerca de la real, el modelo reacciona a la condición.</p>
        <div className="tabla-scroll">
          <table>
            <thead><tr><th>Fuente</th><th>Desviación diaria</th><th>VaR 95 % diario</th><th>CVaR 95 % diario</th><th>Media a 16 días</th><th>VaR 95 % a 16 días</th><th>CVaR 95 % a 16 días</th><th>Respuesta a la volatilidad</th></tr></thead>
            <tbody>
              {datos.generativos.filas.map((f) => (
                <tr key={f.fuente}>
                  <td>{f.fuente}</td><td>{pct(f.desviacion_diaria, 2)}</td><td>{pct(f.var95_diario, 2)}</td><td>{pct(f.cvar95_diario, 2)}</td><td>{pctSigno(f.media_16_dias, 1)}</td>
                  <td>{pct(f.var95_16_dias, 1)}</td><td>{pct(f.cvar95_16_dias, 1)}</td><td>{razon(f.respuesta_a_la_volatilidad)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h3>Agente Double DQN</h3>
        <p className="explicacion">
          Decide al cierre entre efectivo y comprado; la posición nueva empieza en la apertura siguiente y cada cambio paga 0.10 %. Sin ventas en corto, porque MEXC spot no las permite. {datos.agente.entrenamiento.episodios} episodios sobre entrenamiento; la validación eligió el episodio {datos.agente.entrenamiento.mejor_episodio}.
        </p>
        <div className="tabla-scroll">
          <table>
            <thead><tr><th>Política</th><th>Rendimiento</th><th>Caída</th><th>Sharpe</th><th>Sortino</th><th>Días comprado</th><th>Cambios por día</th></tr></thead>
            <tbody>
              {datos.agente.filas.map((f) => (
                <tr key={f.politica}>
                  <td>{f.politica}</td><td>{pctSigno(f.rendimiento, 1)}</td><td>{pct(f.drawdown, 1)}</td><td>{razon(f.sharpe)}</td><td>{razon(f.sortino)}</td><td>{pct(f.dias_comprado, 0)}</td><td>{f.rotacion.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
