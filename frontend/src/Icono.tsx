const trazos: Record<string, string> = {
  radar: 'M12 3a9 9 0 1 0 9 9M12 7a5 5 0 1 0 5 5M12 12l8-8M12 12h.01',
  mercado: 'M4 19V5M4 19h16M7 14l4-5 4 3 5-7',
  resumen: 'M4 4h6v7H4zM14 4h6v4h-6zM4 15h6v5H4zM14 12h6v8h-6z',
  operaciones: 'M4 7h15m-4-4 4 4-4 4M20 17H5m4-4-4 4 4 4',
  estrategia: 'M5 5h14M5 12h14M5 19h14M8 3v4M16 10v4M10 17v4',
  cerebro: 'M9 4 4 9l3 8 8 3 5-7-5-9zM9 4l3 8-5 5M12 12l8 1M12 12l3 8M4 9l8 3 3-8',
  auditoria: 'M8 3H5v18h14V3h-3M8 2h8v4H8zM8 11h8M8 16h5',
  sistema: 'M4 4h16v12H4zM8 20h8M12 16v4M7 8l2 2-2 2M12 12h4',
  universo: 'M12 2v4M12 18v4M2 12h4M18 12h4M5 5l3 3M16 16l3 3M5 19l3-3M16 8l3-3M12 8l4 4-4 4-4-4z',
  salir: 'M9 4H4v16h5M13 7l5 5-5 5M8 12h10',
  buscar: 'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14M15 15l6 6',
};

export function Icono({ nombre, size = 19 }: { nombre: string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={trazos[nombre] ?? trazos.radar} /></svg>;
}
