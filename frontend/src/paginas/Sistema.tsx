import { useEffect, useState } from 'react';
import { enviar, type Radar, useDatos } from '../api';
import { avisoEnergia, type Energia, type EsquemaApi, fechaHora, limiteVacio, num, rutasDeEsquema, type SaldoMexc, usd, validarNuevaClave, valorCuenta } from '../logica';

interface Acceso {
  personal: boolean;
  desde: string | null;
}

interface CuentaMexc {
  conectada: boolean;
  saldos: SaldoMexc[];
  motivo?: string;
  error?: string | null;
  leido_hace_s?: number;
}

interface Percentiles {
  p50: number;
  p95: number;
  p99: number;
}

interface Info {
  energia?: Energia;
  ollama: { ok: boolean; version?: string; ms?: number; error?: string };
  ollama_url: string;
  modelo_llm: string;
  modelos_instalados: { nombre: string; digest: string; tamano: number }[];
  ultimo_llm: { modelo: string; latencia_ms: number; ts: number } | null;
  hardware: { sistema: string; procesador: string };
  mexc: { error: string | null; edad_precio_s: number | null };
  reflejo: {
    barridos: number; activos: number; latencia_ms: number; p99_ms: number;
    red?: { barridos: number; ciclo_ms: Percentiles | null; intervalo_s: Percentiles | null; ciclos_lentos: number; intervalos_largos: number };
  } | null;
  activos: string[];
  sin_modelo: string[];
}

const CAMPOS: [string, string, string][] = [
  ['capital_inicial', 'Capital virtual inicial', 'Unidades de USDT simuladas.'],
  ['comision', 'Comisión por operación', 'Fracción: 0.0008 es 0.08 %. Cada par usa la comisión real que dio MEXC para tu cuenta; esta queda para los pares sin dato.'],
  ['deslizamiento_bps', 'Deslizamiento supuesto', 'Puntos base que empeoran cada precio simulado.'],
  ['exposicion_max', 'Exposición máxima', 'Fracción del patrimonio. Máximo 1: sin apalancamiento.'],
  ['riesgo_por_operacion', 'Riesgo por operación', 'Pérdida aceptada hasta el stop, como fracción del patrimonio.'],
  ['perdida_diaria_max', 'Pérdida diaria máxima', 'Al alcanzarla no se abren posiciones ese día.'],
  ['drawdown_max', 'Caída máxima', 'Al alcanzarla el bot se bloquea hasta que lo reanudes.'],
  ['antiguedad_max_horas', 'Antigüedad máxima del dato', 'Horas desde el cierre de la última vela.'],
  ['stop_atr', 'Stop de pérdida', 'Distancia en múltiplos de ATR.'],
  ['objetivo_pct', 'Meta por operación', 'Precio de venta: entrada × (1 + meta + comisión del par); 0.13 es 13 %. No es una ganancia neta asegurada: muchas operaciones cierran antes en el stop. 0 usa el objetivo en ATR.'],
  ['objetivo_atr', 'Objetivo de ganancia', 'Distancia en múltiplos de ATR. Solo cuenta si la meta por operación es 0.'],
  ['trailing_atr', 'Stop móvil', 'Distancia en múltiplos de ATR; solo sube.'],
  ['spread_max_bps', 'Spread máximo', 'Puntos base. Con más spread el reflejo espera antes de comprar.'],
  ['extension_max_atr', 'Sin perseguir el precio', 'No compra si ya subió más de estos ATR desde el cierre.'],
  ['edad_precio_max_s', 'Antigüedad máxima del precio', 'Segundos. Con un precio más viejo el reflejo no opera.'],
  ['max_compras_dia', 'Tope de compras por día', 'Compras nuevas que la cartera puede autorizar en cada vela diaria, entre todos los activos y en su orden. 0 es sin tope.'],
  ['proteger_atr', 'Punto de equilibrio', 'ATR que debe ganar una posición para que su stop suba a la entrada más comisiones: desde ahí ya no termina en pérdida, salvo un salto. 0 lo apaga.'],
  ['espera_max_min', 'Espera en el libro', 'Minutos que una compra espera a su precio, sin comisión, antes de comprar al instante. 0 compra al instante.'],
  ['comision_espera', 'Comisión de la orden que espera', 'Fracción. MEXC informó 0 % en los 40 pares el 2026-11-06.'],
];

export function Sistema({ estadoBot }: { estadoBot?: string }) {
  const { datos: info, error: errorInfo, recargar } = useDatos<Info>('/api/sistema', 15_000);
  const { datos: config, recargar: recargarConfig } = useDatos<Record<string, number | string>>('/api/config');
  const [formulario, setFormulario] = useState<Record<string, number | string | boolean> | null>(null);
  const [mensaje, setMensaje] = useState('');
  const [fallo, setFallo] = useState('');
  const [apagado, setApagado] = useState('');
  const { datos: acceso, recargar: recargarAcceso } = useDatos<Acceso>('/api/acceso');
  const { datos: cuenta, error: errorCuenta } = useDatos<CuentaMexc>('/api/cuenta-mexc', 30_000);
  const energia = avisoEnergia(info?.energia);

  useEffect(() => {
    if (config) setFormulario(config);
  }, [config]);

  const bloqueado = estadoBot !== 'detenido' && estadoBot !== 'sin_modelo';

  return (
    <>
      <section className="sistema-intro">
        <h2>Tu observatorio, bajo control<span className="marca-punto">.</span></h2>
        <p>Primero afinamos el funcionamiento. Después conectamos tu cuenta.</p>
        <ol className="etapas-proyecto">
          <li className="etapa-actual"><span>01</span><strong>Funcionamiento Paper</strong><small>Etapa actual · capital virtual</small></li>
          <li className={acceso?.personal ? 'etapa-activa' : undefined}><span>02</span><strong>Tu contraseña</strong><small>{acceso?.personal ? 'Activa · la clave de .env queda de respaldo' : 'Lista para configurar abajo'}</small></li>
          <li className={cuenta?.conectada ? 'etapa-activa' : undefined}><span>03</span><strong>Cuenta MEXC</strong><small>{!cuenta ? 'sin dato' : cuenta.conectada ? 'Conectada · solo lectura' : 'Sin conectar'}</small></li>
          <li className="etapa-futura"><span>04</span><strong>Ejecución real</strong><small>Fase futura · aún no disponible</small></li>
        </ol>
      </section>

      <CuentaReal cuenta={cuenta} error={errorCuenta} />

      <section>
        <h2>LLM local</h2>
        {/* Sin respuesta de /api/sistema no se afirma ningún estado: ni «Detenido» ni cero activos */}
        {errorInfo && <p className="aviso-error" role="alert">No se pudo leer el estado del sistema: {errorInfo}</p>}
        <dl className="lecturas">
          <div><dt>Ollama</dt><dd>{!info ? 'sin dato' : info.ollama.ok ? `Activo, versión ${info.ollama.version}` : 'Detenido'}</dd><small><code>{info?.ollama_url}</code></small></div>
          <div><dt>Modelo</dt><dd>{info?.modelo_llm ?? 'sin dato'}</dd><small>huella <code>{info?.modelos_instalados.find((m) => m.nombre === info.modelo_llm)?.digest ?? 'sin dato'}</code></small></div>
          <div><dt>Última respuesta</dt><dd>{info?.ultimo_llm ? `${(info.ultimo_llm.latencia_ms / 1000).toFixed(1)} s` : 'sin consultas'}</dd></div>
        </dl>
        {info?.ollama.error && <p className="aviso-error" role="alert">{info.ollama.error}</p>}
        <p className="explicacion">La inferencia ocurre en esta laptop: el backend solo acepta una dirección local de Ollama y rechaza modelos en la nube. El LLM no recibe claves y solo tiene herramientas de lectura.{info?.hardware.procesador ? ` Procesador: ${info.hardware.procesador}.` : ''}</p>
        <button onClick={recargar}>Revisar otra vez</button>
      </section>

      <section>
        <h2>Datos de mercado</h2>
        <p className="explicacion">Datos públicos de MEXC, con un intervalo objetivo de un segundo para consultar precios. La red y los reintentos pueden alargarlo. {info?.mexc.error ?? ''} Las operaciones actuales son Paper.</p>
        <dl className="lecturas">
          <div><dt>Activos vigilados</dt><dd>{info?.reflejo?.activos ?? 'sin dato'}</dd><small>{!info ? '' : info.sin_modelo.length ? `${info.sin_modelo.length} sin modelo aprobado` : 'todos con modelo'}</small></div>
          <div><dt>Barridos del reflejo</dt><dd>{info?.reflejo?.barridos.toLocaleString('es-MX') ?? 'sin dato'}</dd><small>objetivo: un barrido por segundo</small></div>
          <div><dt>Procesamiento del reflejo</dt><dd>{info?.reflejo ? `${info.reflejo.latencia_ms.toFixed(2)} ms` : 'sin dato'}</dd><small>{info?.reflejo ? `p99 ${info.reflejo.p99_ms.toFixed(2)} ms · sin tiempo de red` : ''}</small></div>
          <div>
            <dt>Barrido completo con red</dt>
            <dd>{info?.reflejo?.red?.ciclo_ms ? `${info.reflejo.red.ciclo_ms.p95.toFixed(0)} ms p95` : 'sin dato'}</dd>
            <small>
              {info?.reflejo?.red?.ciclo_ms
                ? `p50 ${info.reflejo.red.ciclo_ms.p50.toFixed(0)} ms · p99 ${info.reflejo.red.ciclo_ms.p99.toFixed(0)} ms · ${info.reflejo.red.ciclos_lentos} de ${info.reflejo.red.barridos.toLocaleString('es-MX')} pasaron de 1 s`
                : 'se mide desde que arranca el servidor'}
            </small>
          </div>
        </dl>
      </section>

      <section>
        <h2>Energía</h2>
        <p className={energia.alerta ? 'aviso-atencion' : 'explicacion'} role={energia.alerta ? 'alert' : undefined}>{energia.texto}</p>
      </section>

      <section>
        <h2>Límites de riesgo</h2>
        <p className="explicacion">{bloqueado ? 'Detén el bot para poder cambiarlos.' : 'Se aplican a las siguientes decisiones.'} El LLM nunca puede modificarlos.</p>
        {formulario && (
          <form
            className="formulario-limites"
            onSubmit={async (e) => {
              e.preventDefault();
              setMensaje('');
              setFallo('');
              const vacio = limiteVacio(formulario, CAMPOS);
              if (vacio) {
                setFallo(`Escribe un número en «${vacio}».`);
                return;
              }
              try {
                await enviar('/api/config', formulario, 'PUT');
                setMensaje('Límites guardados.');
                recargarConfig();
              } catch (err) {
                setFallo((err as Error).message);
              }
            }}
          >
            <p className="dato-menor">Se aplican a toda la cartera. El capital se reparte en partes iguales entre los activos.</p>
            <fieldset disabled={bloqueado}>
              {CAMPOS.map(([k, nombre, ayuda]) => (
                <label key={k}>
                  {nombre}
                  <input type="number" step="any" min="0" value={formulario[k] as number} onChange={(e) => setFormulario({ ...formulario, [k]: e.target.value === '' ? '' : Number(e.target.value) })} />
                  <small>{ayuda}</small>
                </label>
              ))}
              <label className="casilla">
                <span><input type="checkbox" checked={formulario.maquina_tiempo === true} onChange={(e) => setFormulario({ ...formulario, maquina_tiempo: e.target.checked })} /> Máquina del tiempo</span>
                <small>Antes de autorizar una compra, repite 10,000 veces los próximos días con las últimas 60 velas del activo y sus mismas salidas. Si en promedio pierde, no compra.</small>
              </label>
              <button className="primario">Guardar límites</button>
            </fieldset>
            {mensaje && <p className="aviso-bien" role="status">{mensaje}</p>}
            {fallo && <p className="aviso-error" role="alert">{fallo}</p>}
          </form>
        )}
      </section>

      <section>
        <h2>Apagar</h2>
        <p className="explicacion">Cerrar esta ventana no apaga a Astrolabio: sigue vigilando en segundo plano. Apagarlo cierra la aplicación entera: deja de revisar precios y de vigilar las posiciones, que se conservan. Para solo detener las compras y ventas automáticas, usa «Desactivar bot» en la cabecera. Si activaste el arranque automático, vuelve a abrirse al iniciar sesión o desbloquear la laptop.</p>
        <button
          className="peligro"
          onClick={async () => {
            if (window.confirm('¿Apagar Astrolabio? Dejará de vigilar las posiciones hasta que vuelva a abrirse. Para solo detener compras y ventas, cancela y usa «Desactivar bot».')) {
              try {
                await enviar('/api/apagar');
                setApagado('Astrolabio se apagó. Ya puedes cerrar esta ventana.');
              } catch (err) {
                setApagado(`No se pudo apagar: ${(err as Error).message}`);
              }
            }
          }}
        >
          Apagar Astrolabio
        </button>
        {apagado && <p className="aviso-bien" role="status">{apagado}</p>}
      </section>

      <TuContrasena acceso={acceso} alGuardar={recargarAcceso} />

      <section>
        <h2>Privacidad y acceso</h2>
        <p className="explicacion">La contraseña existente permanece protegida. Las sesiones caducan y cerrar sesión revoca su acceso. No compartas contraseñas ni claves de MEXC en el chat o en las notas del proyecto.</p>
      </section>
      <ApiDocumentada />
    </>
  );
}

/** Saldo real de MEXC en solo lectura: con esta conexión el bot no puede comprar, vender ni retirar. */
function CuentaReal({ cuenta, error }: { cuenta: CuentaMexc | null; error: string | null }) {
  const { datos: radar } = useDatos<Radar>('/api/radar', 15_000);
  const precios = Object.fromEntries((radar?.filas ?? []).filter((f) => f.bid != null).map((f) => [f.simbolo, f.bid as number]));
  const valor = valorCuenta(cuenta?.saldos ?? [], precios);
  return (
    <section>
      <h2>Cuenta MEXC</h2>
      <p className="explicacion">Solo lectura: el bot ve tu saldo real, pero con esta conexión no puede comprar, vender ni retirar. Las operaciones siguen en Paper.</p>
      {error && <p className="aviso-error" role="alert">No se pudo leer la cuenta: {error}</p>}
      {cuenta && !cuenta.conectada && <p className="aviso-atencion">{cuenta.error ?? cuenta.motivo}</p>}
      {cuenta?.conectada && (cuenta.saldos.length === 0 ? (
        <p className="vacio">Conectada. La cuenta no tiene saldo todavía.</p>
      ) : (
        <>
          <dl className="lecturas">
            <div><dt>Valor estimado</dt><dd>{usd(valor.total)}</dd><small>al precio de compra del radar{valor.sinPrecio.length ? `; sin precio: ${valor.sinPrecio.join(', ')}` : ''}</small></div>
          </dl>
          <div className="tabla-scroll">
            <table className="tabla-posiciones">
              <thead><tr><th>Activo</th><th>Disponible</th><th>En órdenes</th><th>Valor estimado</th></tr></thead>
              <tbody>
                {valor.filas.map((f) => (
                  <tr key={f.activo}><td>{f.activo}</td><td>{num(f.libre)}</td><td>{num(f.bloqueado)}</td><td>{f.valor == null ? 'sin precio' : usd(f.valor)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <small>Leído hace {cuenta.leido_hace_s ?? 0} s; se vuelve a leer cada 30 s.</small>
        </>
      ))}
    </section>
  );
}

function ApiDocumentada() {
  const { datos, error } = useDatos<EsquemaApi>('/api/openapi.json');
  const filas = rutasDeEsquema(datos);
  return (
    <section>
      <h2>API documentada</h2>
      <p className="explicacion">
        Las rutas que usa este panel. Todas piden sesión, salvo /api/salud, /api/login y /api/logout; /llm/chat pide la clave del gateway. El esquema
        OpenAPI completo está en <a href="/api/openapi.json" target="_blank" rel="noreferrer">/api/openapi.json</a>, también solo con sesión.
      </p>
      {error && <p className="aviso-error" role="alert">No se pudo leer la documentación de la API: {error}</p>}
      <div className="tabla-scroll">
        <table className="tabla-api">
          <thead>
            <tr><th>Método</th><th>Ruta</th><th>Qué hace</th></tr>
          </thead>
          <tbody>
            {filas.map((f) => (
              <tr key={`${f.metodo} ${f.ruta}`}><td>{f.metodo}</td><td><code>{f.ruta}</code></td><td>{f.descripcion}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function TuContrasena({ acceso, alGuardar }: { acceso: Acceso | null; alGuardar: () => void }) {
  const [actual, setActual] = useState('');
  const [nueva, setNueva] = useState('');
  const [repetida, setRepetida] = useState('');
  const [aviso, setAviso] = useState<{ bien: boolean; texto: string } | null>(null);
  const [enviando, setEnviando] = useState(false);
  const personal = acceso?.personal ?? false;
  return (
    <section>
      <h2>Tu contraseña</h2>
      <p className="explicacion">
        {personal && acceso?.desde ? `Desde el ${fechaHora(Date.parse(acceso.desde))} usas una contraseña personal. ` : 'Ahora entras con la clave larga del archivo .env. '}
        Pon una que recuerdes: se guarda solo su huella cifrada en la base de esta laptop, nunca la contraseña. La clave de .env sigue sirviendo para
        recuperar el acceso. Al cambiarla se cierran las demás sesiones.
      </p>
      <form
        className="formulario-clave"
        onSubmit={async (e) => {
          e.preventDefault();
          const problema = validarNuevaClave(nueva, repetida);
          if (problema) {
            setAviso({ bien: false, texto: problema });
            return;
          }
          setEnviando(true);
          try {
            await enviar('/api/acceso', { actual, nueva }, 'PUT');
            setActual('');
            setNueva('');
            setRepetida('');
            setAviso({ bien: true, texto: 'Contraseña guardada. Úsala la próxima vez que entres.' });
            alGuardar();
          } catch (err) {
            setAviso({ bien: false, texto: (err as Error).message });
          } finally {
            setEnviando(false);
          }
        }}
      >
        <label>
          {personal ? 'Contraseña actual o clave de .env' : 'Clave actual del archivo .env'}
          <input type="password" autoComplete="current-password" value={actual} onChange={(e) => setActual(e.target.value)} />
        </label>
        <label>
          Contraseña nueva, de 10 caracteres o más
          <input type="password" autoComplete="new-password" value={nueva} onChange={(e) => setNueva(e.target.value)} />
        </label>
        <label>
          Repite la contraseña nueva
          <input type="password" autoComplete="new-password" value={repetida} onChange={(e) => setRepetida(e.target.value)} />
        </label>
        <button className="primario" disabled={!actual || !nueva || !repetida || enviando}>
          {enviando ? 'Guardando…' : personal ? 'Cambiar contraseña' : 'Guardar contraseña'}
        </button>
      </form>
      {aviso && <p className={aviso.bien ? 'aviso-bien' : 'aviso-error'} role={aviso.bien ? 'status' : 'alert'}>{aviso.texto}</p>}
    </section>
  );
}
