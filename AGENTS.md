# Reglas del proyecto para Claude y Codex

Los dos asistentes leen este archivo al empezar. Alex decide y su instrucción más reciente prevalece.

## Antes de editar

1. Ejecuta `.venv/Scripts/python scripts/nota.py estado`: muestra la visión de Alex, lo que está en curso, lo pendiente y lo último hecho.
2. Lee `docs/BASE_COMPARTIDA_CLAUDE_CODEX.md` (decisiones y estado) y `docs/COORDINACION.md` (quién hace qué).
3. Revisa `git status`: el otro asistente puede estar trabajando en esta misma carpeta.
4. Anota tu tarea y sus archivos en `docs/COORDINACION.md`. No edites archivos que el otro tenga en curso.

## Mientras trabajas

Registra cada avance como nota del desarrollo, no solo al final: `scripts/nota.py agregar --origen claude|codex|ambos|alex --tipo ... --galaxia ... --titulo ... --texto ...`. Conecta notas con `[[Título exacto]]`. Se ven como universo en la pestaña Universo del panel y también abren en Obsidian. Son memoria del proyecto, no neuronas del modelo. Marca lo inconcluso con el tipo `En curso` y actualízalo con `--id`.

## Antes de terminar

Corre `.venv/Scripts/python -m pytest -q` y, si tocaste el panel, `npm run build` y `npx vitest run` en `frontend/`.

## Reglas fijas

- Etapa actual: MEXC en modo Paper más la cartera Real (etapa 4, decisión de Alex del 2026-11-26). La Real repite en la cuenta Spot lo que Paper ejecuta, desde `bot/real.py`, arranca apagada y solo Alex la enciende desde el panel escribiendo la confirmación. Las órdenes reales solo salen de `bot/real.py`; no agregues otras rutas de órdenes, ni rutas para mandar órdenes a mano, ni retiros o transferencias. Alex decidió el 2026-11-27 que el envío real no se bloquea, aunque la rúbrica del curso lo penalice: no agregues bloqueos de la cartera Real.
- Las claves y otros secretos no van en el repositorio, los logs ni el chat.
- El bot en ejecución no llama a Claude ni a Codex. Su único LLM es Ollama local.
- El LLM propone; los controles de riesgo deterministas deciden si se ejecuta.
- Cada resultado se declara como propuesto, simulado, observado o validado.
- Haz commit solo si Alex lo pide.
- `tmp/` no se versiona: contiene texto extraído del libro.
- El repositorio es público. Quedan solo en esta laptop, sin versionar (`.git/info/exclude`): `docs/` salvo sus cuatro documentos técnicos, `notas/`, las capturas y `output/`. No los subas.
- TE se abre una sola vez, con el sistema congelado. El entrenamiento en CPU es solo de desarrollo y nunca abre TE.
- No cambies las versiones fijas de `pandas` y `torch` sin probar el import: Windows (Control de aplicaciones) bloquea binarios nuevos. No desactives esa protección.
