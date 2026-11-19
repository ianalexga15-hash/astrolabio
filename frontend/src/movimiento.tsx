import { useRef } from 'react';
import { type Cambio, idsNuevos, puntosNuevos, registrarCambio } from './logica';

/** Cambios reales de un valor. La primera carga no cuenta; `veces` sirve de key para repetir una animación solo al cambiar. */
export function useCambio(valor: Cambio['valor']): Cambio {
  const r = useRef<Cambio>({ valor: null, veces: 0, sube: null });
  r.current = registrarCambio(r.current, valor);
  return r.current;
}

/** Identificadores que no estaban en la lectura anterior de la lista; la primera lectura no marca nada. */
export function useNuevos(lista: { id: number }[] | null | undefined): Set<number> {
  const r = useRef<{ lista: unknown; vistos: Set<number> | null; nuevos: Set<number> }>({ lista: null, vistos: null, nuevos: new Set() });
  if (lista && lista !== r.current.lista) {
    const ids = lista.map((x) => x.id);
    r.current = { lista, vistos: new Set(ids), nuevos: idsNuevos(r.current.vistos, ids) };
  }
  return r.current.nuevos;
}

/** Cifra con destello tenue y flecha de dirección solo cuando el valor cambia de verdad. */
export function CifraViva({ valor, texto, como: Etiqueta = 'td' }: { valor: number | null | undefined; texto: string; como?: 'td' | 'dd' }) {
  const c = useCambio(valor);
  const sentido = c.sube == null ? null : c.sube ? 'sube' : 'baja';
  return (
    <Etiqueta key={c.veces} className={c.veces ? `destello-${sentido}` : undefined} title={sentido ? `${sentido === 'sube' ? 'Subió' : 'Bajó'} en el último cambio` : undefined}>
      {sentido && (
        <svg className={`flecha flecha-${sentido}`} viewBox="0 0 8 8" aria-hidden="true">
          <path d={sentido === 'sube' ? 'M4 1 7 6H1z' : 'M4 7 1 2h6z'} />
        </svg>
      )}
      {texto}
    </Etiqueta>
  );
}

/** Tramo final que acaba de llegar a una serie. `identidad` (por ejemplo el activo) evita confundir un cambio de activo con un dato nuevo. */
export function useCola(etiquetas: string[], identidad = ''): { desde: number | null; veces: number } {
  const ultima = etiquetas.length ? etiquetas[etiquetas.length - 1] : null;
  const r = useRef({ identidad, ultima: null as string | null, desde: null as number | null, veces: 0 });
  if (identidad !== r.current.identidad) r.current = { identidad, ultima, desde: null, veces: r.current.veces };
  else if (ultima !== r.current.ultima) {
    const desde = puntosNuevos(r.current.ultima, etiquetas);
    r.current = { identidad, ultima, desde, veces: r.current.veces + (desde == null ? 0 : 1) };
  }
  return r.current;
}
