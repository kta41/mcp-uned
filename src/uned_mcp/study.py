"""High-level study workflows used by both the MCP tools and the CLI."""

from __future__ import annotations

import re
from pathlib import Path

from uned_mcp import client, config, ficha, library, planner


def courses_with_details() -> list[dict]:
    _, courses = client.get_courses()
    return courses


def resolve(asignatura: str | int) -> dict:
    return client.resolve_course(courses_with_details(), asignatura)


def sync(asignatura: str | int | None = None, force: bool = False, progress=None) -> str:
    only = resolve(asignatura) if asignatura not in (None, "") else None
    reports = library.sync_all(only=only, force=force, progress=progress)
    gs = library.global_state()
    for rep in reports:
        cid = next((k for k, v in gs.get("cursos", {}).items() if v["carpeta"] == rep.carpeta), None)
        if cid and gs["cursos"][cid].get("asignatura"):
            ficha.write_ficha({"id": int(cid), "fullname": gs["cursos"][cid]["nombre"]})
    ficha.write_index()
    planner.write_ics()
    md = library.report_markdown(reports)
    (config.STUDY_DIR / "novedades.md").write_text(md, encoding="utf-8")
    totals = {
        "materiales nuevos": sum(len(r.nuevos) for r in reports),
        "actualizados": sum(len(r.actualizados) for r in reports),
        "plazos nuevos/cambiados": sum(len(r.plazos_nuevos) + len(r.plazos_cambiados) for r in reports),
        "anuncios nuevos": sum(len(r.anuncios_nuevos) for r in reports),
        "errores": sum(len(r.errores) for r in reports),
    }
    head = (f"Sincronizado en {config.STUDY_DIR} · "
            + " · ".join(f"{k}: {v}" for k, v in totals.items()) + "\n\n")
    return head + md


def materials(asignatura: str | int) -> str:
    course = resolve(asignatura)
    sdir = library.find_subject_dir(course)
    st = library.load_state(sdir)
    if not st:
        return f"'{course['fullname']}' aún no está sincronizada. Usa uned_sincronizar."
    rel_dir = sdir.relative_to(config.STUDY_DIR)
    lines = [f"Materiales de {course['fullname']} (carpeta {sdir}):"]
    for f in sorted(st.get("archivos", {}).values(), key=lambda f: f["ruta"]):
        if f.get("omitido"):
            lines.append(f"• {f['ruta']} — no descargado ({f.get('mimetype')})")
            continue
        info = []
        if f.get("paginas"):
            info.append(f"{f['paginas']} págs")
        if f.get("ocr"):
            info.append("escaneado, sin texto")
        if f.get("texto"):
            info.append(f"texto: {rel_dir}/{f['texto']}")
        lines.append(f"• {f['ruta']}" + (f" ({'; '.join(info)})" if info else ""))
    return "\n".join(lines)


def read_text(archivo: str, desde: int = 1, hasta: int | None = None, max_chars: int = 30000) -> str:
    """Read an extracted text file (path relative to the study dir), optionally a page range."""
    path = (config.STUDY_DIR / archivo).resolve()
    if not path.is_relative_to(config.STUDY_DIR.resolve()):
        return "Ruta fuera de la carpeta de estudio."
    if not path.exists() and not archivo.endswith(".md"):
        path = path.with_name(path.name + ".md")
    if not path.exists():
        candidates = list(config.STUDY_DIR.rglob(f"texto/**/{Path(archivo).name}*.md"))
        if len(candidates) == 1:
            path = candidates[0]
        else:
            return f"No encuentro '{archivo}'. Usa uned_materiales o uned_buscar para ver las rutas."
    text = path.read_text(encoding="utf-8")
    if desde > 1 or hasta:
        parts = re.split(r"(?m)^(?=## \[)", text)
        head, body = parts[0], parts[1:]
        sel = []
        for i, part in enumerate(body, start=1):
            m = re.match(r"## \[(?:p\. |diapositiva |sección )(\d+)\]", part)
            n = int(m.group(1)) if m else i
            if n >= desde and (hasta is None or n <= hasta):
                sel.append(part)
        text = head + "".join(sel)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[… recortado a {max_chars} caracteres; pide más páginas con desde/hasta]"
    return text


def save_note(asignatura: str | int, nombre: str, contenido: str) -> Path:
    course = resolve(asignatura)
    sdir = library.find_subject_dir(course)
    name = library.safe_name(nombre, 80)
    if not name.endswith(".md"):
        name += ".md"
    path = sdir / "apuntes" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contenido, encoding="utf-8")
    if (sdir / "ficha.md").exists():
        ficha.write_ficha(course)
    return path
