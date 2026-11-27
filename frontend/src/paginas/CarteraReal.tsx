import { useState } from 'react';
import { enviar, type EstadoReal, type Radar, useDatos } from '../api';
import { ActivoCompacto, IdentidadActivo } from '../componentes/IdentidadActivo';
import { comprasPosibles, horaLocal, NOMBRE_ACCION, num, precio, usd, valorCuenta } from '../logica';
import { useCambio } from '../movimiento';
import type { CuentaMexc } from './Sistema';

const MODOS = [
  ['apagada', 'Apagada', 'Apagada: no envía nada a MEXC.'],
  ['sombra', 'Sombra', 'Sombra: arma cada orden y MEXC la valida sin ejecutarla, para probar sin dinero en juego.'],
  ['real', 'Real', 'Real: envía las órdenes con tu dinero, dentro de los topes.'],
] as const;
const ESTADOS: Record<string, [string, string]> = {
  ejecutada: ['Ejecutada', 'o-ejecutada'], probada: ['Validada en sombra', 'e-activo'], omitida: ['Omitida', 'o-expirada'], error: ['Rechazada', 'o-rechazada'],
  enviando: ['Sin respuesta', 'e-atencion'], no_enviada: ['No llegó a MEXC', 'o-rechazada'], sin_ejecutar: ['Sin ejecutar', 'o-expirada'],
};

/** El camino de una orden: Paper la ejecuta, los topes la acotan y MEXC Spot la recibe. El enlace solo se mueve con la cartera encendida. */
function Circuito({ modo, radar, real, usdt }: { modo: EstadoReal['modo']; radar: Radar | null; real: EstadoReal | null; usdt: number }) {
  const r = radar?.resumen;
  const barrido = useCambio(radar?.estadisticas?.ultimo_barrido_ms ?? null);
  const topes = real?.topes;
  const expuesto = real?.expuesto ?? 0;
  const usado = topes ? Math.min(1, expuesto / topes.tope_total_usdt) : 0;
  const compras = topes ? comprasPosibles(usdt, expuesto, topes.tope_total_usdt, topes.max_orden_usdt) : 0;
  return (
    <section className={`circuito modo-${modo}`} aria-label="Camino de una orden de Paper a tu cuenta de MEXC">
      <div className="circuito-nodo">
        <span className="circuito-nombre"><span className="punto-paper" />Paper ejecuta</span>
        <strong>{r ? `${r.posiciones} de ${r.activos}` : 'sin dato'}</strong>
        <small>posiciones abiertas, {r?.armadas ?? 0} compras armadas</small>
        <small>{barrido.veces > 0 && <i key={barrido.veces} className="pulso-barrido" aria-hidden="true" />}el radar revisa cada segundo</small>
      </div>
      <div className="circuito-enlace" aria-hidden="true"><i /></div>
      <div className="circuito-nodo">
        <span className="circuito-nombre">Topes</span>
        <strong>{usd(expuesto)} de {usd(topes?.tope_total_usdt)}</strong>
        <span className="circuito-barra" role="meter" aria-label="Parte usada del tope" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(usado * 100)}><i style={{ width: `${usado * 100}%` }} /></span>
        <small>hasta {usd(topes?.max_orden_usdt)} por orden; las compras se pausan en −{usd(topes?.perdida_diaria_usdt)} al día</small>
      </div>
      <div className="circuito-enlace" aria-hidden="true"><i /></div>
      <div className="circuito-nodo">
        <span className="circuito-nombre"><span className={`punto-real real-${modo}`} />MEXC Spot</span>
        <strong>{usd(usdt)}</strong>
        <small>en USDT; alcanza para {compras} {compras === 1 ? 'compra' : 'compras'} de {usd(topes?.max_orden_usdt)}</small>
      </div>
      <p className="circuito-estado">{MODOS.find(([m]) => m === modo)?.[2]} Encendida, repite solo lo que Paper ejecute desde ese momento; sin USDT en Spot no manda órdenes.</p>
    </section>
  );
}

/** Cartera Real: el mismo tablero que Paper, sobre tu cuenta Spot de MEXC. Repite lo que Paper ejecuta y solo Alex la enciende, escribiendo la confirmación. */
export function CarteraReal({ radar }: { radar: Radar | null }) {
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
  const precios = Object.fromEntries((radar?.filas ?? []).filter((f) => f.bid != null).map((f) => [f.simbolo, f.bid as number]));
  const delBot = new Map((real?.posiciones ?? []).map((p) => [p.simbolo.replace(/USDT$/, ''), p]));
  const saldos = cuenta?.saldos ?? [];
  // Una posición del bot que ya no está en la cuenta se muestra en cero: el descuadre queda a la vista
  const faltantes = [...delBot.keys()].filter((a) => !saldos.some((s) => s.activo === a)).map((activo) => ({ activo, libre: 0, bloqueado: 0 }));
  const valor = valorCuenta([...saldos, ...faltantes], precios);
  const filas = [...valor.filas].sort((a, b) => (b.valor ?? -1) - (a.valor ?? -1));
  const usdt = saldos.find((s) => s.activo === 'USDT')?.libre ?? 0;
  const clave = !real ? 'sin dato' : !real.clave_configurada ? 'Falta' : !real.verificacion ? 'Sin probar' : real.verificacion.ok ? 'Puede operar' : 'Con problema';

  return (
    <>
      <div className="titulo-vista">
        <div><h2>Cartera Real<span className="marca-punto">.</span></h2><p>Tu cuenta Spot de MEXC. Dinero real, los mismos controles de Paper.</p></div>
        <div className="titulo-acciones">
          <span className="cadencia"><span className={`punto-real real-${modo}`} />{real ? `Modo ${nombreModo.toLowerCase()}` : 'Leyendo el modo…'}</span>
          <div className="filtros-radar modos-real" role="group" aria-label="Modo de la cartera Real">
            {MODOS.map(([m, nombre]) => (
              <button key={m} aria-pressed={modo === m} className={modo === m ? 'seleccionado' : ''} disabled={enviando || !real}
                onClick={() => (m === 'real' ? setPidiendo(true) : pedirServidor('/api/real/modo', { modo: m }))}>{nombre}</button>
            ))}
          </div>
        </div>
      </div>

      <dl className="lecturas">
        <div>
          <dt>Saldo en MEXC</dt><dd>{cuenta?.conectada ? usd(valor.total) : 'sin dato'}</dd>
          <small>{cuenta?.conectada ? `${num(usdt)} USDT libres para operar` : cuenta ? 'Cuenta sin conectar' : 'Leyendo tu cuenta…'}</small>
        </div>
        <div><dt>Invertido por el bot</dt><dd>{usd(real?.expuesto)}</dd><small>tope de {usd(topes?.tope_total_usdt)}</small></div>
        <div><dt>Resultado de hoy</dt><dd>{usd(real?.resultado_hoy)}</dd><small>las compras se pausan en −{usd(topes?.perdida_diaria_usdt)}</small></div>
        <div><dt>Por orden</dt><dd>{usd(topes?.max_orden_usdt)}</dd><small>como máximo en cada compra</small></div>
        <div>
          <dt>Clave de MEXC</dt><dd>{clave}</dd>
          <small>{real?.verificacion ? `probada el ${horaLocal(real.verificacion.fecha)}` : 'solo Spot, sin retiros'}</small>
        </div>
      </dl>
      <Circuito modo={modo} radar={radar} real={real} usdt={usdt} />

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
      {error && <p className="aviso-error" role="alert">No se pudo leer la cartera Real: {error}</p>}
      {errorCuenta && <p className="aviso-error" role="alert">No se pudo leer tu cuenta de MEXC: {errorCuenta}</p>}
      {cuenta && !cuenta.conectada && <p className="aviso-atencion">{cuenta.error ?? cuenta.motivo}</p>}
      {real && !real.clave_configurada && <p className="aviso-atencion">Falta MEXC_API_KEY o MEXC_API_SECRET en .env.</p>}
      {real?.verificacion && !real.verificacion.ok && <p className="aviso-atencion">{real.verificacion.mensaje}</p>}
      {real?.compras_bloqueadas && <p className="aviso-atencion" role="alert">Compras reales en pausa: {real.motivo} Vuelve a elegir el modo para reanudarlas.</p>}

      <section className="panel-radar">
        <div className="radar-herramientas">
          <h3>Activos en tu cuenta Spot</h3>
          <div className="prueba-clave">
            {/* La hora con segundos y la clave por fecha hacen visible cada prueba, aunque el resultado sea el mismo */}
            {real?.verificacion && (
              <span key={real.verificacion.fecha} className={`texto-cambia ${real.verificacion.ok ? 'positivo' : 'negativo'}`} role="status">
                {real.verificacion.ok ? 'Clave lista: MEXC validó una orden de prueba sin ejecutarla' : real.verificacion.mensaje} ({horaLocal(real.verificacion.fecha, true)})
              </span>
            )}
            <button disabled={enviando || !real?.clave_configurada} onClick={() => pedirServidor('/api/real/verificar')}>{enviando ? 'Probando…' : 'Probar la clave'}</button>
          </div>
        </div>
        {filas.length > 0 ? (
          <div className="tabla-scroll">
            <table className="tabla-radar tabla-posiciones">
              <thead><tr><th>Activo</th><th>Disponible</th><th>En órdenes</th><th>Precio</th><th>Valor</th><th>Del bot</th></tr></thead>
              <tbody>
                {filas.map((f) => {
                  const bot = delBot.get(f.activo);
                  return (
                    <tr key={f.activo} className={bot ? 'fila-en_posicion' : undefined}>
                      {/* IdentidadActivo quita el sufijo USDT del par: con el activo solo, USDT quedaría sin nombre */}
                      <td><span className="activo-enlace"><IdentidadActivo simbolo={`${f.activo}USDT`} /><span><strong>{f.activo}</strong>{f.activo !== 'USDT' && <small>USDT</small>}</span></span></td>
                      <td>{num(f.libre)}</td>
                      <td className={f.bloqueado ? undefined : 'tenue'}>{num(f.bloqueado)}</td>
                      <td>{f.activo === 'USDT' ? '1' : precio(precios[`${f.activo}USDT`])}</td>
                      <td className={f.valor == null ? 'tenue' : undefined}>{f.valor == null ? 'sin precio' : usd(f.valor)}</td>
                      <td className={bot ? undefined : 'tenue'}>{bot ? `${num(bot.cantidad)} · costo ${usd(bot.costo)}` : 'no aplica'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="vacio radar-vacio">
            {!cuenta ? 'Leyendo tu cuenta de MEXC…' : !cuenta.conectada ? 'Sin conexión con tu cuenta de MEXC.'
              : 'Tu cuenta Spot está en cero. Si ya depositaste, en la app de MEXC abre Activos y transfiere el saldo a Spot, en USDT: aparece aquí en menos de 30 s.'}
          </p>
        )}
        <div className="tabla-pie">
          <span>{filas.length} {filas.length === 1 ? 'activo' : 'activos'} en tu cuenta</span>
          <span>Saldos de MEXC Spot cada 30 s · Precio de compra del radar · El bot nunca retira ni transfiere</span>
        </div>
      </section>

      <section>
        <h2>Órdenes reales</h2>
        {!real?.ordenes.length ? <p className="vacio">Todavía no hay órdenes. Aquí aparecen las compras y ventas de Paper que se repitan desde que la enciendas.</p> : (
          <div className="tabla-scroll">
            <table className="tabla-ordenes-reales">
              <thead><tr><th>Hora</th><th>Activo</th><th>Lado</th><th>Modo</th><th>Estado</th><th>Monto</th><th>Resultado</th><th>Detalle</th></tr></thead>
              <tbody>
                {real.ordenes.map((o) => {
                  const [estado, tono] = ESTADOS[o.estado] ?? [o.estado, ''];
                  return (
                    <tr key={o.id}>
                      <td>{horaLocal(o.creado)}</td><td><ActivoCompacto simbolo={o.simbolo} /></td>
                      <td className={`lado lado-${o.lado}`}>{NOMBRE_ACCION[o.lado] ?? o.lado}</td><td>{o.modo}</td>
                      <td><span className={`etiqueta-estado ${tono}`}>{estado}</span></td><td>{usd(o.cotizado ?? o.monto_usdt)}</td>
                      <td className={o.resultado == null ? 'tenue' : o.resultado >= 0 ? 'positivo' : 'negativo'}>{o.resultado == null ? 'no aplica' : usd(o.resultado)}</td>
                      <td>{o.motivo ?? ''}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <details className="explicacion">
        <summary>Paper y Real</summary>
        <p>Paper es la cartera interna: opera con precios reales de MEXC y 50,000 USDT virtuales, sin enviar nada. Real repite en tu cuenta Spot cada compra y venta que Paper ejecuta, con sus mismos stops y objetivos, dentro de los topes. Cada orden lleva un identificador propio: si se pierde la respuesta, el bot consulta a MEXC antes de reintentar y nunca la duplica. Un rechazo pausa las compras y deja seguir las ventas.</p>
      </details>
    </>
  );
}
