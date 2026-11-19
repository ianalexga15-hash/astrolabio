# Seguridad

Astrolabio es un proyecto personal que opera en modo **Paper**, con dinero virtual. Aquí está qué se protege y cómo, qué hacer si una clave se filtra y cómo avisar de un problema.

## Qué nunca entra al repositorio

| Qué | Dónde vive | Por qué |
| --- | --- | --- |
| Claves del panel, del gateway del LLM y de MEXC | `.env`, solo en esta laptop | Con ellas se entra al panel o se lee la cuenta. `.env.example` trae los nombres, sin valores |
| Base del bot (`data/bot.sqlite3` y la del observatorio) | `data/` | Guarda la huella de tu contraseña, las sesiones y las operaciones |
| Texto extraído de un libro | `tmp/` | Tiene derechos de autor |
| Skills de terceros | `.claude/skills/` | No son del proyecto |
| Dependencias y compilados | `.venv/`, `node_modules/`, `frontend/dist/` | Se reconstruyen con `pip install` y `npm install` |

`.gitignore` también ignora, en cualquier carpeta, `*.sqlite3`, `*.db`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.kdbx` e `id_rsa*`. Las claves tampoco van en el código, los logs, las notas ni el chat. `data/` sí versiona precios públicos de MEXC (velas), que no son personales.

## Cómo está protegido

- **Solo Paper.** No existe ninguna ruta que envíe órdenes reales a MEXC. Crearla sería la etapa 4 y necesita una decisión explícita de Alex.
- **MEXC en solo lectura.** La clave se crea solo con *View Account Details* y *View Order Details*: con ella no se puede comprar, vender ni retirar. El cliente firmado, `bot/cuenta_mexc.py`, solo lee la cuenta y las comisiones.
- **Panel solo en esta laptop.** El servidor escucha en `127.0.0.1` y rechaza otros nombres de host.
- **Contraseña guardada como huella scrypt.** La base guarda la huella con sal, nunca la contraseña. `BOT_ADMIN_KEY` de `.env` sirve para recuperar el acceso.
- **Límite de intentos.** Tras 5 claves fallidas seguidas desde una misma IP, esa IP queda bloqueada 30 segundos. El aviso dice cuántos segundos faltan, también en la cabecera `Retry-After`, y nunca dice si la clave existe. Cada intento cuenta antes de comprobar la clave, así que mandar muchos a la vez no se salta el límite. Una clave mala tarda lo mismo con o sin contraseña personal. Cambiar la contraseña en Sistema comparte este límite. El servidor no cree en la cabecera `X-Forwarded-For`, así que cambiarla no cambia la IP.
- **Sesiones guardadas como huella.** Cada sesión es un token aleatorio de 8 horas en una cookie `HttpOnly`, `SameSite=Strict` y `Max-Age` de 8 horas; al cerrar sesión se borra con los mismos atributos. La base guarda solo su huella SHA-256 y su vencimiento; cerrar sesión o cambiar la contraseña las borra.
- **Sesión obligatoria.** Toda ruta `/api/*` pide sesión salvo `/api/salud`, `/api/login` y `/api/logout`, que solo borra la cookie que trae. Lo que cambia algo (control, configuración, apagar, contraseña, notas) solo acepta POST o PUT y se rechaza si viene de otro sitio. Una prueba recorre todas las rutas.
- **Encabezados en cada respuesta**, también en los errores 403 y 500. La CSP solo deja cargar scripts, estilos e imágenes del propio panel, sin `'unsafe-inline'`, y prohíbe meterlo en un marco ajeno. Van además `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy` y `Cross-Origin-Resource-Policy` en `same-origin`, y una `Permissions-Policy` que apaga cámara, micrófono, ubicación, pagos, USB y las demás funciones que el panel no usa.
- **Errores sin detalles internos.** Un fallo inesperado responde un texto fijo; la traza queda solo en el log local. El panel nunca muestra la carpeta del proyecto ni la del usuario, aunque un error las traiga. Los errores de MEXC dicen la ruta, el código HTTP y el código de MEXC, sin repetir su texto. Una ruta `\\host\...` pedida al panel nunca se intenta abrir.
- **LLM local.** En ejecución el bot no llama a Claude, a Codex ni a servicios en la nube: solo a Ollama en esta laptop, por un gateway con su propia clave (`BOT_LLM_KEY`). El LLM propone; los controles de riesgo deterministas deciden.

## Antes de subir a GitHub

```bash
.venv\Scripts\python scripts\revisar_secretos.py
```

Revisa cada versión de cada archivo en todas las ramas, los mensajes de los commits y los archivos que git versionaría. Busca los valores reales de `.env`, las huellas de la contraseña y de las sesiones, y formatos de claves de otros servicios, con reglas al estilo de gitleaks. Nunca muestra un valor: solo el tipo, el commit y el archivo. En esta carpeta corre solo antes de cada `git push`, con el gancho `.git/hooks/pre-push`, y si encuentra algo cancela la subida. En otra copia del proyecto, instala el gancho con:

```bash
copy scripts\pre-push .git\hooks\pre-push
```

Además, `tests/test_secretos.py` falla si una clave de `.env` o una huella del panel entra a un archivo versionable.

## En GitHub

- El repositorio es **público** desde el 2026-11-19. Los commits usan como autor el correo privado de GitHub (noreply), no el personal. Antes de publicarlo se revisó que el historial no tuviera claves, `.env`, bases de datos, el texto del libro (`tmp/`) ni saldos reales de MEXC en las capturas.
- Desde que es público están activos el secret scanning y la push protection de GitHub. Con el repositorio privado, GitHub respondía HTTP 422 al activarlos. El gancho `pre-push` de esta carpeta sigue revisando antes de cada subida.
- Están activas las alertas de Dependabot y sus actualizaciones de seguridad. Antes de aceptar una que cambie `pandas` o `torch`, prueba el import en esta laptop: el Control de aplicaciones de Windows bloquea binarios nuevos.

## Dependencias

Para revisarlas:

```bash
.venv\Scripts\python -m pip_audit
```

```bash
cd frontend && npm audit
```

Resultado del 2026-11-14:
- **npm:** 0 vulnerabilidades. vitest pasó de 3.2.7 a 4.1.12, que corrige las alertas de `vitest`, `@vitest/mocker` y `tinypool`. Solo se usa para las pruebas del panel; `npm run build` y las 54 pruebas pasan.
- **Python:** `tornado` pasó a 6.6.1 y `setuptools` a 81.0.0. Quedan dos avisos de `setuptools`, corregidos en las versiones 83 y 84, porque `torch 2.12.1+cpu` exige `setuptools<82`. El bot en marcha no usa `setuptools`: lo pide `torch` para compilar extensiones.
- **Sin auditar:** `pip-audit` no puede revisar `torch 2.12.1+cpu`, porque esa compilación no está en PyPI.
- **Sin cambios:** `pandas` y `torch` siguen en sus versiones fijas, y ambos importan bien.

## Si una clave se filtra

1. **Rótala primero**, antes de limpiar nada:
   - MEXC: borra la clave en *API Management*, crea otra de solo lectura y pégala en `.env`.
   - Panel: cambia `BOT_ADMIN_KEY` en `.env` y tu contraseña en Sistema → Tu contraseña; eso cierra las demás sesiones.
   - Gateway del LLM: cambia `BOT_LLM_KEY` en `.env`.
   - Reinicia el bot.
2. **Sácala del historial** con `git filter-repo --replace-text` y vuelve a subir. Una clave que llegó a GitHub se da por perdida aunque se borre: por eso se rota primero.

## Cómo avisar de un problema

Avísale a Alex en privado. No abras un issue con los detalles ni pegues claves en issues, commits, notas o chats.
