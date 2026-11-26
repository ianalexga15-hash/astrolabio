import { useMemo, useState } from 'react';
import { type Corrida, type Estado, useDatos } from '../api';
import { Lineas } from '../graficos/Lineas';
import { indexar100, num, pct, pctSigno, usd } from '../logica';

interface Marca {
  fecha: string;
  patrimonio: number;
  precio: number;
}

const NOMBRE_TIPO: Record<string, string> = { live: 'En vivo', replay: 'Replay histórico' };

export function Resumen({ estado }: { estado: Estado | null }) {
  const [run, setRun] = useState('live');
  const { datos: corridas, error: errorCorridas } = useDatos<Corrida[]>('/api/comparacion', 30_000);
  const { datos: marcas, error: errorMarcas } = useDatos<Marca[]>(`/api/patrimonio?run=${encodeURIComponent(run)}`, 30_000);
  const c = estado?.cartera;
  const actual = corridas?.find((r) => r.run === run);
  const vivo = corridas?.find((r) => r.run === 'live'); // la cabecera es la cartera en vivo; el selector solo cambia la gráfica

  const grafica = useMemo(() => {
    const lista = marcas ?? [];
    return {
      etiquetas: lista.map((m) => m.fecha),
      bot: indexar100(lista.map((m) => m.patrimonio)),
      pasivo: indexar100(lista.map((m) => m.precio)),
    };
  }, [marcas]);

  return (
    <>
      <section className="titular">
        <div>
          <h2>Patrimonio simulado de la cartera</h2>
          <p className="cifra-mayor">{usd(c?.patrimonio)}</p>
          <p className="cifra-nota">{pctSigno(c?.rendimiento)} desde {usd(c?.capital_inicial)} de capital virtual</p>
          {vivo?.salidos?.length ? (
            <p className="cifra-nota">
              No incluye {vivo.salidos.map((s) => `${s.simbolo.replace(/USDT$/, '')} (${s.operaciones} ${s.operaciones === 1 ? 'operación' : 'operaciones'}, ${usd(s.resultado)})`).join(', ')}: {vivo.salidos.length === 1 ? 'salió' : 'salieron'} de la cartera y su historial sigue en Operaciones.
            </p>
          ) : null}
        </div>
        <dl className="lecturas">
          <div><dt>Caída desde el máximo</dt><dd>{pct(c?.caida)}</dd></div>
          <div><dt>Posiciones abiertas</dt><dd>{c?.posiciones ?? 0} de {c?.activos ?? 0}</dd><small>exposición {pct(c?.exposicion, 1)}</small></div>
          <div><dt>Operaciones cerradas</dt><dd>{vivo?.operaciones ?? 'sin dato'}</dd></div>
          <div><dt>Ganadoras</dt><dd>{vivo?.win_rate == null ? 'no definido' : pct(vivo.win_rate, 0)}</dd></div>
          <div><dt>Costos pagados</dt><dd>{usd(c?.costos)}</dd></div>
        </dl>
      </section>

      <div className="fila-control">
        <label>
          Corrida
          <select value={run} onChange={(e) => setRun(e.target.value)}>
            {(corridas ?? []).map((r) => <option key={r.run} value={r.run}>{r.etiqueta || NOMBRE_TIPO[r.tipo] || r.run}</option>)}
          </select>
        </label>
        {actual?.tipo === 'replay' && <p className="dato-menor">Replay con datos históricos: no son observaciones nuevas de la conexión actual.</p>}
      </div>
      {errorMarcas && <p className="aviso-error" role="alert">No se pudo leer el patrimonio de esta corrida: {errorMarcas}</p>}
      {/* La serie del grupo vivo la calcula el servidor; aquí solo se dice que no tiene la misma base que la cabecera, sin ocultar ninguna cifra */}
      {vivo?.activos != null && c?.activos != null && vivo.activos !== c.activos && (
        <p className="aviso-atencion">La serie «En vivo» de la gráfica y de la tabla suma los {vivo.activos} agentes que pasaron por la cartera; la cabecera, los {c.activos} activos de hoy. Sus cifras no se pueden comparar entre sí.</p>
      )}

      <Lineas
        titulo="Patrimonio frente a comprar y mantener la canasta, base 100 al inicio"
        etiquetas={grafica.etiquetas}
        series={[{ nombre: 'Bot', color: '#3D8BEB', valores: grafica.bot }, { nombre: 'Comprar y mantener', color: '#C08226', valores: grafica.pasivo, punteada: true }]}
        formato={(v) => v.toFixed(1)}
        referencia={100}
      />

      <section>
        <h2>Comparación de corridas</h2>
        <p className="explicacion">Mismo periodo y costos dentro de cada replay. El rendimiento pasado no predice el futuro: sirve para saber si el LLM aporta algo frente a la regla sola. Sharpe y Sortino se anualizan con 365 días y una tasa libre de riesgo de 0 %; VaR y CVaR son históricos, a un día y al 95 %, expresados como pérdida.</p>
        {errorCorridas && <p className="aviso-error" role="alert">No se pudieron leer las corridas: {errorCorridas}</p>}
        {!corridas && !errorCorridas && <p className="vacio">Leyendo las corridas…</p>}
        <div className="tabla-scroll">
          <table className="tabla-corridas">
            <thead>
              <tr><th>Corrida</th><th>Periodo</th><th>Activos</th><th>Decisiones</th><th>Rendimiento neto</th><th>Comprar y mantener</th><th>Caída máx.</th><th>Sharpe</th><th>Sortino</th><th>VaR 95 %</th><th>CVaR 95 %</th><th>Operaciones</th><th>Ganadoras</th><th>Rechazadas</th><th>Latencia media</th></tr>
            </thead>
            <tbody>
              {(corridas ?? []).map((r) => (
                <tr key={r.run}>
                  <td>{r.etiqueta || NOMBRE_TIPO[r.tipo] || r.run}</td>
                  <td>{r.periodo ? `${r.periodo[0]} a ${r.periodo[1]}` : 'sin datos'}</td>
                  <td>{r.activos ?? 1}</td>
                  <td>{r.ciclos}</td>
                  <td>{pctSigno(r.rendimiento)}</td>
                  <td>{pctSigno(r.comprar_y_mantener)}</td>
                  <td>{pct(r.drawdown)}</td>
                  <td>{r.sharpe == null ? 'sin dato' : r.sharpe.toFixed(2)}</td>
                  <td>{r.sortino == null ? 'sin dato' : r.sortino.toFixed(2)}</td>
                  <td>{r.var == null ? 'sin dato' : pct(r.var)}</td>
                  <td>{r.cvar == null ? 'sin dato' : pct(r.cvar)}</td>
                  <td>{r.operaciones}</td>
                  <td>{r.win_rate == null ? 'no definido' : pct(r.win_rate, 0)}</td>
                  <td>{r.acciones_rechazadas}</td>
                  <td>{r.latencia_media_ms == null ? 'no aplica' : `${num(Math.round(r.latencia_media_ms / 100) / 10)} s`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
