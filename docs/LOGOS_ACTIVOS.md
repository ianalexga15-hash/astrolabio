# Identidad visual de activos

Incremento visual, 13 de noviembre de 2026. La primera revisión cubrió 40 criptomonedas. Claude diversificó después el universo: actualmente hay 32 criptomonedas y ocho tokens de MEXC ligados a oro, monedas, índices y empresas. Esta revisión amplía la identidad a esos ocho instrumentos; no incorpora instrumentos ni modifica el motor de trading.

**Actualización (2026-11-19):** la cartera tiene 32 criptomonedas y 8 tokens de acciones, divisas y oro, todos con logo; RUNE entró en lugar de XMR. Los logos de las criptos que salieron (ZIG, ARB, XLM, GRAM, LINK, QNT, BONK, DASH y XMR) se conservan: el historial de Operaciones las sigue mostrando.

Las 40 identidades activas se sirven desde `frontend/public/activos/`, sin solicitudes a terceros al abrir el panel. Se conservan nueve imágenes de instrumentos anteriores para el historial. El registro explícito está en `frontend/src/identidadActivos.ts`. El componente conserva círculos, ticker y botones, y muestra iniciales si un archivo falla o un símbolo nuevo no tiene imagen. Los iconos son decorativos para accesibilidad: el ticker continúa siendo el nombre accesible.

Procedencia y huella SHA-256 individual en `frontend/public/activos/fuentes.json`. Fuentes:

- [Web3 Icons](https://github.com/0xa3k5/web3icons), variantes circulares; licencia MIT declarada en su README, conservado junto a los recursos. El nombre en metadatos no basta: TAO y STRK tenían una representación incorrecta y se sustituyeron.
- [Token Icons](https://github.com/incidunt/token-icons), BONK; README con licencia MIT conservado.
- [Cryptofonts](https://github.com/Cryptofonts/cryptoicons), ENA y TON usado como identidad de GRAM; licencia GPL-3.0 íntegra conservada. Los SVG se distribuyen como archivos independientes sin modificar. La marca sigue perteneciendo a su titular.
- [Cryptologo](https://cryptologo.org/): ETHFI/ether.fi, TAO/Bittensor y STRK/Starknet. Uso identificativo de las respectivas marcas, sin insinuar afiliación. Conservar procedencia al redistribuir.

GRAM se identifica con TON conforme a la página de [MEXC GRAM/USDT](https://www.mexc.fm/exchange/GRAM_USDT), que lo describe como GRAM(prev.Toncoin). No se usa el logo del otro token Gram que cambió a GRM.

Astrolabio conserva su astrolabio/brújula original como SVG vectorial, con geometría refinada, aro metálico, contraste y tamaño de 34 px en cabecera. Login y favicon usan el mismo archivo.

## Identidades de los instrumentos incorporados

- EUR: bandera de la Unión Europea; BRL: Brasil. SVG de [flag-icons](https://github.com/lipis/flag-icons), MIT, licencia incluida.
- AAPLX y METAX: marcas de Apple y Meta desde [Simple Icons](https://github.com/simple-icons/simple-icons), con contraste adaptado. Se conservan licencia y aviso de marcas.
- MSFTON: símbolo geométrico de cuatro colores que identifica Microsoft.
- GOLD(XAUT): ilustración propia de lingote, sin insinuar que sea el logo oficial de XAUT.
- SPYON y QQQON: pictogramas propios de índices con 500 y 100, respectivamente. No se presentan como logos oficiales de SPDR/Invesco/Ondo.

El tooltip identifica el subyacente y, donde corresponde, xStocks/Ondo. Son tokens cotizados en MEXC; el logo de una empresa no debe hacer creer que se compran sus acciones directamente. Futuras ampliaciones deben mapear símbolo, emisor y subyacente explícitamente.

## Verificación

40 imágenes cargadas en el Radar de una copia aislada con datos ficticios. Revisión visual del catálogo completo, detección y corrección de colisiones de ticker, y contraste especial para TAO. Sin scripts, manejadores de eventos ni recursos externos dentro de los SVG importados. Build, 54 pruebas Vitest y 560 pruebas Python aprobadas en este incremento; no hay cambios en trading, cuenta ni secretos.
