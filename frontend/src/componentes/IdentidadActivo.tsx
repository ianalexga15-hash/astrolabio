import { useState, type CSSProperties } from 'react';
import { IDENTIDAD_ACTIVOS } from '../identidadActivos';

// Logos servidos localmente; procedencia en public/activos/fuentes.json.
const COLORES: Record<string, string> = {
  BTC: '#f5a623', ETH: '#99a9ff', SOL: '#92e4d0', XRP: '#dce3ed',
  BNB: '#f3cf59', DOGE: '#d8bd72', ADA: '#78b3ec', LTC: '#a9c7ed',
  TRX: '#ee9b9f', LINK: '#8ca9ff', AVAX: '#ef9195', DOT: '#e9a6ce',
  NEAR: '#d5e6df', ATOM: '#bec1ef', UNI: '#ee9dc9', SUI: '#86c5ee',
};
const PALETA = ['#a8b7e8', '#c3acd9', '#91c5cf', '#d5be93', '#aabdc9'];

export function IdentidadActivo({ simbolo }: { simbolo: string }) {
  const base = simbolo.replace(/USDT$/, '');
  const [fallido, setFallido] = useState<string | null>(null);
  const identidad = IDENTIDAD_ACTIVOS[base];
  const logo = identidad ? `/activos/${identidad.archivo}` : null;
  const tono = COLORES[base] ?? PALETA[Array.from(base).reduce((n, c) => n + c.charCodeAt(0), 0) % PALETA.length];
  const estilo = { '--activo-color': tono } as CSSProperties;
  return <span className="identidad-activo" style={estilo} title={identidad?.nombre} aria-hidden="true">
    {logo && fallido !== logo ? <img className={base === 'TAO' ? 'identidad-fondo-claro' : undefined} src={logo} alt="" width="24" height="24" decoding="async" onError={() => setFallido(logo)} />
      : <span className="identidad-iniciales">{base.slice(0, 2) || '?'}</span>}
  </span>;
}

export function ActivoCompacto({ simbolo }: { simbolo: string }) {
  return <span className="activo-compacto"><IdentidadActivo simbolo={simbolo} /><strong>{simbolo.replace(/USDT$/, '')}</strong></span>;
}
