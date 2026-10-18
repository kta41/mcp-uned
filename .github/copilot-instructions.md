# UNED MCP

Python MCP server (official `mcp` SDK, FastMCP, stdio) for the UNED virtual campus `agora.uned.es` (Moodle), plus Copilot customizations for studying. User-facing text (tool descriptions, generated Markdown, Copilot agent/prompts) is in **Spanish**; code, comments and identifiers are in English.

Module layout under `src/uned_mcp/`:
- `server.py`: MCP tool registration (thin layer; every tool returns a string and never raises — use `_fail`).
- `auth.py`: SSO login with Playwright, capture of the Moodle mobile token (`launch.php` → `<scheme>://token=<base64>`), headless refresh from the saved session, proxy CA handling for Chromium.
- `client.py`: Moodle REST calls (`call`), token storage (`~/.uned-mcp`, mode 600), TLS context, downloads with the token, helpers.
- `library.py`: incremental sync of a course into `~/UNED/<Asignatura>/` (manifest `.moodle.json`, diffs of files/deadlines/announcements, calendar and forums).
- `extract.py`: text extraction (PDF with page markers, docx/odt/pptx/rtf/html/txt), optional OCR via `ocrmypdf`.
- `index.py`: SQLite FTS5 full-text index (accent-insensitive).
- `guide.py`: discovery and parsing of the official public subject guide (guía docente) PDF.
- `ficha.py`: per-subject `ficha.md` and the global `~/UNED/README.md`.
- `classes.py`: class/session timetables (jornadas) parsed from downloaded documents and mapped to subjects.
- `planner.py`: topic progress (`progreso.json`), weekly plan, `.ics` calendar.
- `study.py`: high-level operations used by the tools and the CLI.
- `__main__.py`: CLI (`serve`, `check`, `login`, `sync`, `resumen`, `plan`).

Rules:
- Never log or return the token, cookies or session data; strip tokens from URLs (`client.strip_url_token`).
- Downloaded course material is copyrighted and personal: nothing under `~/UNED` or `~/.uned-mcp` may be committed or sent anywhere.
- Keep requests polite (`config.DOWNLOAD_DELAY`, incremental sync); no polling loops.
- Tests must not hit the network; use `tmp_path` and monkeypatch `config.STUDY_DIR`/`INDEX_DB`/`STATE_FILE`.

Run `uv run ruff check src tests scripts` and `uv run pytest` before committing.
