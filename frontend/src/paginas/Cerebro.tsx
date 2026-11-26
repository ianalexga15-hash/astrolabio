import { useCallback, useEffect, useRef, useState } from 'react';
import { type EventoBot, useDatos, useEventos } from '../api';
import { Constelacion, type EnlaceCerebro, type NodoCerebro } from '../graficos/Constelacion';
import { NOMBRE_BOT } from '../logica';
import { useNuevos } from '../movimiento';

interface Datos {
  nodos: NodoCerebro[];
  enlaces: EnlaceCerebro[];
  recientes: EventoBot[];
  bot: string;
  ollama: { ok: boolean; version?: string; ms?: number; error?: string };
  reflejo: { barridos: number; activos: number; latencia_ms: number; p99_ms: number } | null;
  resumen: { posiciones: number; armadas: number; activos: number } | null;
  ultimo_llm: { latencia_ms: number } | null;
}

const NOMBRE_ESTADO = { activo: 'Activo', atencion: 'Atención', detenido: 'Detenido', reposo: 'En reposo' } as const;
const NOMBRE_TIPO: Record<string, string> = {
  datos: 'Datos', decision: 'Propuesta', bloqueo: 'Bloqueo', autorizacion: 'Autorización', ordenes: 'Ejecución Paper', aprendizaje: 'Aprendizaje', error: 'Error',
};

export function Cerebro() {
  const { datos, error } = useDatos<Datos>('/api/cerebro', 5000);
  const emisor = useRef<((e: EventoBot) => void) | null>(null);
  const [seleccion, setSeleccion] = useState<string | null>(null);
  const [feed, setFeed] = useState<EventoBot[]>([]);
  const [ritmo, setRitmo] = useState(0);
  const marcas = useRef<number[]>([]);

  const registrar = useCallback((f: (e: EventoBot) => void) => {
    emisor.current = f;
  }, []);

  const conectado = useEventos((e) => {
    emisor.current?.(e);
    marcas.current.push(e.ts);
    setFeed((f) => [e, ...f].slice(0, 30));
  });

  useEffect(() => {
    const t = setInterval(() => {
      const limite = Date.now() / 1000 - 60;
      marcas.current = marcas.current.filter((m) => m >= limite);
      setRitmo(marcas.current.length);
    }, 2000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (datos?.recientes && feed.length === 0) setFeed([...datos.recientes].reverse().slice(0, 30));
  }, [datos, feed.length]);

  const nombre = (id: string) => datos?.nodos.find((n) => n.id === id)?.etiqueta ?? id;
  const elegido = datos?.nodos.find((n) => n.id === seleccion);
  const nuevosFeed = useNuevos(feed.length ? feed : null);

  if (error) return <p className="aviso-error" role="alert">{error}</p>;

  return (
    <>
      <section className="cerebro">
        <div className="cerebro-encabezado">
          <h2>Constelación de componentes</h2>
          <p>Cada nodo representa un componente del bot. Los flujos y las ondas muestran eventos reales; el fondo estelar es ambiental y puedes dejarlo quieto.</p>
        </div>
        <Constelacion nodos={datos?.nodos ?? []} enlaces={datos?.enlaces ?? []} seleccion={seleccion} alSeleccionar={setSeleccion} registrarEmisor={registrar} />
        <ul className="leyenda leyenda-cerebro" aria-label="Leyenda">
          <li><i className="linea-datos" />Datos</li>
          <li><i className="linea-decision" />Propuesta</li>
          <li><i className="linea-bloqueo" />Bloqueo</li>
          <li><i className="linea-autorizacion" />Autorización</li>
          <li><i className="linea-ordenes" />Ejecución Paper</li>
          <li><i className="linea-aprendizaje" />Aprendizaje</li>
          <li><i className="punto-activo" />Activo</li>
          <li><i className="punto-atencion" />Atención</li>
          <li><i className="punto-detenido" />Detenido</li>
          <li><i className="punto-reposo" />En reposo</li>
        </ul>
      </section>

      <dl className="lecturas lecturas-cerebro">
        <div><dt>Estado del bot</dt><dd>{datos ? NOMBRE_BOT[datos.bot] ?? datos.bot : 'sin dato'}</dd><small>{datos?.resumen ? `${datos.resumen.posiciones} posiciones de ${datos.resumen.activos} activos` : ''}</small></div>
        <div><dt>Latencia del reflejo</dt><dd>{datos?.reflejo ? `${datos.reflejo.latencia_ms.toFixed(2)} ms` : 'sin dato'}</dd><small>{datos?.reflejo ? `p99 ${datos.reflejo.p99_ms.toFixed(2)} ms, ${datos.reflejo.barridos.toLocaleString('es-MX')} barridos` : ''}</small></div>
        <div><dt>Última respuesta del LLM</dt><dd>{datos?.ultimo_llm ? `${(datos.ultimo_llm.latencia_ms / 1000).toFixed(1)} s` : 'sin consultas'}</dd><small>una revisión al día por activo</small></div>
        <div><dt>Eventos por minuto</dt><dd>{ritmo}</dd><small>{conectado ? 'conectado al backend' : 'reconectando'}</small></div>
        <div><dt>Ollama local</dt><dd>{!datos ? 'sin dato' : datos.ollama.ok ? `activo ${datos.ollama.version}` : 'detenido'}</dd><small>{datos?.ollama.ok ? `responde en ${Math.round(datos.ollama.ms ?? 0)} ms` : datos?.ollama.error}</small></div>
      </dl>

      <div className="dos-columnas">
        <section className="columna-principal">
          <h2>Componentes</h2>
          <div className="tabla-scroll">
            <table className="tabla-componentes">
              <thead><tr><th>Componente</th><th>Grupo</th><th>Estado</th><th>Eventos</th><th>Último evento</th></tr></thead>
              <tbody>
                {(datos?.nodos ?? []).map((n) => (
                  <tr key={n.id} className={seleccion === n.id ? 'fila-activa' : ''} onClick={() => setSeleccion(n.id)}>
                    <td><button className="enlace" onClick={() => setSeleccion(n.id)}>{n.etiqueta}</button></td>
                    <td>{n.grupo}</td>
                    <td><span className={`etiqueta-estado e-${n.estado}`}>{NOMBRE_ESTADO[n.estado]}</span></td>
                    <td>{n.eventos}</td>
                    <td>{n.ultimo ? new Date(n.ultimo * 1000).toLocaleTimeString('es-MX', { hourCycle: 'h23' }) : 'sin eventos'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section className="flujo">
          <h2>{elegido ? elegido.etiqueta : 'Eventos recientes'}</h2>
          {feed.length === 0 && <p className="vacio">Sin eventos todavía. Aparecerán en cuanto el bot consulte MEXC.</p>}
          <ol>
            {feed.filter((e) => !seleccion || e.origen === seleccion || e.destino === seleccion).slice(0, 18).map((e) => (
              <li key={e.id} className={nuevosFeed.has(e.id) ? 'evento-nuevo' : undefined}>
                <time>{new Date(e.ts * 1000).toLocaleTimeString('es-MX', { hourCycle: 'h23' })}</time>
                <span>{nombre(e.origen)} a {nombre(e.destino)}</span>
                <small><i className={`punto-flujo f-${e.tipo}`} aria-hidden="true" />{NOMBRE_TIPO[e.tipo] ?? e.tipo}{e.detalle ? `: ${e.detalle}` : ''}</small>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </>
  );
}
