"""Topic progress tracking, weekly study plan and iCalendar export."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from uned_mcp import classes, client, config, guide, library

ESTADOS = ["pendiente", "leyendo", "visto", "repasado", "dominado"]
ESTADO_ICONO = {"pendiente": "⬜", "leyendo": "📖", "visto": "🟨", "repasado": "🟩", "dominado": "⭐"}
_RESTANTE = {"pendiente": 1.0, "leyendo": 0.7, "visto": 0.4, "repasado": 0.15, "dominado": 0.0}
_TOPIC_RE = re.compile(
    r"^\s*((?:tema|bloque|unidad|m[óo]dulo|lecci[óo]n|cap[íi]tulo|parte)\s*[\dIVXLC]+\b.*"
    r"|(?:primer|segundo|tercer|cuarto|quinto|sexto|s[ée]ptimo|octavo)\s+(?:bloque|m[óo]dulo|tema|parte)\b.*"
    r"|\d{1,2}\s*(?:[.),]|\.-)\s*\S.*"
    r"|[a-z]\s*(?:\)|\.-|\.)\s*\S.*)$",
    re.I)
_TOPIC_START_RE = re.compile(r"^\s*(?:\d{1,2}\s*(?:[.),]|\.-)|[a-z]\s*(?:\)|\.-|\.))\s*")


def _topic_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip(" .:,;")
    label = ""
    m = _TOPIC_START_RE.match(text)
    if m:
        label = re.sub(r"[\s.),-]+$", "", m.group(0).strip()) + ". "
        text = text[m.end():]
    first = re.split(r"(?<=[a-záéíóúñ)])\.\s+(?=[A-ZÁÉÍÓÚÑ])", text, maxsplit=2)
    title = first[0].strip(" .:,;")
    if len(first) > 1 and len(title) <= 20:
        title += ". " + first[1].strip(" .:,;")
    first = title
    if len(first) > 140:
        first = first[:140].rsplit(" ", 1)[0] + "…"
    return label + first


# --------------------------------------------------------------------------- #
# Progress
# --------------------------------------------------------------------------- #

def topics_from_guide(g: guide.Guide | None) -> list[str]:
    if not g:
        return []
    text = g.secciones.get("CONTENIDOS", "")
    blocks: list[str] = []
    open_block = False
    for line in text.splitlines():
        if re.match(r"^\s*\d{1,2}\.\d", line):
            open_block = False
        elif _TOPIC_RE.match(line):
            blocks.append(line.strip())
            open_block = True
        elif not line.strip() or line.strip().endswith(":"):
            open_block = False
        elif open_block and len(blocks[-1]) < 400:
            blocks[-1] += " " + line.strip()
    topics = [_topic_title(b) for b in blocks]
    return list(dict.fromkeys(t for t in topics if len(t) > 3))


def _progress_path(sdir: Path) -> Path:
    return sdir / "progreso.json"


def load_progress(course: dict, sdir: Path | None = None) -> dict:
    sdir = sdir or library.find_subject_dir(course)
    try:
        prog = json.loads(_progress_path(sdir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prog = {"asignatura": course.get("fullname"), "temas": []}
    known = {client.normalize(t["tema"]) for t in prog["temas"]}
    for topic in topics_from_guide(guide.load_guide(sdir)):
        if client.normalize(topic) not in known:
            prog["temas"].append({"tema": topic, "estado": "pendiente", "actualizado": None, "nota": ""})
    return prog


def save_progress(sdir: Path, prog: dict) -> None:
    sdir.mkdir(parents=True, exist_ok=True)
    _progress_path(sdir).write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_topic(course: dict, tema: str, estado: str, nota: str = "") -> str:
    estado = estado.lower().strip()
    if estado not in ESTADOS:
        raise ValueError(f"Estado no válido. Usa uno de: {', '.join(ESTADOS)}")
    sdir = library.find_subject_dir(course)
    prog = load_progress(course, sdir)
    nq = client.normalize(tema)
    match = [t for t in prog["temas"] if client.normalize(t["tema"]) == nq]
    if not match and tema.strip().isdigit():
        n = tema.strip()
        match = [t for t in prog["temas"] if re.match(rf"^(?:[a-z]+ )?{n}\b", client.normalize(t["tema"]))]
    elif not match:
        match = [t for t in prog["temas"] if nq in client.normalize(t["tema"])]
    if len(match) > 1:
        raise ValueError("Varios temas coinciden: " + "; ".join(t["tema"] for t in match))
    if match:
        entry = match[0]
    else:
        entry = {"tema": tema.strip(), "estado": "pendiente", "actualizado": None, "nota": ""}
        prog["temas"].append(entry)
    entry["estado"] = estado
    entry["actualizado"] = datetime.now(config.TZ).strftime("%d/%m/%Y")
    if nota:
        entry["nota"] = nota
    save_progress(sdir, prog)
    return f"{entry['tema']} → {estado}"


def progress_pct(prog: dict) -> int:
    if not prog["temas"]:
        return 0
    remaining = sum(_RESTANTE.get(t["estado"], 1.0) for t in prog["temas"])
    return round(100 * (1 - remaining / len(prog["temas"])))


# --------------------------------------------------------------------------- #
# Weekly plan
# --------------------------------------------------------------------------- #

def _subjects() -> list[tuple[dict, Path]]:
    out = []
    for cid, info in library.global_state().get("cursos", {}).items():
        if info.get("asignatura"):
            out.append(({"id": int(cid), "fullname": info["nombre"]}, config.STUDY_DIR / info["carpeta"]))
    return out


def build_plan(horas_semana: float = 10, semanas: int = 4) -> str:
    subjects = _subjects()
    if not subjects:
        return "Aún no hay asignaturas sincronizadas. Ejecuta primero uned_sincronizar."
    today = datetime.now(config.TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today  # weeks start today so week 1 is never already past
    data = []
    for course, sdir in subjects:
        st = library.load_state(sdir)
        g = guide.load_guide(sdir)
        prog = load_progress(course, sdir)
        pending = [d for d in st.get("plazos_detalle", [])
                   if d["ts"] and d["ts"] > today.timestamp() and d.get("estado") != "submitted"]
        remaining = sum(_RESTANTE.get(t["estado"], 1.0) for t in prog["temas"]) / max(len(prog["temas"]), 1)
        ects = float(g.ects) if g and g.ects.replace(".", "", 1).isdigit() else 5.0
        data.append({"course": course, "pending": sorted(pending, key=lambda d: d["ts"]), "remaining": remaining,
                     "ects": ects, "topics": [t for t in prog["temas"] if t["estado"] in ("pendiente", "leyendo", "visto")],
                     "guide_dates": list(dict.fromkeys(g.fechas_entrega)) if g else []})

    L = [f"# 🗓️ Plan de estudio — {semanas} semanas · {horas_semana:g} h/semana",
         f"> Generado el {today.strftime('%d/%m/%Y')}. Reparto según créditos, temario pendiente y cercanía de entregas. "
         "Ajusta con el agente si cambian tus horas.", ""]
    topic_cursor = {id(d): 0 for d in data}
    all_cls = classes.all_classes()
    for w in range(semanas):
        start = monday + timedelta(weeks=w)
        end = start + timedelta(days=7)
        scores = {}
        for d in data:
            urgency = 0.0
            for p in d["pending"]:
                weeks_left = (p["ts"] - start.timestamp()) / (7 * 86400)
                if 0 <= weeks_left <= 4:
                    urgency += 1.0 / (1.0 + weeks_left)
            scores[id(d)] = d["ects"] / 5 * (0.3 + d["remaining"]) + 2.0 * urgency
        total = sum(scores.values()) or 1
        L.append(f"## Semana {w + 1}: {start.strftime('%d/%m')} – {(end - timedelta(days=1)).strftime('%d/%m')}")
        week_classes = [c for c in all_cls if start.timestamp() <= c.inicio < end.timestamp()]
        if week_classes:
            L += ["", "🏫 **Clases esta semana:** " + "; ".join(
                f"{c.horario()} {c.asignatura or c.titulo}" for c in week_classes)]
        L += ["",
              "| Asignatura | Horas | Qué hacer |", "|---|---|---|"]
        for d in sorted(data, key=lambda d: -scores[id(d)]):
            hours = round(horas_semana * scores[id(d)] / total * 2) / 2
            if hours <= 0:
                continue
            todo = []
            for p in d["pending"]:
                if start.timestamp() <= p["ts"] < end.timestamp():
                    todo.append(f"**Entregar** {p['nombre']} ({client.fmt_ts(p['ts'])})")
                elif end.timestamp() <= p["ts"] < (end + timedelta(days=14)).timestamp():
                    todo.append(f"Preparar {p['nombre']} (vence {client.fmt_ts(p['ts'])[:10]})")
            n_topics = max(1, int(hours // 3)) if d["topics"] else 0
            cur = topic_cursor[id(d)]
            for t in d["topics"][cur:cur + n_topics]:
                verb = {"pendiente": "Estudiar", "leyendo": "Terminar", "visto": "Repasar"}[t["estado"]]
                todo.append(f"{verb} {t['tema']}")
            topic_cursor[id(d)] = cur + n_topics
            if not todo:
                todo.append("Repaso general / lecturas de la guía")
            L.append(f"| {d['course']['fullname']} | {hours:g} h | {'<br>'.join(todo)} |")
        L.append("")
    notes = [f"- *{d['course']['fullname']}*: {'; '.join(d['guide_dates'])}" for d in data if d["guide_dates"]]
    if notes:
        L += ["## Fechas aproximadas de las guías (no están en el calendario)", "", *notes, ""]
    return "\n".join(L)


def write_plan(horas_semana: float = 10, semanas: int = 4) -> tuple[Path, str]:
    text = build_plan(horas_semana, semanas)
    path = config.STUDY_DIR / "plan-semanal.md"
    path.write_text(text, encoding="utf-8")
    return path, text


# --------------------------------------------------------------------------- #
# iCalendar
# --------------------------------------------------------------------------- #

def _ics_escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_dt(ts: float) -> str:
    return datetime.utcfromtimestamp(ts).strftime("%Y%m%dT%H%M%SZ")  # noqa: DTZ004


def build_ics() -> str:
    events = []
    for course, sdir in _subjects() + [
            ({"id": int(cid), "fullname": i["nombre"]}, config.STUDY_DIR / i["carpeta"])
            for cid, i in library.global_state().get("cursos", {}).items() if not i.get("asignatura")]:
        st = library.load_state(sdir)
        names = set()
        for e in st.get("eventos", []):
            if e.get("ts"):
                events.append((f"cal-{e['id']}", e["ts"], e.get("duracion") or 0, e["nombre"], course["fullname"],
                               e.get("descripcion", "")))
                names.add(client.normalize(e["nombre"]))
        for d in st.get("plazos_detalle", []):
            if d["ts"] and not any(client.normalize(d["nombre"]) in n for n in names):
                events.append((d["id"], d["ts"], 0, f"Vencimiento de {d['nombre']}", course["fullname"], ""))
    for c in classes.all_classes():
        desc = " · ".join(x for x in (c.profesor, c.modalidad) if x)
        events.append((c.uid, c.inicio, c.fin - c.inicio, f"Clase: {c.titulo}", c.asignatura or "Titulación", desc))
    stamp = _ics_dt(time.time())
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//mcp-uned//ES", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:UNED", "X-WR-TIMEZONE:Europe/Madrid"]
    for uid, ts, dur, name, course, desc in sorted(events, key=lambda e: e[1]):
        lines += ["BEGIN:VEVENT", f"UID:{uid}@mcp-uned", f"DTSTAMP:{stamp}", f"DTSTART:{_ics_dt(ts)}",
                  f"DTEND:{_ics_dt(ts + max(dur, 1800))}", f"SUMMARY:{_ics_escape(name)} ({_ics_escape(course)})",
                  f"DESCRIPTION:{_ics_escape(desc[:500])}", "BEGIN:VALARM", "ACTION:DISPLAY",
                  f"DESCRIPTION:{_ics_escape(name)}", "TRIGGER:-P2D", "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def write_ics() -> Path:
    path = config.STUDY_DIR / "calendario.ics"
    path.write_text(build_ics(), encoding="utf-8")
    return path
