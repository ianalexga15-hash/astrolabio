import { useMemo, useState } from 'react';
import { enviar, useDatos } from '../api';
import { Universo } from '../graficos/Universo';
import { conectadas, type EnlaceNota, filtrarNotas, type Nota } from '../logica';

interface Datos {
  notas: Nota[];
  enlaces: EnlaceNota[];
  galaxias: Record<string, number>;
  autores: Record<string, number>;
  omitidas: string[];
  resumen: { vision: Nota[]; en_curso: Nota[]; pendiente: Nota[]; hecho: Nota[] };
}

const AUTOR: Record<string, string> = { codex: 'Codex', claude: 'Claude', alex: 'Alex', ambos: 'Codex y Claude' };
const TIPOS = ['Visión', 'Hito', 'Decisión', 'Código', 'Modelo', 'Estudio', 'Prueba', 'Error', 'Seguridad', 'Herramienta', 'Pendiente', 'En curso'];

function MuestraAutor({ origen }: { origen: string }) {
  return <i className={`muestra m-${origen}`} aria-hidden="true" />;
}

export function UniversoPagina() {
  const { datos, recargar, error } = useDatos<Datos>('/api/notas', 15_000);
  const [texto, setTexto] = useState('');
  const [origen, setOrigen] = useState('');
  const [galaxia, setGalaxia] = useState('');
  const [seleccion, setSeleccion] = useState<string | null>(null);
  const [formulario, setFormulario] = useState({ titulo: '', cuerpo: '', origen: 'alex', tipo: 'Decisión', galaxia: 'Decisiones' });
  const [aviso, setAviso] = useState('');
  const [falloNota, setFalloNota] = useState(''); // un rechazo no puede verse igual que «Nota guardada»

  const visibles = useMemo(() => filtrarNotas(datos?.notas ?? [], { texto, origen, galaxia }), [datos, texto, origen, galaxia]);
  const enlaces = useMemo(() => {
    const ids = new Set(visibles.map((n) => n.id));
    return (datos?.enlaces ?? []).filter((e) => ids.has(e.origen) && ids.has(e.destino));
  }, [visibles, datos]);
  const elegida = datos?.notas.find((n) => n.id === seleccion) ?? null;
  const relacionadas = elegida ? conectadas(elegida.id, datos!.notas, datos!.enlaces) : [];

  const columna = (titulo: string, lista: Nota[]) => (
    <div className="ahora-columna">
      <h3>{titulo}</h3>
      {lista.length === 0 && <p className="dato-menor">Nada por ahora.</p>}
      {lista.slice(0, 7).map((n) => (
        <button key={n.id} className="nota-boton" onClick={() => setSeleccion(n.id)}><MuestraAutor origen={n.origen} /><span>{n.titulo}</span></button>
      ))}
    </div>
  );

  if (error && !datos) return <p className="aviso-error" role="alert">{error}</p>;

  return (
    <>
      <section className="universo-encabezado">
        <h2>Universo del desarrollo</h2>
        <p>Cada estrella es una nota de cómo se construyó este bot y de lo que se aprendió al hacerlo. Las galaxias agrupan por tema, el color dice quién la hizo y las conexiones salen de enlaces escritos en cada nota. Es memoria del proyecto, no neuronas del modelo.</p>
      </section>

      <div className="fila-control">
        <label>Buscar<input value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Modelo, error, decisión" /></label>
        <label>Autor
          <select value={origen} onChange={(e) => setOrigen(e.target.value)}>
            <option value="">Todos</option>
            {Object.keys(datos?.autores ?? {}).map((a) => <option key={a} value={a}>{AUTOR[a] ?? a}</option>)}
          </select>
        </label>
        <label>Galaxia
          <select value={galaxia} onChange={(e) => setGalaxia(e.target.value)}>
            <option value="">Todas</option>
            {Object.keys(datos?.galaxias ?? {}).map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </label>
        <p className="dato-menor">{visibles.length} notas y {enlaces.length} conexiones</p>
      </div>

      <div className="universo-rejilla">
        <div className="universo-lienzo">
          <Universo notas={visibles} enlaces={enlaces} seleccion={seleccion} alSeleccionar={setSeleccion} />
          <ul className="leyenda leyenda-sobre" aria-label="Colores por autor">
            {['alex', 'claude', 'codex', 'ambos'].map((a) => <li key={a}><MuestraAutor origen={a} />{AUTOR[a]}</li>)}
          </ul>
        </div>
        <aside className="nota-detalle">
          {elegida ? (
            <>
              <p className={`insignia i-${elegida.origen}`}>{AUTOR[elegida.origen] ?? elegida.origen}, {elegida.tipo}</p>
              <h3>{elegida.titulo}</h3>
              <p className="dato-menor">{elegida.galaxia}. {elegida.fecha.replace('T', ' ')}{elegida.fuente ? `. ${elegida.fuente}` : ''}</p>
              <p className="nota-cuerpo">{elegida.cuerpo}</p>
              {relacionadas.length > 0 && <h4>Conecta con</h4>}
              {relacionadas.map((r) => <button key={r.id} className="nota-boton" onClick={() => setSeleccion(r.id)}><MuestraAutor origen={r.origen} /><span>{r.titulo}</span></button>)}
            </>
          ) : (
            <p className="vacio">Elige una estrella para leer su nota. Arrastra para girar el universo y usa la rueda para acercarte.</p>
          )}
        </aside>
      </div>

      <section>
        <h2>En qué nos quedamos</h2>
        <div className="ahora">
          {columna('Visión', datos?.resumen.vision ?? [])}
          {columna('En curso', datos?.resumen.en_curso ?? [])}
          {columna('Pendiente', datos?.resumen.pendiente ?? [])}
          {columna('Lo último hecho', datos?.resumen.hecho ?? [])}
        </div>
      </section>

      <div className="dos-columnas">
        <section className="columna-principal">
          <h2>Línea de tiempo</h2>
          <ol className="linea-tiempo">
            {[...visibles].reverse().map((n) => (
              <li key={n.id}>
                <button className={`nota-boton${seleccion === n.id ? ' elegida' : ''}`} onClick={() => setSeleccion(n.id)}>
                  <MuestraAutor origen={n.origen} />
                  <span>{n.titulo}<small>{n.fecha.replace('T', ' ')}, {n.tipo}, {n.galaxia}</small></span>
                </button>
              </li>
            ))}
          </ol>
        </section>
        <section className="flujo">
          <h2>Registrar un paso</h2>
          <p className="explicacion">Para conectar notas escribe el título exacto entre dobles corchetes: [[Título]]. No guardes claves: la nota se rechaza si parece contener una.</p>
          <form
            className="formulario-nota"
            onSubmit={async (e) => {
              e.preventDefault();
              setAviso('');
              setFalloNota('');
              try {
                const r = await enviar<{ id: string }>('/api/notas', formulario);
                setFormulario({ ...formulario, titulo: '', cuerpo: '' });
                setSeleccion(r.id);
                setAviso('Nota guardada.');
                recargar();
              } catch (err) {
                setFalloNota((err as Error).message);
              }
            }}
          >
            <label>Título<input required value={formulario.titulo} onChange={(e) => setFormulario({ ...formulario, titulo: e.target.value })} /></label>
            <label>Autor
              <select value={formulario.origen} onChange={(e) => setFormulario({ ...formulario, origen: e.target.value })}>
                {Object.entries(AUTOR).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <label>Tipo
              <select value={formulario.tipo} onChange={(e) => setFormulario({ ...formulario, tipo: e.target.value })}>
                {TIPOS.map((t) => <option key={t}>{t}</option>)}
              </select>
            </label>
            <label>Galaxia<input required list="galaxias" value={formulario.galaxia} onChange={(e) => setFormulario({ ...formulario, galaxia: e.target.value })} /></label>
            <datalist id="galaxias">{Object.keys(datos?.galaxias ?? {}).map((g) => <option key={g} value={g} />)}</datalist>
            <label>Contenido<textarea required rows={5} value={formulario.cuerpo} onChange={(e) => setFormulario({ ...formulario, cuerpo: e.target.value })} /></label>
            <button className="primario">Guardar nota</button>
            {aviso && <p className="aviso-bien" role="status">{aviso}</p>}
            {falloNota && <p className="aviso-error" role="alert">{falloNota}</p>}
          </form>
        </section>
      </div>
    </>
  );
}
