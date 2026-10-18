# UNED Campus MCP Server

[![CI](https://github.com/kta41/mcp-uned/actions/workflows/ci.yml/badge.svg)](https://github.com/kta41/mcp-uned/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Servidor MCP que conecta tu asistente (Copilot en VS Code, Claude, Cursor…) con
el campus virtual de la UNED (`agora.uned.es`, Moodle) y lo convierte en un
**apoyo de estudio**: descarga los materiales por asignatura, extrae e indexa su
texto, genera fichas (profesorado, contacto, evaluación, fechas, clases, temario),
sigue tu progreso por tema, planifica la semana y exporta las fechas a `.ics`.
Incluye un agente de Copilot (`uned-tutor`), prompts `/uned-*` y una skill.

> Proyecto personal, **no oficial** y sin relación con la UNED. Usa la misma API
> REST que la app móvil oficial de Moodle, con tu propia sesión.

## Cómo funciona

El campus de la UNED autentica por **SSO** (login.uned.es), así que el servidor
no puede pedir tu contraseña directamente. En su lugar usa el mismo flujo que
la app móvil oficial de Moodle:

1. La herramienta `uned_login` abre una ventana de Chromium.
2. **Tú** haces login vía SSO (tu contraseña nunca pasa por el código ni se guarda).
3. El servidor captura automáticamente el *token* de web service que la app
   móvil recibiría (endpoint `admin/tool/mobile/launch.php`).
4. Todas las demás herramientas consultan la REST API de Moodle con ese token.

El token se guarda en `~/.uned-mcp/token.json` (solo en tu máquina, permisos
600). Es revocable cambiando tu contraseña o borrando el archivo.

## Requisitos

- Python 3.10+ y [uv](https://docs.astral.sh/uv/).
- Chromium de Playwright (solo para el login SSO).
- Opcional, para buscar en PDF escaneados: `ocrmypdf` y `tesseract-ocr-spa`.

## Instalación (una vez)

```bash
git clone https://github.com/kta41/mcp-uned.git
cd mcp-uned
uv sync
uv run playwright install chromium
# opcional (Debian/Ubuntu): OCR de PDF escaneados
sudo apt install ocrmypdf tesseract-ocr-spa
```

## Instalación en VS Code (como mcp-bruno)

```bash
uv run python scripts/install_vscode.py --with-copilot-customizations
```

- Registra el servidor `uned` en el `mcp.json` del perfil de VS Code (en WSL, vía
  `wsl.exe` en el perfil de Windows y directo en `~/.vscode-server`), copiando
  las variables de entorno de la tabla de abajo si están definidas. El resto de
  servidores de `mcp.json` no se tocan.
- Copia el agente `uned-tutor` y los prompts `/uned-hoy`, `/uned-ficha`,
  `/uned-resumen`, `/uned-test`, `/uned-plan`, `/uned-trabajo` a `User/prompts`.
- Copia la skill `estudio-uned` a `~/.copilot/skills`.

Recarga VS Code, elige el agente **uned-tutor** en el chat o lanza `/uned-hoy`.

## Configuración manual del cliente MCP

`mcp.json`:

```json
{
  "servers": {
    "uned": {
      "command": "uv",
      "args": ["run", "--directory", "/ruta/completa/a/mcp-uned", "uned-mcp"]
    }
  }
}
```

### Variables de entorno

| Variable | Por defecto | Uso |
|---|---|---|
| `UNED_STUDY_DIR` | `~/UNED` | Carpeta de estudio |
| `UNED_MCP_HOME` | `~/.uned-mcp` | Token y sesión SSO (permisos 600) |
| `UNED_MCP_MAX_FILE_MB` | `80` | Tamaño máximo de archivo a descargar |
| `UNED_MCP_DOWNLOAD_DELAY` | `0.4` | Pausa (s) entre descargas |
| `UNED_TITULACION_URL` | autodetectada | Página de la titulación en uned.es (para localizar guías docentes) |
| `UNED_MCP_CA_BUNDLE` / `REQUESTS_CA_BUNDLE` | — | Bundle de CA para redes con proxy TLS |
| `UNED_MCP_PROXY_CA_ORG` | — | Organización(es) de la CA del proxy (ver abajo) |

### Red con proxy TLS (corporativa)

Si tu red re-firma el TLS, define `UNED_MCP_CA_BUNDLE` (o `REQUESTS_CA_BUNDLE`) con
el bundle de CA: lo usa httpx para la API. Chromium no usa ese bundle, así que el
login confía explícitamente en la CA del proxy (`--ignore-certificate-errors-spki-list`):

- si `UNED_MCP_CA_BUNDLE` contiene solo la CA del proxy, no hace falta nada más;
- si el bundle tiene muchas CA, indica la organización de la del proxy con
  `UNED_MCP_PROXY_CA_ORG="MiEmpresa"` (varias separadas por comas).

Define estas variables antes de ejecutar `scripts/install_vscode.py` para que se
copien al `mcp.json`.

## Primer uso

Dile a tu asistente: **«haz login en la UNED»**. Se abrirá el navegador,
inicia sesión con tu cuenta UNED (DNI/NIE/usuario + contraseña en la página
oficial del SSO) y el token se capturará solo. Solo hay que hacerlo una vez;
si el token caduca algún día, repite el login.

Puedes verificar el estado sin abrir el asistente:

```bash
uv run uned-mcp check   # estado del token
uv run uned-mcp login   # login desde terminal (reutiliza la sesión guardada si sigue válida)
uv run uned-mcp sync    # primera descarga completa (recomendado desde terminal: tarda varios minutos)
uv run uned-mcp sync "microeconomía" --forzar   # una asignatura, re-procesando todo
uv run uned-mcp plan --horas 12 --semanas 4
uv run uned-mcp resumen --notify             # sync + notificación de escritorio si hay cambios (para cron)
```

## Carpeta de estudio (`~/UNED`)

```
~/UNED/
  README.md               índice: asignaturas, próximas clases y entregas, avance
  plan-semanal.md         plan generado (uned_plan)
  calendario.ics          entregas, fechas y clases, con aviso 2 días antes (importable en Outlook/Google)
  novedades.md            cambios de la última sincronización
  _General/               espacios que no son asignaturas (acogida, coordinación de la titulación)
  <Asignatura>/
    ficha.md              profesorado y contacto, evaluación/ponderación, clases, entregas y estado,
                          temario con progreso, metodología, materiales, bibliografía, anuncios
    guia-docente.pdf/.md  guía oficial (uned.es), localizada por el código de la asignatura
    materiales/           archivos del aula, por sección (y Tareas/ con los enunciados)
    texto/                texto extraído en markdown con marcas «## [p. N]» para citar
    apuntes/              resúmenes/tests guardados por el agente
    progreso.json         estado de cada tema (pendiente → leyendo → visto → repasado → dominado)
    enlaces.md            enlaces externos del aula
```

Cambia la ubicación con `UNED_STUDY_DIR`. La sincronización es incremental: solo
descarga lo modificado y detecta materiales, plazos y anuncios nuevos. No descarga
vídeo/audio ni archivos de más de 80 MB.

**PDF escaneados:** si un PDF no tiene capa de texto y `ocrmypdf` está instalado, la
sincronización genera `<nombre>.ocr.pdf` y lo indexa (también los que quedaron
pendientes de sincronizaciones anteriores). Sin `ocrmypdf` se marcan «pendiente OCR».

## Qué puedes preguntar después

| Pregunta de ejemplo | Herramienta que usa |
|---|---|
| «¿Qué tengo pendiente esta semana?» | `uned_novedades` |
| «Lista mis cursos» | `uned_cursos` |
| «¿Entregas en los próximos 15 días?» | `uned_entregas` |
| «¿Hay anuncios nuevos de los profesores?» | `uned_anuncios` |
| «¿Se han publicado notas?» | `uned_notas` |
| «¿Eventos del calendario este mes?» | `uned_eventos` |
| «¿Cuándo son las próximas clases?» | `uned_clases` |
| «Dame el contenido del curso X» | `uned_curso_contenido` |
| «Descarga/actualiza todo el campus» | `uned_sincronizar` |
| «Ficha de Derecho Constitucional» | `uned_ficha` |
| «¿Qué dicen los materiales sobre la ventaja comparativa?» | `uned_buscar` + `uned_leer` |
| «Resúmeme el tema 3 de Psicología del Desarrollo» | `/uned-resumen` |
| «Hazme un test de Historia del Arte» | `/uned-test` |
| «Plan para 12 h/semana» | `uned_plan` |
| «He terminado el tema 2 de Microeconomía» | `uned_progreso_marcar` |

## Herramientas expuestas

- `uned_login` — login SSO + captura de token (abre navegador).
- `uned_logout` — borra token y sesión locales.
- `uned_cursos` — cursos matriculados con progreso.
- `uned_entregas(dias)` — tareas con fecha límite próximos N días.
- `uned_eventos(dias)` — eventos de calendario próximos N días.
- `uned_clases(asignatura, incluir_pasadas)` — clases/jornadas (día, hora, profesor, online/presencial y acceso) leídas de los horarios publicados en el campus.
- `uned_anuncios(dias)` — últimos avisos de los foros de noticias por curso.
- `uned_notas` — calificaciones publicadas por curso.
- `uned_novedades(dias)` — resumen combinado de todo lo anterior.
- `uned_curso_contenido(courseid)` — secciones y recursos de un curso.
- `uned_sincronizar(asignatura, forzar)` — descarga materiales, guía docente, plazos y anuncios; regenera fichas, índice y `.ics`.
- `uned_ficha(asignatura)` — ficha completa de la asignatura.
- `uned_materiales(asignatura)` — materiales descargados con páginas y ruta del texto.
- `uned_buscar(consulta, asignatura, limite)` — búsqueda de texto completo (sin acentos) con archivo y página.
- `uned_leer(archivo, desde_pagina, hasta_pagina)` — texto extraído de un material.
- `uned_foros(asignatura, dias)` — debates recientes de todos los foros.
- `uned_progreso(asignatura)` / `uned_progreso_marcar(asignatura, tema, estado, nota)` — seguimiento por tema.
- `uned_plan(horas_semana, semanas)` — plan semanal (ECTS, temas pendientes, entregas).
- `uned_calendario_ics()` — regenera `~/UNED/calendario.ics`.
- `uned_guardar_apunte(asignatura, nombre, contenido)` — guarda un apunte en `apuntes/`.

## Seguridad y buen uso

- Todo se ejecuta **en tu máquina**; no envíes nunca tus credenciales UNED a
  servicios de terceros.
- El token otorga acceso de solo lectura a tu cuenta desde apps móviles;
  guárdalo con el mismo cuidado que tu contraseña.
- La sincronización espacia las descargas y solo baja lo que ha cambiado; no la
  lances en bucle (una vez al día es suficiente).
- Los materiales descargados están protegidos por derechos de autor: son para tu
  estudio personal. No subas `~/UNED` a repositorios ni lo compartas.

## Solución de problemas

| Síntoma | Solución |
|---|---|
| «Falta Playwright» al hacer login | `uv sync && uv run playwright install chromium` |
| «Token no válido» / error `invalidtoken` | Vuelve a hacer `uned_login` (p. ej. tras cambiar la contraseña) |
| «No se pudo capturar el token» | El servicio móvil podría estar capado en agora; reporta el mensaje |
| El asistente no ve las herramientas | Vuelve a ejecutar `scripts/install_vscode.py` y recarga VS Code |
| Errores de certificado en red corporativa | Define `UNED_MCP_CA_BUNDLE` antes de instalar (se copia al `mcp.json`) |
| «pendiente OCR» en el informe | Instala `ocrmypdf tesseract-ocr-spa` y vuelve a sincronizar |
| Error de certificado al hacer login tras un proxy | Define `UNED_MCP_PROXY_CA_ORG` o un `UNED_MCP_CA_BUNDLE` solo con la CA del proxy |

## Desarrollo

```bash
uv sync
uv run ruff check src tests scripts
uv run pytest
```

Estructura: `src/uned_mcp/` (servidor, cliente Moodle, sincronización, extracción,
índice, guías, fichas, planificador), `copilot/` (agente, prompts y skill),
`scripts/install_vscode.py`, `tests/` (sin red). Más detalle en
[.github/copilot-instructions.md](.github/copilot-instructions.md).

## Licencia

[MIT](LICENSE). Los materiales del campus que descargues no están cubiertos por
esta licencia: pertenecen a sus autores y son solo para tu estudio personal.
