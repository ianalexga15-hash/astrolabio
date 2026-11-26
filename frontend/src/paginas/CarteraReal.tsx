import { useState } from 'react';
import { enviar, type EstadoReal, useDatos } from '../api';
import { horaLocal, NOMBRE_ACCION, num, usd } from '../logica';
import { type CuentaMexc, CuentaReal } from './Sistema';

const MODOS = [
  ['apagada', 'Apagada', 'No envía nada a MEXC.'],
  ['sombra', 'Sombra', 'Arma cada orden y MEXC la valida sin ejecutarla: sirve para probar sin dinero en juego.'],
  ['real', 'Real', 'Envía las órdenes con tu dinero, dentro de los topes.'],
] as const;
const ESTADOS: Record<string, string> = {
  ejecutada: 'Ejecutada', probada: 'Validada en sombra', omitida: 'Omitida', error: 'Rechazada', enviando: 'Sin respuesta',
  no_enviada: 'No llegó a MEXC', sin_ejecutar: 'Sin ejecutar',
};

/** Cartera Real: repite en la cuenta Spot de MEXC lo que Paper ejecuta. Solo Alex la enciende, escribiendo la confirmación. */
export function CarteraReal() {
  const { datos: real, error, recargar } = useDatos<EstadoReal>('/api/real', 5000);
  const { datos: cuenta, error: errorCuenta } = useDatos<CuentaMexc>('/api/cuenta-mexc', 30_000);
  const [pidiendo, setPidiendo] = useState(false);
  const [texto, setTexto] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState('');

  const pedirServidor = async (ruta: string, cuerpo?: unknown) => {
    setEnviando(true);
    setFallo('');
    try {
      await enviar(ruta, cuerpo);
      setPidiendo(false);
      setTexto('');
    } catch (e) {
      setFallo((e as Error).message);
    } finally {
      setEnviando(false);
      recargar();
    }
  };
  const modo = real?.modo ?? 'apagada';
  const topes = real?.topes;
  const nombreModo = MODOS.find(([m]) => m === modo)?.[1] ?? modo;

  return (
    <>
      <section className="titular">
        <div>
          <h2>Cartera Real · MEXC Spot</h2>
          <p className="cifra-mayor">{real ? nombreModo : 'sin dato'}</p>
          <p className="cifra-nota">Repite con dinero real las compras y ventas que Paper ejecuta, con sus mismos stops y objetivos.</p>
        </div>
        <dl className="lecturas">
          <div><dt>Invertido por el bot</dt><dd>{usd(real?.expuesto)}</dd><small>tope {usd(topes?.tope_total_usdt)}</small></div>
          <div><dt>Por orden</dt><dd>{usd(topes?.max_orden_usdt)}</dd><small>máximo</small></div>
          <div><dt>Resultado de hoy</dt><dd>{usd(real?.resultado_hoy)}</dd><small>se pausa en −{usd(topes?.perdida_diaria_usdt)}</small></div>
        </dl>
      </section>
      {error && <p className="aviso-error" role="alert">No se pudo leer la cartera Real: {error}</p>}
      {real?.compras_bloqueadas && <p className="aviso-atencion" role="alert">Compras reales en pausa: {real.motivo} Vuelve a elegir el modo para reanudarlas.</p>}

      <section>
        <h2>Modo</h2>
        <div className="selector-grafica" role="group" aria-label="Modo de la cartera Real">
          {MODOS.map(([m, nombre]) => (
            <button key={m} aria-pressed={modo === m} disabled={enviando || !real}
              onClick={() => (m === 'real' ? setPidiendo(true) : pedirServidor('/api/real/modo', { modo: m }))}>{nombre}</button>
          ))}
        </div>
        <p className="explicacion">{MODOS.find(([m]) => m === modo)?.[2]} Al encenderla solo repite lo que Paper ejecute desde ese momento; sin saldo en USDT no envía nada.</p>
        {pidiendo && (
          <form className="confirmar-real" onSubmit={(e) => { e.preventDefault(); pedirServidor('/api/real/modo', { modo: 'real', confirmacion: texto }); }}>
            <label>
              Escribe {real?.confirmacion ?? 'ACTIVAR REAL'} para operar con tu dinero
              <input value={texto} autoFocus onChange={(e) => setTexto(e.target.value)} autoComplete="off" />
            </label>
            <button className="peligro" disabled={enviando || texto !== real?.confirmacion}>Encender Real</button>
            <button type="button" onClick={() => { setPidiendo(false); setTexto(''); }}>Cancelar</button>
          </form>
        )}
        {fallo && <p className="aviso-error" role="alert">{fallo}</p>}
      </section>

      <section>
        <h2>Clave de MEXC</h2>
        {real && !real.clave_configurada && <p className="aviso-atencion">Falta MEXC_API_KEY o MEXC_API_SECRET en .env.</p>}
        <p className={real?.verificacion ? (real.verificacion.ok ? 'dato-menor' : 'aviso-atencion') : 'explicacion'}>
          {real?.verificacion ? `${real.verificacion.mensaje} (${horaLocal(real.verificacion.fecha)})` : 'Sin probar: el botón pide a MEXC validar una orden de prueba, que nunca se ejecuta.'}
        </p>
        <button disabled={enviando} onClick={() => pedirServidor('/api/real/verificar')}>{enviando ? 'Probando…' : 'Probar la clave'}</button>
      </section>

      <CuentaReal cuenta={cuenta} error={errorCuenta} />

      <section>
        <h2>Posiciones del bot</h2>
        {!real?.posiciones.length ? <p className="vacio">Sin posiciones reales.</p> : (
          <div className="tabla-scroll">
            <table>
              <thead><tr><th>Activo</th><th>Cantidad</th><th>Costo</th></tr></thead>
              <tbody>{real.posiciones.map((p) => <tr key={p.simbolo}><td>{p.simbolo}</td><td>{num(p.cantidad)}</td><td>{usd(p.costo)}</td></tr>)}</tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2>Órdenes reales</h2>
        {!real?.ordenes.length ? <p className="vacio">Todavía no hay órdenes. Aparecen aquí las compras y ventas de Paper que se repitan desde que la enciendas.</p> : (
          <div className="tabla-scroll">
            <table>
              <thead><tr><th>Hora</th><th>Activo</th><th>Lado</th><th>Modo</th><th>Estado</th><th>Monto</th><th>Resultado</th><th>Detalle</th></tr></thead>
              <tbody>
                {real.ordenes.map((o) => (
                  <tr key={o.id}>
                    <td>{horaLocal(o.creado)}</td><td>{o.simbolo}</td><td>{NOMBRE_ACCION[o.lado] ?? o.lado}</td><td>{o.modo}</td>
                    <td>{ESTADOS[o.estado] ?? o.estado}</td><td>{usd(o.cotizado ?? o.monto_usdt)}</td>
                    <td>{o.resultado == null ? '—' : usd(o.resultado)}</td><td>{o.motivo ?? ''}</td>
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
