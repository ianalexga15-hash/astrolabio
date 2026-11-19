import { useEffect, useRef, useState } from 'react';
import { enviar } from '../api';

/** Preguntas de solo lectura al LLM local. No puede operar ni cambiar límites. */
export function Asistente() {
  const [abierto, setAbierto] = useState(false);
  const [pregunta, setPregunta] = useState('');
  const [respuesta, setRespuesta] = useState('');
  const [fallo, setFallo] = useState('');
  const [pensando, setPensando] = useState(false);
  const boton = useRef<HTMLButtonElement>(null);
  const seccion = useRef<HTMLElement>(null);
  const cerrarConFoco = () => { setAbierto(false); boton.current?.focus(); }; // el foco vuelve al botón, no se pierde en la página

  // Como «Acciones avanzadas»: Escape o un clic fuera lo cierran, para que no tape la página. La pregunta y la respuesta se conservan.
  useEffect(() => {
    if (!abierto) return;
    const cerrar = (e: Event) => {
      const fuera = !boton.current?.contains(e.target as Node) && !seccion.current?.contains(e.target as Node);
      if (e instanceof KeyboardEvent) { if (e.key === 'Escape') cerrarConFoco(); } else if (fuera) setAbierto(false);
    };
    document.addEventListener('click', cerrar);
    document.addEventListener('keydown', cerrar);
    return () => {
      document.removeEventListener('click', cerrar);
      document.removeEventListener('keydown', cerrar);
    };
  }, [abierto]);

  return (
    <>
      <button ref={boton} className="boton-asistente" aria-expanded={abierto} onClick={() => setAbierto(!abierto)}>Asistente</button>
      {abierto && (
        <section ref={seccion} className="asistente" aria-label="Asistente">
          <div className="asistente-cabeza"><h2>Pregunta sobre el estado del bot</h2><button type="button" className="enlace" onClick={cerrarConFoco}>Cerrar</button></div>
          <p className="dato-menor">Responde el modelo local con los datos actuales. Solo lee: no puede operar ni dar consejos de inversión.</p>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setPensando(true);
              setRespuesta('');
              setFallo('');
              try {
                const r = await enviar<{ respuesta: string }>('/api/asistente', { pregunta });
                setRespuesta(r.respuesta || 'El modelo no devolvió texto. Intenta otra pregunta.');
              } catch (err) {
                setFallo(`No hubo respuesta: ${(err as Error).message}`);
              } finally {
                setPensando(false);
              }
            }}
          >
            <textarea rows={3} value={pregunta} maxLength={600} onChange={(e) => setPregunta(e.target.value)} placeholder="¿Por qué no compró hoy?" aria-label="Pregunta" />
            <button className="primario" disabled={pensando || !pregunta.trim()}>{pensando ? 'Consultando Ollama' : 'Preguntar'}</button>
          </form>
          {respuesta && <p className="asistente-respuesta">{respuesta}</p>}
          {fallo && <p className="aviso-error" role="alert">{fallo}</p>}
        </section>
      )}
    </>
  );
}
