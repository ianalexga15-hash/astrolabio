import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { enviar, type Estado, type EstadoReal, type Radar as DatosRadar, useDatos } from './api';
import { avisoDetener, avisoDetenido, estadoMexc, interruptor, NOMBRE_BOT } from './logica';
import { useCambio } from './movimiento';
import { Asistente } from './paginas/Asistente';
import { Auditoria } from './paginas/Auditoria';
import { CarteraReal } from './paginas/CarteraReal';
import { Cerebro } from './paginas/Cerebro';
import { Estrategia } from './paginas/Estrategia';
import { Mercado } from './paginas/Mercado';
import { Operaciones } from './paginas/Operaciones';
import { Radar } from './paginas/Radar';
import { Resumen } from './paginas/Resumen';
import { Sistema } from './paginas/Sistema';
import { UniversoPagina } from './paginas/UniversoPagina';
import { Icono } from './Icono';

const PAGINAS = [
  ['radar', 'Radar'], ['mercado', 'Mercado'], ['resumen', 'Resumen'], ['operaciones', 'Operaciones'], ['estrategia', 'Estrategia'],
  ['cerebro', 'Cerebro'], ['auditoria', 'Auditoría'], ['sistema', 'Sistema'], ['universo', 'Universo'],
] as const;
type Pagina = (typeof PAGINAS)[number][0];

export function EstadoChip({ estado, halo = false }: { estado: string; halo?: boolean }) {
  return <span className={`chip estado-${estado}${halo ? ' halo' : ''}`}><i aria-hidden="true" />{NOMBRE_BOT[estado] ?? estado}</span>;
}

/** Interruptor global: la respuesta del servidor decide el estado y nunca se usa /api/apagar, que cierra la aplicación. */
function InterruptorBot({ estado, conectado, recargar }: { estado: Estado | null; conectado: boolean; recargar: () => void }) {
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState<string | null>(null);
  const [halo, setHalo] = useState(false);
  const cancelar = useRef<HTMLButtonElement>(null);
  const bot = conectado ? estado?.bot.estado : undefined;
  const i = interruptor(bot, conectado);
  const posiciones = estado?.cartera?.posiciones ?? 0;
  const cambio = useCambio(bot ?? null);

  useEffect(() => {
    if (!cambio.veces || bot !== 'activo') return;
    setHalo(true);
    const t = window.setTimeout(() => setHalo(false), 500);
    return () => window.clearTimeout(t);
  }, [cambio.veces, bot]);

  useEffect(() => {
    if (aviso) cancelar.current?.focus();
  }, [aviso]);

  const ejecutar = async (ruta: 'iniciar' | 'detener') => {
    setAviso(null);
    setError('');
    setEnviando(true);
    try {
      await enviar(`/api/control/${ruta}`);
    } catch (e) {
      setError(`No se pudo ${ruta === 'iniciar' ? 'activar' : 'desactivar'} el bot: ${(e as Error).message}`);
    } finally {
      setEnviando(false);
      recargar();
    }
  };
  const pulsar = () => {
    if (!i.ruta) return;
    const advertencia = i.ruta === 'detener' ? avisoDetener(posiciones) : null;
    if (advertencia) setAviso(advertencia);
    else ejecutar(i.ruta);
  };

  return (
    <div className="interruptor" onKeyDown={(e) => { if (e.key === 'Escape') { setAviso(null); setError(''); } }}>
      <EstadoChip estado={bot ?? 'desconocido'} halo={halo} />
      {conectado && posiciones > 0 && <span className="posiciones-abiertas">{posiciones === 1 ? '1 posición abierta' : `${posiciones} posiciones abiertas`}</span>}
      <button className={`interruptor-boton ${i.ruta === 'iniciar' ? 'encender' : 'apagar'}`} disabled={enviando || !i.ruta} aria-busy={enviando || undefined}
        title={i.motivo ?? 'Compra y vende automáticamente · Paper'} aria-describedby="interruptor-ayuda" onClick={pulsar}>
        {enviando && <i className="espera" aria-hidden="true" />}
        <span key={enviando ? 'espera' : i.texto} className="texto-cambia">{enviando ? i.espera : i.texto}</span>
      </button>
      <span id="interruptor-ayuda" className="solo-lectores">Encendido: decide y opera solo cuando se cumplen condiciones. Apagado: no ejecuta compras ni ventas automáticas.</span>
      {aviso && (
        <div className="globo-interruptor" role="alertdialog" aria-labelledby="aviso-detener">
          <p id="aviso-detener">{aviso}</p>
          <div className="globo-acciones">
            <button ref={cancelar} onClick={() => setAviso(null)}>Cancelar</button>
            <button className="peligro" onClick={() => ejecutar('detener')}>Desactivar</button>
          </div>
        </div>
      )}
      {error && (
        <div className="globo-interruptor globo-error" role="alert">
          <p>{error}</p>
          <div className="globo-acciones"><button onClick={() => setError('')}>Entendido</button></div>
        </div>
      )}
    </div>
  );
}

function Entrada({ alEntrar }: { alEntrar: () => void }) {
  const [clave, setClave] = useState('');
  const [error, setError] = useState('');
  const [enviando, setEnviando] = useState(false);
  return (
    <main className="entrada">
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setEnviando(true);
          try {
            await enviar('/api/login', { clave });
            alEntrar();
          } catch (err) {
            setError((err as Error).message);
          } finally {
            setEnviando(false);
          }
        }}
      >
        <img src="/astrolabio.svg" width="86" height="86" alt="" />
        <h1>Astrolabio<span className="marca-punto">.</span></h1>
        <p>Una mirada al mercado. Cada decisión, en su lugar.</p>
        <div className="entrada-modo"><span className="punto-paper" />MEXC Spot <span> / </span> Cartera Paper</div>
        <label>
          Clave del panel
          <input type="password" autoFocus autoComplete="current-password" value={clave} onChange={(e) => setClave(e.target.value)} />
        </label>
        {error && <p className="aviso-error" role="alert">{error}</p>}
        <button className="primario" disabled={!clave || enviando}>{enviando ? 'Abriendo observatorio…' : 'Entrar al observatorio'}</button>
        <details><summary>¿Dónde encuentro mi clave?</summary><p>Usa tu contraseña personal si ya la configuraste en Sistema. Si no, o si la olvidaste, usa la clave BOT_ADMIN_KEY del archivo .env del proyecto.</p></details>
        <small>Datos de mercado reales. Operaciones con dinero virtual.</small>
      </form>
    </main>
  );
}

function Tablero({ alSalir }: { alSalir: () => void }) {
  const inicial = (location.hash.slice(1) as Pagina) || 'radar';
  const [pagina, setPagina] = useState<Pagina>(PAGINAS.some(([k]) => k === inicial) ? inicial : 'radar');
  const [simbolo, setSimbolo] = useState('BTCUSDT');
  const [cartera, setCartera] = useState<'paper' | 'real'>(location.hash === '#real' ? 'real' : 'paper');
  const { datos: estado, error, recargar } = useDatos<Estado>(`/api/estado?simbolo=${simbolo}`, 2000);
  const { datos: radar, error: errorRadar } = useDatos<DatosRadar>('/api/radar', 3000);
  const { datos: real } = useDatos<EstadoReal>('/api/real', 10_000);
  const mexc = estadoMexc(radar ?? null, errorRadar);
  const abrir = (k: Pagina) => { setCartera('paper'); setPagina(k); };

  useEffect(() => {
    history.replaceState(null, '', `#${cartera === 'real' ? 'real' : pagina}`);
  }, [pagina, cartera]);

  const estadoBot = estado?.bot.estado;
  const atencion = estadoBot === 'pausado' || estadoBot === 'bloqueado';
  const sinVigilar = error ? null : avisoDetenido(estadoBot, estado?.cartera?.posiciones);
  const nav = useRef<HTMLElement>(null);
  const linea = useRef<HTMLSpanElement>(null);
  const animarLinea = useRef(false);

  const moverLinea = (animar: boolean) => {
    const marca = linea.current;
    const activa = nav.current?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!marca || !activa) return;
    if (!animar) marca.style.transition = 'none';
    marca.style.transform = `translateX(${activa.offsetLeft}px)`;
    marca.style.width = `${activa.offsetWidth}px`;
    if (!animar) {
      void marca.offsetWidth; // aplica la posición sin transición antes de restaurarla
      marca.style.transition = '';
    }
  };

  useLayoutEffect(() => {
    moverLinea(animarLinea.current);
    animarLinea.current = true;
    nav.current?.querySelector('[aria-current="page"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [pagina, cartera]);

  useEffect(() => {
    const observador = new ResizeObserver(() => moverLinea(false));
    nav.current?.querySelectorAll('button').forEach((b) => observador.observe(b));
    return () => observador.disconnect();
  }, []);

  return (
    <div className="marco">
      <a className="saltar-contenido" href="#contenido">Saltar al contenido</a>
      <header className="barra-superior">
        <div className="barra-fila">
          <div className="marca">
            <img src="/astrolabio.svg" width="32" height="32" alt="" />
            <h1>Astrolabio<span className="marca-punto">.</span></h1>
          </div>
          <div className="cabecera-derecha">
            <div className="insignias">
              <div className="selector-cartera" role="group" aria-label="Cartera">
                <button aria-pressed={cartera === 'paper'} onClick={() => setCartera('paper')} title="Datos reales de MEXC, capital virtual"><span className="punto-paper" />PAPER</button>
                <button aria-pressed={cartera === 'real'} onClick={() => setCartera('real')} title={`Tu cuenta Spot de MEXC con dinero real · ${real?.modo ?? 'sin dato'}`}>
                  <span className={`punto-real real-${real?.modo ?? 'apagada'}`} />REAL
                </button>
              </div>
              <span className={`mercado-insignia mexc-${mexc.tono}`} title={`MEXC Spot. ${mexc.detalle}`} role="status"><i aria-hidden="true" />MEXC <span>{mexc.texto}</span></span>
              {estado?.modelo && estado.modelo.valido_para_entrega === false && (
                <span className="aviso-modelo" title="Modelo entrenado en CPU, sin la evidencia de entrenamiento en T4.">Modelo de desarrollo</span>
              )}
            </div>
            {(estado || error) && <InterruptorBot estado={estado} conectado={!error} recargar={recargar} />}
            <button className="salir" onClick={async () => { await enviar('/api/logout'); alSalir(); }}><Icono nombre="salir" /><span>Salir</span></button>
          </div>
        </div>
        <div className="pestanas-fila">
          <nav className={`pestanas${cartera === 'real' ? ' en-real' : ''}`} aria-label="Secciones" ref={nav}>
            <span className="pestanas-linea" ref={linea} aria-hidden="true" />
            {PAGINAS.map(([k, nombre]) => (
              <button key={k} className={cartera === 'paper' && pagina === k ? 'activa' : ''} aria-current={cartera === 'paper' && pagina === k ? 'page' : undefined} onClick={() => abrir(k)}>
                <Icono nombre={k} /><span>{nombre}</span>
                {k === 'sistema' && atencion && <i className="punto-aviso" title="Requiere atención" />}
              </button>
            ))}
          </nav>
          <Asistente />
        </div>
      </header>
      <div className="espacio-trabajo">
      {error && <p className="aviso-error" role="alert">No se pudo leer el estado del bot: {error}</p>}
      {estado?.bot.motivo && estado.bot.estado !== 'detenido' && <p className="aviso-atencion" role="alert">{estado.bot.motivo}</p>}
      {sinVigilar && <p className="aviso-atencion">{sinVigilar}</p>}

      <main key={cartera === 'real' ? 'real' : pagina} className={`contenido vista-${cartera === 'real' ? 'real' : pagina}`} id="contenido" tabIndex={-1}>
        {cartera === 'real' && <CarteraReal radar={radar ?? null} />}
        {cartera === 'paper' && <>
        {pagina === 'radar' && <Radar estado={estado} recargar={recargar} alElegir={(s) => { setSimbolo(s); setPagina('mercado'); }} />}
        {pagina === 'mercado' && <Mercado estado={estado} recargar={recargar} simbolo={simbolo} alElegir={setSimbolo} />}
        {pagina === 'resumen' && <Resumen estado={estado} />}
        {pagina === 'operaciones' && <Operaciones estado={estado} />}
        {pagina === 'estrategia' && <Estrategia />}
        {pagina === 'cerebro' && <Cerebro />}
        {pagina === 'auditoria' && <Auditoria />}
        {pagina === 'sistema' && <Sistema estadoBot={estadoBot} />}
        {pagina === 'universo' && <UniversoPagina />}
        </>}
      </main>
      </div>
    </div>
  );
}

export function App() {
  const [dentro, setDentro] = useState<boolean | null>(null);

  useEffect(() => {
    fetch('/api/estado', { credentials: 'same-origin' }).then((r) => setDentro(r.ok)).catch(() => setDentro(false));
    const perder = () => setDentro(false);
    window.addEventListener('sesion-perdida', perder);
    return () => window.removeEventListener('sesion-perdida', perder);
  }, []);

  if (dentro === null) return null;
  return dentro ? <Tablero alSalir={() => setDentro(false)} /> : <Entrada alEntrar={() => setDentro(true)} />;
}
