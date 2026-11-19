# Resultados intradía de 15 minutos

Generado el 2026-11-09 02:23 UTC por `scripts/evaluar_intradia.py` con `intradia-candidatas-0.1`. **Resultados simulados**, no validados; ninguna candidata se promueve al bot.

## Datos

MEXC GET /api/v3/klines interval=15m, datos públicos. Descargados el 2026-11-09T02:20. Periodo de 2026-08-12 00:00 a 2026-11-09 02:15 UTC.

| Activo | Velas | Duplicados | Huecos | OHLC incoherente | Volumen cero | Huella SHA-256 |
| --- | --- | --- | --- | --- | --- | --- |
| BTCUSDT | 8553 | 0 | 0 | 0 | 0 | `f27827f2aa48627c…` |
| ETHUSDT | 8553 | 0 | 0 | 0 | 0 | `1d53cf2877ca709f…` |
| SOLUSDT | 8553 | 0 | 0 | 0 | 0 | `9a80941f5a7b9265…` |

## Supuestos fijados antes de medir

- **Señal y entrada:** la señal se conoce al cierre de una vela y solo permite comprar en la apertura de la siguiente.
- **Salidas:** stop a 2 ATR14 y objetivo a 3 ATR14 de la última vela cerrada, máximo 16 velas (4 horas). Si una vela toca ambos, cuenta primero el stop; un salto bajo el stop sale a la apertura disponible; la salida por tiempo usa la apertura siguiente.
- **Tamaño:** riesgo de 0.25 % del capital hasta el stop, con exposición máxima de 20 %. Capital de 10,000 por activo y una posición a la vez.
- **Costos:** comisión real de MEXC del par por lado (`config/comisiones.json`: 0.05 % en BTC, ETH y SOL) más 2 pb de deslizamiento en lo que se ejecuta a mercado. Escenario de costos altos: el doble de comisión y 10 pb. El objetivo sale a su precio, pero paga comisión: no se supone llenado maker gratis.
- **Ventanas:** TR1 de 2026-08-12 a 2026-08-31, TR2 de 2026-09-01 a 2026-09-20, TR3 de 2026-09-21 a 2026-10-10, VA de 2026-10-11 a 2026-10-30. Del 2026-10-31 en adelante queda reservado y no se evalúa.
- **Indicadores:** se calculan con toda la historia anterior a cada vela (causales). Sin libro histórico: no se afirma una simulación fiel de la profundidad.
- **Cierre de vela:** MEXC marca el cierre en el inicio de la vela siguiente; el generador espera el último milisegundo, así que se resta 1 ms.

## Escenario: base

Tres monedas juntas, cada una con 10,000. Salidas en orden: objetivo / stop / tiempo / fin de ventana.

| Estrategia | Ventana | Señales | Operaciones | Acierto | Factor de beneficio | Resultado neto | Rendimiento | Caída máx. | Duración media | Exposición | Salidas | Comprar y mantener |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tendencia | TR1 | 198 | 100 | 45% | 1.07 | 41.55 USDT | +0.14% | 1.73% | 2.2 h | 15.1% | 37/39/24/0 | +29.69% |
| tendencia | TR2 | 206 | 108 | 41% | 0.65 | -242.42 USDT | -0.81% | 1.30% | 2.5 h | 18.4% | 25/43/40/0 | +5.98% |
| tendencia | TR3 | 181 | 96 | 33% | 0.42 | -360.52 USDT | -1.20% | 1.73% | 2.4 h | 16.0% | 21/40/35/0 | -1.46% |
| tendencia | VA | 165 | 93 | 31% | 0.51 | -361.10 USDT | -1.20% | 1.75% | 2.3 h | 15.0% | 17/43/33/0 | -10.05% |
| recuperacion | TR1 | 9 | 9 | 22% | 0.67 | -16.39 USDT | -0.05% | 0.38% | 2.5 h | 1.6% | 1/4/4/0 | +29.69% |
| recuperacion | TR2 | 14 | 14 | 29% | 0.15 | -70.51 USDT | -0.24% | 0.40% | 3.0 h | 2.9% | 0/5/9/0 | +5.98% |
| recuperacion | TR3 | 11 | 11 | 18% | 0.12 | -138.53 USDT | -0.46% | 0.81% | 1.5 h | 1.1% | 1/9/1/0 | -1.46% |
| recuperacion | VA | 23 | 23 | 48% | 0.80 | -32.80 USDT | -0.11% | 0.52% | 2.6 h | 4.1% | 7/8/8/0 | -10.05% |
| ruptura | TR1 | 82 | 60 | 47% | 0.91 | -35.75 USDT | -0.12% | 1.18% | 2.1 h | 8.6% | 21/24/15/0 | +29.69% |
| ruptura | TR2 | 93 | 72 | 35% | 0.51 | -299.58 USDT | -1.00% | 1.87% | 1.6 h | 8.2% | 18/41/13/0 | +5.98% |
| ruptura | TR3 | 100 | 73 | 33% | 0.44 | -322.80 USDT | -1.08% | 2.10% | 2.0 h | 10.0% | 16/43/14/0 | -1.46% |
| ruptura | VA | 70 | 52 | 48% | 1.23 | 64.34 USDT | +0.21% | 0.71% | 2.1 h | 7.7% | 14/19/19/0 | -10.05% |

## Escenario: costos altos

Tres monedas juntas, cada una con 10,000. Salidas en orden: objetivo / stop / tiempo / fin de ventana.

| Estrategia | Ventana | Señales | Operaciones | Acierto | Factor de beneficio | Resultado neto | Rendimiento | Caída máx. | Duración media | Exposición | Salidas | Comprar y mantener |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tendencia | TR1 | 198 | 113 | 34% | 0.51 | -513.64 USDT | -1.71% | 2.88% | 1.8 h | 13.7% | 33/60/20/0 | +29.36% |
| tendencia | TR2 | 206 | 116 | 26% | 0.24 | -876.89 USDT | -2.92% | 3.24% | 2.1 h | 17.1% | 22/59/35/0 | +5.71% |
| tendencia | TR3 | 181 | 104 | 18% | 0.16 | -924.09 USDT | -3.08% | 3.87% | 1.9 h | 13.9% | 16/63/25/0 | -1.72% |
| tendencia | VA | 165 | 95 | 21% | 0.24 | -818.57 USDT | -2.73% | 3.03% | 2.0 h | 13.5% | 13/53/29/0 | -10.28% |
| recuperacion | TR1 | 9 | 9 | 22% | 0.35 | -52.39 USDT | -0.17% | 0.53% | 2.5 h | 1.6% | 1/4/4/0 | +29.36% |
| recuperacion | TR2 | 14 | 14 | 7% | 0.02 | -134.98 USDT | -0.45% | 0.63% | 3.0 h | 2.9% | 0/5/9/0 | +5.71% |
| recuperacion | TR3 | 11 | 11 | 9% | 0.08 | -177.67 USDT | -0.59% | 0.93% | 1.4 h | 1.0% | 1/9/1/0 | -1.72% |
| recuperacion | VA | 23 | 23 | 35% | 0.32 | -183.22 USDT | -0.61% | 0.95% | 2.3 h | 3.7% | 6/11/6/0 | -10.28% |
| ruptura | TR1 | 82 | 62 | 34% | 0.44 | -349.77 USDT | -1.17% | 1.94% | 1.7 h | 7.3% | 20/32/10/0 | +29.36% |
| ruptura | TR2 | 93 | 72 | 26% | 0.29 | -596.83 USDT | -1.99% | 3.15% | 1.5 h | 7.7% | 17/43/12/0 | +5.71% |
| ruptura | TR3 | 100 | 73 | 21% | 0.24 | -614.87 USDT | -2.05% | 3.00% | 1.6 h | 8.0% | 13/49/11/0 | -1.72% |
| ruptura | VA | 70 | 52 | 33% | 0.58 | -187.06 USDT | -0.62% | 1.08% | 2.0 h | 7.3% | 12/22/18/0 | -10.28% |
## Lectura

Escrita a mano por Claude el 2026-11-08 después de revisar las tablas, para los datos con las huellas de arriba. Si los datos cambian, hay que volver a escribirla.

- **Ninguna candidata muestra una ventaja estable.** Con costos base, ninguna gana en más de una de las cuatro ventanas.
  - **Tendencia:** perdió en TR2, TR3 y VA, con factor de beneficio de 0.42 a 0.65, y solo ganó +0.14 % en TR1.
  - **Ruptura:** perdió en las tres ventanas de TR, de −0.12 % a −1.08 %, y ganó +0.21 % en VA, con factor 1.23 en 52 operaciones.
  - **Recuperación:** perdió en todas y tuvo muy pocas operaciones (9 a 23 por ventana).
- **Un buen resultado aislado en VA no basta.** Llega después de tres ventanas de TR negativas, y quedarse con la mejor de tres candidatas añade sesgo de selección.
- **Los costos pesan tanto como la regla.** Con el doble de comisión y 10 pb de deslizamiento, las tres pierden en todas las ventanas (factor de beneficio de 0.02 a 0.58). Un objetivo de 3 ATR en unas dos horas ronda el 0.6 % del precio, del mismo orden que el costo de ida y vuelta en el escenario alto.
- **Frente a las referencias:** el efectivo (0 %) fue mejor que las tres en la mayoría de las ventanas. Comprar y mantener ganó con claridad en TR1 (+29.7 %) y TR2 (+6.0 %) y perdió en TR3 (−1.5 %) y VA (−10.1 %). Si las candidatas perdieron menos en las caídas fue porque pasan entre el 82 % y el 99 % del tiempo en efectivo, no porque acierten.
- **Decisión:** no se promueve ninguna al bot. Si se sigue con estas candidatas, conviene revisar primero la salida y los costos, por ejemplo con un objetivo más amplio que el costo de ida y vuelta, antes que los criterios de entrada. Cualquier cambio de regla se fija antes de medir y se prueba con un periodo nuevo; el reservado, del 2026-10-31 en adelante, sigue sin consultar.
