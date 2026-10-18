"""Download course materials into per-subject folders, extract text, index and detect changes."""

from __future__ import annotations

import json
import logging
import re
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from uned_mcp import client, config, extract, guide, index

log = logging.getLogger("uned_mcp.library")

_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
GENERAL_DIR = "_General"


def safe_name(name: str, limit: int = 90) -> str:
    name = client.strip_html(name, 400)
    name = _UNSAFE.sub(" ", name).strip(" .")
    return re.sub(r"\s+", " ", name)[:limit].strip() or "sin-nombre"


# --------------------------------------------------------------------------- #
# Paths and per-subject state
# --------------------------------------------------------------------------- #

def subject_dir(course: dict, is_subject: bool = True) -> Path:
    base = config.STUDY_DIR if is_subject else config.STUDY_DIR / GENERAL_DIR
    return base / safe_name(course.get("fullname") or str(course["id"]))


def _state_path(sdir: Path) -> Path:
    return sdir / ".moodle.json"


def load_state(sdir: Path) -> dict:
    try:
        return json.loads(_state_path(sdir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(sdir: Path, state: dict) -> None:
    sdir.mkdir(parents=True, exist_ok=True)
    _state_path(sdir).write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def global_state() -> dict:
    try:
        return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_global_state(data: dict) -> None:
    config.STUDY_DIR.mkdir(parents=True, exist_ok=True)
    config.STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def find_subject_dir(course: dict) -> Path:
    """Locate an already-synced folder for a course (subject or general)."""
    gs = global_state().get("cursos", {}).get(str(course["id"]))
    if gs and gs.get("carpeta"):
        return config.STUDY_DIR / gs["carpeta"]
    return subject_dir(course)


# --------------------------------------------------------------------------- #
# Moodle snapshot
# --------------------------------------------------------------------------- #

@dataclass
class RemoteFile:
    key: str
    url: str
    rel: str
    timemodified: int
    size: int
    mimetype: str
    module: str


@dataclass
class Snapshot:
    files: list[RemoteFile] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)


def course_snapshot(course_id: int) -> Snapshot:
    data = client.call("core_course_get_contents", courseid=course_id)
    if client.is_error(data) or not isinstance(data, list):
        raise RuntimeError(f"No se pudo leer el curso {course_id}: {data}")
    snap = Snapshot()
    for n, section in enumerate(data):
        sname = f"{n:02d} {safe_name(section.get('name') or f'Sección {n}', 60)}"
        sec = {"nombre": client.strip_html(section.get("name", ""), 200),
               "resumen": client.strip_html(section.get("summary", ""), 4000), "modulos": []}
        for mod in section.get("modules", []):
            if mod.get("uservisible") is False:
                continue
            mname = client.strip_html(mod.get("name", ""), 200)
            entry = {"tipo": mod.get("modname"), "nombre": mname, "url": mod.get("url")}
            if mod.get("modname") == "label":
                entry["texto"] = client.strip_html(mod.get("description", ""), 3000)
            elif mod.get("description"):
                entry["descripcion"] = client.strip_html(mod.get("description", ""), 1500)
            sec["modulos"].append(entry)
            for f in mod.get("contents") or []:
                if f.get("type") == "url":
                    snap.links.append({"seccion": sec["nombre"], "nombre": mname, "url": f.get("fileurl")})
                    continue
                if f.get("type") != "file" or not f.get("fileurl"):
                    continue
                subdir = Path(sname)
                if mod.get("modname") in ("folder", "book", "page") or len(mod.get("contents") or []) > 1:
                    subdir /= safe_name(mname, 60)
                fpath = (f.get("filepath") or "/").strip("/")
                if fpath:
                    subdir /= Path(*[safe_name(p, 60) for p in fpath.split("/")])
                fname = safe_name(f.get("filename") or "archivo", 120)
                if mod.get("modname") in ("page", "book") and fname == "index.html":
                    fname = safe_name(mname, 80) + ".html"
                snap.files.append(RemoteFile(
                    key=client.strip_url_token(f["fileurl"]), url=f["fileurl"], rel=str(subdir / fname),
                    timemodified=int(f.get("timemodified") or 0), size=int(f.get("filesize") or 0),
                    mimetype=f.get("mimetype") or "", module=mname))
        snap.sections.append(sec)
    return snap


def course_deadlines(course_ids: list[int]) -> dict[int, list[dict]]:
    """Assignments (with submission status) and quizzes per course."""
    out: dict[int, list[dict]] = {cid: [] for cid in course_ids}
    data = client.call("mod_assign_get_assignments", **client.arr("courseids", course_ids))
    for c in data.get("courses", []) if isinstance(data, dict) else []:
        for a in c.get("assignments", []):
            status = client.call("mod_assign_get_submission_status", assignid=a["id"])
            sub = ((status or {}).get("lastattempt") or {}).get("submission") or {} if isinstance(status, dict) else {}
            grade = ((status or {}).get("feedback") or {}).get("gradefordisplay") if isinstance(status, dict) else None
            out.setdefault(c["id"], []).append({
                "id": f"assign-{a['id']}", "tipo": "tarea", "nombre": client.strip_html(a.get("name", ""), 200),
                "ts": a.get("duedate") or 0, "corte": a.get("cutoffdate") or 0,
                "estado": sub.get("status", "desconocido"), "nota": client.strip_html(grade or "", 100),
                "enunciado": client.strip_html(a.get("intro", ""), 4000),
                "adjuntos": [{"nombre": f.get("filename"), "url": f.get("fileurl"),
                              "timemodified": f.get("timemodified") or 0, "size": f.get("filesize") or 0,
                              "mimetype": f.get("mimetype") or ""}
                             for f in a.get("introattachments", [])],
            })
    quizzes = client.call("mod_quiz_get_quizzes_by_courses", **client.arr("courseids", course_ids))
    for q in quizzes.get("quizzes", []) if isinstance(quizzes, dict) else []:
        out.setdefault(q["course"], []).append({
            "id": f"quiz-{q['id']}", "tipo": "cuestionario", "nombre": client.strip_html(q.get("name", ""), 200),
            "ts": q.get("timeclose") or 0, "apertura": q.get("timeopen") or 0, "estado": "",
            "enunciado": client.strip_html(q.get("intro", ""), 1500), "adjuntos": []})
    return out


def calendar_events(course_ids: list[int], days_back: int = 7, days_ahead: int = 365) -> list[dict]:
    now = int(time.time())
    params = {"options[timestart]": now - days_back * 86400, "options[timeend]": now + days_ahead * 86400,
              "options[userevents]": 1, "options[siteevents]": 1}
    params.update({f"events[courseids][{i}]": cid for i, cid in enumerate(course_ids)})
    data = client.call("core_calendar_get_calendar_events", **params)
    if client.is_error(data) or not isinstance(data, dict):
        return []
    return [{"id": e.get("id"), "nombre": client.strip_html(e.get("name", ""), 200), "ts": e.get("timestart") or 0,
             "duracion": e.get("timeduration") or 0, "curso": e.get("courseid"), "tipo": e.get("eventtype"),
             "modulo": e.get("modulename"), "descripcion": client.strip_html(e.get("description", ""), 500)}
            for e in data.get("events", [])]


def forum_posts(course_id: int, days: int = 30, per_forum: int = 10) -> list[dict]:
    forums = client.call("mod_forum_get_forums_by_courses", **client.arr("courseids", [course_id]))
    if client.is_error(forums) or not isinstance(forums, list):
        return []
    cutoff = time.time() - days * 86400
    out = []
    for f in forums:
        res = client.call("mod_forum_get_forum_discussions", forumid=f["id"], sortorder=-1, perpage=per_forum)
        for d in res.get("discussions", []) if isinstance(res, dict) else []:
            ts = d.get("timemodified") or d.get("created") or 0
            if ts >= cutoff:
                out.append({"foro": client.strip_html(f.get("name", ""), 120), "tipo": f.get("type"),
                            "id": d.get("discussion"), "asunto": d.get("subject") or d.get("name"),
                            "autor": d.get("userfullname"), "ts": ts, "respuestas": d.get("numreplies", 0),
                            "texto": client.strip_html(d.get("message", ""), 1200)})
    return sorted(out, key=lambda x: -x["ts"])


# --------------------------------------------------------------------------- #
# Sync
# --------------------------------------------------------------------------- #

@dataclass
class SyncReport:
    curso: str
    carpeta: str
    nuevos: list[str] = field(default_factory=list)
    actualizados: list[str] = field(default_factory=list)
    eliminados: list[str] = field(default_factory=list)
    omitidos: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    ocr_pendiente: list[str] = field(default_factory=list)
    ocr_hecho: list[str] = field(default_factory=list)
    plazos_nuevos: list[str] = field(default_factory=list)
    plazos_cambiados: list[str] = field(default_factory=list)
    anuncios_nuevos: list[str] = field(default_factory=list)
    guia: str = ""

    def has_changes(self) -> bool:
        return any((self.nuevos, self.actualizados, self.eliminados, self.plazos_nuevos,
                    self.plazos_cambiados, self.anuncios_nuevos, self.ocr_hecho))


def _process_text(sdir: Path, asignatura: str, local: Path, rel: str, entry: dict, report: SyncReport) -> None:
    """Extract text for a downloaded file and update the search index."""
    if local.suffix.lower() == ".zip":
        try:
            target = local.with_suffix("")
            with zipfile.ZipFile(local) as z:
                for member in z.namelist():
                    if member.endswith("/") or ".." in Path(member).parts:
                        continue
                    out = target / Path(*[safe_name(p, 80) for p in Path(member).parts])
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(z.read(member))
                    _process_text(sdir, asignatura, out, str(out.relative_to(sdir / "materiales")), {}, report)
        except zipfile.BadZipFile:
            report.errores.append(f"{rel}: zip dañado")
        return
    ext = extract.extract(local)
    if ext is None:
        return
    if ext.needs_ocr and local.suffix.lower() == ".pdf":
        ocr = extract.run_ocr(local)
        if ocr:
            ext = extract.extract(ocr) or ext
            ext.needs_ocr = False
        else:
            report.ocr_pendiente.append(rel)
    text_rel = Path("texto") / (rel + ".md")
    (sdir / text_rel).parent.mkdir(parents=True, exist_ok=True)
    (sdir / text_rel).write_text(extract.to_markdown(local.name, f"materiales/{rel}", ext), encoding="utf-8")
    archivo = f"{sdir.relative_to(config.STUDY_DIR)}/{text_rel}"
    index.replace_file(asignatura, archivo, ext.chunks)
    entry.update({"texto": str(text_rel), "paginas": ext.pages, "caracteres": ext.chars, "ocr": ext.needs_ocr})


def _download_all(sdir: Path, asignatura: str, files: list[RemoteFile], state: dict,
                  report: SyncReport, force: bool) -> dict:
    old = state.get("archivos", {})
    new: dict[str, dict] = {}
    mats = sdir / "materiales"
    for rf in files:
        prev = old.get(rf.key)
        local = mats / rf.rel
        entry = {"ruta": rf.rel, "timemodified": rf.timemodified, "size": rf.size, "mimetype": rf.mimetype,
                 "modulo": rf.module}
        if rf.mimetype.startswith(config.SKIP_MIMETYPES_PREFIX) or rf.size > config.MAX_FILE_MB * 1024 * 1024:
            entry["omitido"] = True
            report.omitidos.append(f"{rf.rel} ({rf.mimetype or '?'}, {rf.size // 1048576} MB)")
            new[rf.key] = entry
            continue
        unchanged = (prev and not force and prev.get("timemodified") == rf.timemodified
                     and prev.get("ruta") == rf.rel and local.exists() and not prev.get("omitido"))
        if unchanged:
            new[rf.key] = prev
            if prev.get("ocr") and extract.ocr_available():
                entry = dict(prev)
                _process_text(sdir, asignatura, local, rf.rel, entry, report)
                if not entry.get("ocr"):
                    report.ocr_hecho.append(rf.rel)
                new[rf.key] = entry
            continue
        try:
            client.download(rf.url, local)
            time.sleep(config.DOWNLOAD_DELAY)
        except Exception as exc:
            report.errores.append(f"{rf.rel}: {exc}")
            if prev:
                new[rf.key] = prev
            continue
        if prev and prev.get("ruta") != rf.rel:
            (mats / prev["ruta"]).unlink(missing_ok=True)
        (report.actualizados if prev else report.nuevos).append(rf.rel)
        _process_text(sdir, asignatura, local, rf.rel, entry, report)
        new[rf.key] = entry
    for key, prev in old.items():
        if key not in new:
            report.eliminados.append(prev.get("ruta", key))
            if prev.get("texto"):
                index.remove_file(f"{sdir.relative_to(config.STUDY_DIR)}/{prev['texto']}")
    return new


def _diff_deadlines(old: dict, items: list[dict], report: SyncReport) -> None:
    for it in items:
        prev = old.get(it["id"])
        when = client.fmt_ts(it["ts"]) if it["ts"] else "sin fecha"
        if prev is None:
            if old:
                report.plazos_nuevos.append(f"{it['nombre']} — {when}")
        elif prev != it["ts"]:
            report.plazos_cambiados.append(f"{it['nombre']}: {client.fmt_ts(prev)} → {when}")


def sync_course(course: dict, *, is_subject: bool, codes: dict, degree_page: str | None,
                deadlines: list[dict], events: list[dict], force: bool = False) -> SyncReport:
    sdir = subject_dir(course, is_subject)
    sdir.mkdir(parents=True, exist_ok=True)
    asignatura = course.get("fullname") or str(course["id"])
    report = SyncReport(asignatura, str(sdir.relative_to(config.STUDY_DIR)))
    state = load_state(sdir)

    snap = course_snapshot(course["id"])
    files = list(snap.files)
    for d in deadlines:
        for adj in d.get("adjuntos", []):
            if adj.get("url"):
                files.append(RemoteFile(client.strip_url_token(adj["url"]), adj["url"],
                                        str(Path("Tareas") / safe_name(d["nombre"], 60) / safe_name(adj["nombre"], 120)),
                                        int(adj["timemodified"]), int(adj["size"]), adj["mimetype"], d["nombre"]))
    archivos = _download_all(sdir, asignatura, files, state, report, force)

    _diff_deadlines(state.get("plazos", {}), deadlines, report)

    news = [p for p in forum_posts(course["id"], days=60) if p["tipo"] == "news"]
    seen_news = set(state.get("anuncios", []))
    if state:
        report.anuncios_nuevos = [f"[{client.fmt_ts(n['ts'])}] {n['asunto']}" for n in news if n["id"] not in seen_news]

    if is_subject and degree_page:
        try:
            g = guide.fetch_guide(course, codes, degree_page, sdir)
            report.guia = f"código {g.codigo}" if g else "no encontrada en la web de la titulación"
        except Exception as exc:
            report.guia = f"error: {exc}"

    state.update({
        "curso": {"id": course["id"], "nombre": asignatura, "inicio": course.get("startdate"),
                  "fin": course.get("enddate"), "contactos": course.get("contacts", [])},
        "archivos": archivos,
        "plazos": {d["id"]: d["ts"] for d in deadlines},
        "plazos_detalle": deadlines,
        "eventos": events,
        "anuncios": sorted(seen_news | {n["id"] for n in news}),
        "anuncios_detalle": news[:15],
        "secciones": snap.sections,
        "enlaces": snap.links,
        "sincronizado": int(time.time()),
    })
    save_state(sdir, state)
    _write_links(sdir, asignatura, snap.links)
    return report


def _write_links(sdir: Path, name: str, links: list[dict]) -> None:
    if not links:
        return
    lines = [f"# Enlaces — {name}", ""]
    current = None
    for link in links:
        if link["seccion"] != current:
            current = link["seccion"]
            lines += ["", f"## {current}"]
        lines.append(f"- [{link['nombre']}]({link['url']})")
    (sdir / "enlaces.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def sync_all(only: dict | None = None, force: bool = False, progress=None) -> list[SyncReport]:
    """Sync every enrolled course (or only one). Subjects are those found in the degree page."""
    _, courses = client.get_courses()
    details = client.call("core_course_get_courses_by_field", field="ids",
                          value=",".join(str(c["id"]) for c in courses))
    extra = {c["id"]: c for c in (details.get("courses", []) if isinstance(details, dict) else [])}
    courses = [{**c, **{k: v for k, v in extra.get(c["id"], {}).items() if k in ("contacts", "categoryname")}}
               for c in courses]

    degree_page = guide.degree_url(courses)
    codes = {}
    if degree_page:
        try:
            codes = guide.subject_codes(client.fetch_public(degree_page))
        except Exception as exc:
            log.warning("degree page %s failed: %s", degree_page, exc)

    ids = [c["id"] for c in courses]
    all_deadlines = course_deadlines(ids)
    events = calendar_events(ids)
    gstate = global_state()
    gstate.setdefault("cursos", {})
    reports = []
    targets = [only] if only else courses
    for c in targets:
        is_subject = bool(codes) and guide.match_code(c.get("fullname", ""), codes) is not None
        if not codes:
            is_subject = not client.normalize(c.get("fullname", "")).startswith(("acogida", "master", "grado"))
        if progress:
            progress(f"Sincronizando {c.get('fullname')}…")
        rep = sync_course(c, is_subject=is_subject, codes=codes, degree_page=degree_page,
                          deadlines=all_deadlines.get(c["id"], []),
                          events=[e for e in events if e["curso"] == c["id"]], force=force)
        gstate["cursos"][str(c["id"])] = {"nombre": c.get("fullname"), "carpeta": rep.carpeta,
                                          "asignatura": is_subject}
        reports.append(rep)
    gstate["ultima_sincronizacion"] = int(time.time())
    gstate["titulacion"] = degree_page
    save_global_state(gstate)
    return reports


def report_markdown(reports: list[SyncReport]) -> str:
    lines = [f"# Novedades de la sincronización — {client.fmt_ts(time.time())}", ""]
    for r in reports:
        lines.append(f"## {r.curso}")
        lines.append(f"Carpeta: `{r.carpeta}`" + (f" · Guía: {r.guia}" if r.guia else ""))
        for label, items in (("Nuevos materiales", r.nuevos), ("Materiales actualizados", r.actualizados),
                             ("Materiales retirados del campus", r.eliminados),
                             ("Plazos nuevos", r.plazos_nuevos), ("Plazos que han cambiado", r.plazos_cambiados),
                             ("Anuncios nuevos", r.anuncios_nuevos), ("PDF escaneados ya pasados por OCR", r.ocr_hecho),
                             ("PDF escaneados sin texto (OCR)", r.ocr_pendiente),
                             ("Omitidos (vídeo/audio o demasiado grandes)", r.omitidos), ("Errores", r.errores)):
            if items:
                lines.append(f"- **{label}** ({len(items)}):")
                lines += [f"  - {i}" for i in items[:40]]
                if len(items) > 40:
                    lines.append(f"  - … y {len(items) - 40} más")
        if not r.has_changes() and not r.errores:
            lines.append("- Sin cambios.")
        lines.append("")
    return "\n".join(lines)
