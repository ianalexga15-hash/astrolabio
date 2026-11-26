import { useEffect, useMemo, useRef, useState } from 'react';
import { type Decision, enviar, type Estado, type Orden, type Radar, useDatos } from '../api';
import { type Marca, Lineas } from '../graficos/Lineas';
import { Velas, type VelaOHLC } from '../graficos/Velas';
import { cuentaAtras, fechaHora, NOMBRE_ACCION, num, pct, pctSigno, precio as fmtPrecio, type PuntoSegundo, sma, sumarSegundo } from '../logica';
import { CifraViva, useCambio } from '../movimiento';

const DIA_MS = 86_400_000;
// Un control por dimensión: primero el intervalo; solo el diario elige entre velas y línea (la línea suma SMA20 y operaciones).
const INTERVALOS = [['1s', '1 s'], ['5m', '5 min'], ['60m', '1 h'], ['1d', '1 día']] as const;
const TIPOS_DIARIOS = [['velas', 'Velas'], ['linea', 'Línea']] as const;

/** Velas de 5 min o de 1 h que el servidor lee de MEXC y repite durante 30 s. */
function VelasIntradia({ simbolo, intervalo }: { simbolo: string; intervalo: '5m' | '60m' }) {
  const { datos, error } = useDatos<VelaOHLC[]>(`/api/velas-intradia?simbolo=${simbolo}&intervalo=${intervalo}`, 30_000);
  return (
    <>
      {error && <p className="aviso-error" role="alert">{error}</p>}
      {datos ? <Velas datos={datos} simbolo={simbolo} intervalo={intervalo} /> : !error && <p className="vacio">Leyendo las velas de MEXC…</p>}
    </>
  );
}

function Anillo({ restante }: { restante: number }) {
  const fraccion = Math.max(0, Math.min(1, restante / DIA_MS));
  const c = 2 * Math.PI * 44;
  return (
    <svg className="anillo" viewBox="0 0 100 100" role="img" aria-label={`Faltan ${cuentaAtras(restante)} para el cierre de la vela`}>
      <circle cx="50" cy="50" r="44" className="anillo-fondo" />
      <circle cx="50" cy="50" r="44" className="anillo-valor" strokeDasharray={c} strokeDashoffset={c * (1 - fraccion)} transform="rotate(-90 50 50)" />
      <text x="50" y="55" textAnchor="middle">{cuentaAtras(restante)}</text>
    </svg>
  );
}

/** Acciones avanzadas. Activar y desactivar el bot viven en la cabecera, visibles desde cualquier vista. */
export function Controles({ estado, recargar }: { estado: Estado | null; recargar: () => void }) {
  const [error, setError] = useState('');
  const [pendiente, setPendiente] = useState<string | null>(null);
  const menu = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    const cerrar = (e: Event) => {
      const d = menu.current;
      if (d?.open && (e instanceof KeyboardEvent ? e.key === 'Escape' : !d.contains(e.target as Node))) d.open = false;
    };
    document.addEventListener('click', cerrar);
    document.addEventListener('keydown', cerrar);
    return () => {
      document.removeEventListener('click', cerrar);
      document.removeEventListener('keydown', cerrar);
    };
  }, []);

  const accion = async (ruta: string) => {
    setPendiente(ruta);
    setError('');
    try {
      await enviar(`/api/control/${ruta}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPendiente(null);
      recargar();
    }
  };
  const bot = estado?.bot.estado;
  const posiciones = estado?.cartera?.posiciones ?? 0;
  return (
    <details className="acciones-avanzadas" ref={menu}>
      <summary>Acciones avanzadas</summary>
      <div className="menu-acciones">
        <button disabled={pendiente != null || bot !== 'activo'} onClick={() => accion('pausar')}>{pendiente === 'pausar' ? 'Pausando…' : 'Pausar el bot'}</button>
        <button
          className="peligro"
          disabled={pendiente != null || posiciones === 0}
          onClick={() => {
            if (window.confirm(`¿Cerrar ${posiciones === 1 ? 'la posición simulada' : `las ${posiciones} posiciones simuladas`} al precio actual de MEXC?`)) accion('cerrar-posicion');
          }}
        >
          {pendiente === 'cerrar-posicion' ? 'Cerrando…' : 'Cerrar todas las posiciones'}
        </button>
        <p>Pausar detiene compras y salidas automáticas hasta que vuelvas a activar el bot. Cerrar vende en Paper al precio actual.</p>
        {error && <p className="aviso-error" role="alert">{error}</p>}
      </div>
    </details>
  );
}

// Cumple, falla o pendiente: palomita, tache o círculo, dibujados con el mismo trazo que los demás iconos.
const TRAZO_CONDICION = { si: 'M5 12.5l4.5 4.5L19 7.5', no: 'M7 7l10 10M17 7 7 17', pendiente: 'M12 6.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11' };

export function Condicion({ cumple, texto, detalle }: { cumple: boolean | null; texto: string; detalle?: string }) {
  const cambio = useCambio(cumple == null ? null : cumple ? 'si' : 'no');
  return (
    <li className={cumple == null ? 'pendiente' : cumple ? 'cumple' : 'falla'}>
      <span key={cambio.veces} className={cambio.veces ? 'icono-cambia' : undefined} aria-hidden="true">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d={TRAZO_CONDICION[cumple == null ? 'pendiente' : cumple ? 'si' : 'no']} />
        </svg>
      </span>
      <div>
        {texto}
        {detalle && <small>{detalle}</small>}
      </div>
    </li>
  );
}

function PanelDecision({ d, estado }: { d: Decision | null; estado: Estado | null }) {
  const cambio = useCambio(d?.accion_final ?? null);
  if (!d) {
    return (
      <section className="decision">
        <h2>Decisión</h2>
        <p className="vacio">{estado ? 'Aún no hay decisiones para este activo. Inicia el bot: tomará la primera con la última vela cerrada.' : 'Leyendo la última decisión…'}</p>
      </section>
    );
  }
  const vivo = estado?.mercado.radar?.condiciones ?? [];
  const motivos: string[] = JSON.parse(d.motivos || '[]');
  const indicadores: Record<string, number | null> = JSON.parse(d.indicadores || '{}');
  const herramientas: string[] = JSON.parse(d.herramientas || '[]');
  const edad = estado?.mercado.edad_vela_horas;
  const maxima = Number(estado?.limites.antiguedad_max_horas ?? 26);
  const pasaUmbral = d.pronostico != null && d.umbral != null ? d.pronostico > d.umbral : null;
  return (
    <section className="decision">
      {cambio.veces > 0 && <span key={cambio.veces} className="borde-recorre" aria-hidden="true" />}
      <h2>Decisión de la vela {d.fecha_vela}</h2>
      <p className={`accion accion-${d.accion_final}`}>{NOMBRE_ACCION[d.accion_final] ?? d.accion_final}</p>
      <dl className="pares">
        <div><dt>Pronóstico para mañana</dt><dd>{pctSigno(d.pronostico, 3)}</dd></div>
        <div><dt>Umbral elegido en validación</dt><dd>{pct(d.umbral, 3)}</dd></div>
      </dl>
      <ul className="condiciones">
        <Condicion cumple={edad == null ? null : edad <= maxima} texto="Dato al día" detalle={edad == null ? undefined : `${edad.toFixed(1)} h desde el cierre; máximo ${maxima} h`} />
        <Condicion cumple={pasaUmbral} texto="El pronóstico supera el umbral" />
        <Condicion cumple={d.senal === 1} texto="Señal del modelo" detalle={d.filtro === 'sma20' ? 'Filtro SMA20: el reflejo lo revisa con el precio en vivo' : 'Sin filtro técnico'} />
        <Condicion cumple={d.accion_propuesta !== 'mantener'} texto={`Propuesta: ${NOMBRE_ACCION[d.accion_propuesta] ?? d.accion_propuesta}`} detalle={d.origen === 'llm' ? `${d.llm_modelo}, ${Math.round((d.latencia_ms ?? 0) / 100) / 10} s` : 'Regla del modelo, sin LLM'} />
        <Condicion cumple={d.aprobada === 1} texto={d.aprobada ? 'Riesgo aprobó' : 'Riesgo rechazó'} detalle={motivos.join(' ') || undefined} />
      </ul>
      <blockquote>{d.justificacion}</blockquote>
      {vivo.length > 0 && (
        <>
          <h3>Condiciones en este segundo: {estado?.mercado.radar?.cumplidas} de {vivo.length}</h3>
          <ul className="condiciones">
            {vivo.map((c) => <Condicion key={c.id} cumple={c.cumple} texto={c.nombre} detalle={c.detalle} />)}
          </ul>
        </>
      )}
      {(estado?.cuenta.cantidad ?? 0) > 0 && (
        <dl className="pares">
          <div><dt>En posición desde</dt><dd>{fmtPrecio(estado?.cuenta.precio_medio)}</dd></div>
          <div><dt>Stop de pérdida</dt><dd>{fmtPrecio(estado?.cuenta.stop)}</dd></div>
          <div><dt>Objetivo</dt><dd>{fmtPrecio(estado?.cuenta.objetivo)}</dd></div>
        </dl>
      )}
      {herramientas.length > 0 && <p className="dato-menor">El LLM consultó: {herramientas.join(', ')}.</p>}
      <details>
        <summary>Indicadores de esta vela</summary>
        <dl className="pares compacto">
          {Object.entries(indicadores).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{num(v)}</dd></div>)}
        </dl>
      </details>
    </section>
  );
}

export function Mercado({ estado, recargar, simbolo, alElegir }: { estado: Estado | null; recargar: () => void; simbolo: string; alElegir: (s: string) => void }) {
  const { datos: velas, error: errorVelas } = useDatos<VelaOHLC[]>(`/api/velas?limite=240&simbolo=${simbolo}`, 60_000);
  const [intervalo, setIntervalo] = useState<(typeof INTERVALOS)[number][0]>('1d');
  const [tipoDiario, setTipoDiario] = useState<(typeof TIPOS_DIARIOS)[number][0]>('velas');
  const vistaPrecio = intervalo === '1d' ? tipoDiario : intervalo;
  const { datos: ordenes } = useDatos<Orden[]>(`/api/ordenes?simbolo=${simbolo}`, 30_000);
  const { datos: decisiones } = useDatos<Decision[]>(`/api/decisiones?simbolo=${simbolo}`, 30_000);
  const [ahora, setAhora] = useState(Date.now());
  const { datos: radar } = useDatos<Radar>('/api/radar', 1000);
  const [segundos, setSegundos] = useState<Record<string, PuntoSegundo[]>>({});

  useEffect(() => {
    // shortcut: la serie de 1 s empieza al abrir la página; para historia previa haría falta un búfer en el servidor
    const t = radar?.estadisticas?.ultimo_barrido_ms;
    if (radar && t) setSegundos((s) => Object.fromEntries(radar.filas.map((f) => [f.simbolo, sumarSegundo(s[f.simbolo] ?? [], t, f.bid, f.ask)])));
  }, [radar]);
  const serie = segundos[simbolo] ?? [];

  useEffect(() => {
    const t = setInterval(() => setAhora(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const { etiquetas, cierres, media, marcas } = useMemo(() => {
    const lista = velas ?? [];
    const cierres = lista.map((v) => v.close);
    const etiquetas = lista.map((v) => new Date(v.open_time).toISOString().slice(0, 10));
    const marcas: Marca[] = (ordenes ?? []).filter((o) => o.estado === 'ejecutada' && o.vela != null).flatMap((o) => {
      const i = lista.findIndex((v) => v.open_time === o.vela);
      return i < 0 ? [] : [{ i, tipo: o.lado as Marca['tipo'], etiqueta: `${o.lado} a ${fmtPrecio(o.precio)}` }];
    });
    return { etiquetas, cierres, media: sma(cierres, 20), marcas };
  }, [velas, ordenes]);

  const pronosticos = useMemo(() => {
    const lista = decisiones ?? [];
    return { etiquetas: lista.map((d) => d.fecha_vela), valores: lista.map((d) => d.pronostico) };
  }, [decisiones]);

  const proxima = estado?.mercado.proxima_vela_ms ?? 0;
  const ultima = estado?.mercado.ultima_vela;
  const precio = estado?.mercado.precio ?? null;
  const edadPrecio = estado?.mercado.edad_s;

  return (
    <>
      <section className="modo">
        <label className="elegir-activo">
          Activo
          <select value={simbolo} onChange={(e) => alElegir(e.target.value)}>
            {(estado?.simbolos ?? [simbolo]).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <div className="modo-paper">
          <h2>Modo de operación</h2>
          <p className="modo-valor">Paper</p>
        </div>
        <Controles estado={estado} recargar={recargar} />
      </section>

      <section className="instrumentos">
        <Anillo restante={proxima - ahora} />
        <div className="instrumento-titulo">
          <h2>Vela diaria en curso</h2>
          <p>Cierra el {proxima ? fechaHora(proxima) : 'sin dato'} (00:00 UTC). El bot decide una vez, justo después del cierre.</p>
        </div>
        <dl className="lecturas">
          <div><dt>Precio en MEXC</dt><CifraViva key={simbolo} como="dd" valor={precio} texto={fmtPrecio(precio)} /><small>{edadPrecio == null ? 'esperando dato' : `hace ${Math.max(0, Math.round(edadPrecio))} s`}</small></div>
          <div><dt>Último cierre</dt><dd>{fmtPrecio(ultima?.close)}</dd><small>{ultima ? new Date(ultima.open_time).toISOString().slice(0, 10) : 'sin dato'}</small></div>
          <div><dt>Distancia al cierre</dt><dd>{precio != null && ultima ? pctSigno(precio / ultima.close - 1) : 'sin dato'}</dd><small>desde la última vela</small></div>
        </dl>
      </section>
      {estado?.mercado.error && <p className="aviso-error" role="alert">{estado.mercado.error}</p>}

      <div className="dos-columnas">
        <div className="columna-principal">
          <div className="selector-grafica">
            <div role="group" aria-label="Intervalo del precio">
              {INTERVALOS.map(([v, nombre]) => <button key={v} aria-pressed={intervalo === v} onClick={() => setIntervalo(v)}>{nombre}</button>)}
            </div>
            {intervalo === '1d' && (
              <div role="group" aria-label="Tipo de gráfica diaria">
                {TIPOS_DIARIOS.map(([v, nombre]) => <button key={v} aria-pressed={tipoDiario === v} onClick={() => setTipoDiario(v)}>{nombre}</button>)}
              </div>
            )}
          </div>
          {(vistaPrecio === 'velas' || vistaPrecio === 'linea') && errorVelas && <p className="aviso-error" role="alert">No se pudieron leer las velas diarias: {errorVelas}</p>}
          {vistaPrecio === 'velas' && (velas ? <Velas datos={velas} simbolo={simbolo} /> : !errorVelas && <p className="vacio">Leyendo las velas diarias…</p>)}
          {vistaPrecio === 'linea' && <Lineas
            identidad={simbolo}
            titulo={`Precio de cierre de ${simbolo} y su promedio de 20 días`}
            etiquetas={etiquetas}
            series={[{ nombre: 'Cierre', color: '#3D8BEB', valores: cierres }, { nombre: 'SMA20', color: '#C08226', valores: media, punteada: true }]}
            marcas={marcas}
            formato={fmtPrecio}
          />}
          {vistaPrecio === '1s' && <Lineas
            quieta
            identidad={simbolo}
            titulo={`Precio de ${simbolo} segundo a segundo, desde que abriste Mercado (hasta 15 min)`}
            etiquetas={serie.map((p) => `  ${new Date(p.t).toTimeString().slice(0, 8)}`)} // el eje de Lineas omite los dos primeros caracteres
            series={[{ nombre: 'Compra (bid)', color: '#3D8BEB', valores: serie.map((p) => p.bid) }, { nombre: 'Venta (ask)', color: '#C08226', valores: serie.map((p) => p.ask), punteada: true }]}
            formato={fmtPrecio}
          />}
          {(vistaPrecio === '5m' || vistaPrecio === '60m') && <VelasIntradia key={simbolo + vistaPrecio} simbolo={simbolo} intervalo={vistaPrecio} />}
          {pronosticos.etiquetas.length > 1 && (
            <Lineas identidad={simbolo} titulo="Pronóstico del modelo para el día siguiente" etiquetas={pronosticos.etiquetas} series={[{ nombre: 'Pronóstico', color: '#3D8BEB', valores: pronosticos.valores }]} formato={(v) => `${(v * 100).toFixed(2)} %`} alto={180} referencia={0} />
          )}
        </div>
        <PanelDecision key={simbolo} d={estado?.ultima_decision ?? null} estado={estado} />
      </div>
    </>
  );
}
