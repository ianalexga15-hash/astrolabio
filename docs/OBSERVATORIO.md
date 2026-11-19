# Observatorio de calidad y trading

Implementado por Codex el 2026-11-06. Se encuentra en **Estrategia → Observatorio del modelo**. Seis secciones plegables conservan la interfaz existente.

## Qué hace ahora

- **Salud:** métricas TR/VA y brecha de los experimentos del modelo principal. Se complementa con baselines, ventanas temporales, curvas por época y diagnóstico existentes debajo. No llama subajuste/sobreajuste a una cifra aislada ni entrena modelos nuevos.
- **Sombra:** registra predicciones prospectivas del modelo cargado y un candidato sobre las mismas observaciones. Por defecto el candidato es el pronóstico cero. Opcionalmente, `models/SOMBRA.txt` contiene el nombre de una carpeta de modelo local, con contrato y pesos del formato habitual. Se carga al iniciar el servidor; no cambia ACTIVO.txt ni CARTERA.txt. Para evitar comparaciones retrospectivas, solo se emite dentro de los 15 minutos posteriores al cierre de una vela disponible. Si no llegan velas frescas o el equipo está apagado, ese día no se rellena. Se compara RMSE cuando cierra la vela siguiente, separando activo y versiones. La emisión puede ser posterior al inicio del día objetivo: se registra su hora; esta comparación no representa un backtest con ejecución a la apertura. No hay promoción automática ni promesa de beneficio económico.
- **Concentración:** correlaciones de retornos diarios sobre hasta 90 fechas comunes, mínimo 30; excluye huecos diarios y series constantes. Muestra pares y exposición por activo respecto al patrimonio. Es descriptivo y no sustituye límites de cartera. Las posiciones sin bid usan precio de entrada para valoración; no es precio ejecutable.
- **Grabador/replay:** captura radar aproximadamente cada segundo en un hilo independiente. Conserva precios bid/ask, condiciones, posición, pronóstico, stops y métricas de ciclo. Máximo 86 400 capturas; evita duplicar el mismo libro. Navegación por bloques, selector de activo y reproducción manual/automática. No es almacenamiento de cada tick ni profundidad histórica; no reproduce fills. Conserva timestamps para reconocer huecos. Las órdenes reales del registro se consultan en las fichas, no se reconstruyen al reproducir.
- **Deterioro:** muestra antigüedad global del libro y compara errores de 30 resultados maduros con los 30 anteriores por activo y versión. Umbral descriptivo fijado en 1.5 veces MAE previo, con suelo 1e-6; no se optimiza con VA/TE. Antes de 60 resultados dice evidencia insuficiente. No es prueba de cambio de régimen, control estadístico de falsas alarmas ni estimación de beneficio. No bloquea nuevas entradas automáticamente: convertirlo en un veto requerirá evaluar esa política en Paper; los límites existentes siguen decidiendo.
- **Ficha de decisión:** enlaza decisión, propuesta, riesgo, versión, pronóstico y órdenes por decision_id. Las órdenes sin enlace (por ejemplo del reflejo) se muestran separadas con su motivo. No se inventa una explicación causal con el LLM.

## Ejecución y seguridad

El observatorio arranca con el backend habitual. No hace consultas nuevas a MEXC ni a Ollama; utiliza el radar y velas ya almacenadas. Análisis diario/correlaciones se intenta cada minuto, fuera del bucle de trading. Fallos del observatorio no llaman a iniciar, detener, comprar ni vender. El coste CPU y disco existe aunque sea un hilo separado; queda pendiente medir el impacto en una sesión Paper prolongada con los 40 activos.

Datos guardados en un SQLite independiente junto a la base del bot, sufijo `.observatorio.sqlite3`, cubierto por `data/*.sqlite3*` en la ubicación predeterminada. Si BOT_DB apunta fuera de data/, proteger también esa ubicación y no versionarla. Capturas usan una lista explícita de campos, no guardan secretos. Endpoints `/api/observatorio` y `/api/observatorio/replay` exigen la sesión del panel y límites de paginación. No se añadieron paquetes ni se modificaron pandas/torch.

## Validación

Pruebas nuevas en `verificaciones/test_observatorio.py` para no interferir con tests/ reservado por Claude. Ejecutar explícitamente `python -m pytest -q verificaciones/test_observatorio.py`, además de pytest habitual. Cubren espera del objetivo, no rellenar historia, deduplicación, alineación de fechas, evidencia mínima, exclusión de secretos, autenticación y que observar no altera cuentas/estados/órdenes.

Comprobación visual realizada en instancia aislada con datos ficticios, sin hilos operativos: sección visible y reproducción de una captura de 40 activos. No es evidencia de rentabilidad ni de funcionamiento prolongado en mercado real. Se conserva TE cerrado y no se cambia la estrategia elegida. La utilidad predictiva de un nuevo candidato debe demostrarse con evidencia prospectiva; las herramientas nuevas no hacen automáticamente mejor al modelo.
