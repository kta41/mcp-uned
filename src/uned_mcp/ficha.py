"""Subject sheet (ficha.md) and the global study index (README.md)."""

from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import quote

from uned_mcp import classes, client, config, guide, library, planner

_DATE_WORDS = re.compile(r"\b(\d{1,2} de [a-záé]+|\d{1,2}/\d{1,2}(/\d{2,4})?|lunes|martes|miércoles|jueves|viernes|"
                         r"sábado|enero|febrero|marzo|abril|mayo|junio|julio|septiembre|octubre|noviembre|diciembre)\b",
                         re.I)
_ESTADOS_ENTREGA = {"submitted": "✅ entregada", "draft": "📝 borrador", "new": "⏳ pendiente", "reopened": "🔁 reabierta"}


def _link(path: str) -> str:
    return quote(path)


def _short(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def _evaluation_summary(ev: str) -> list[str]:
    out = []
    for label in ("Tipo de examen", "Requiere Presencialidad", "Duración del examen", "Material permitido en el examen",
                  "¿Hay PEC?", "¿Hay otra/s actividad/es evaluable/s?"):
        m = re.search(re.escape(label) + r"\n([^\n]+)", ev)
        if m:
            out.append(f"- **{label}**: {m.group(1).strip()}")
    for m in re.finditer(r"Ponderaci[óo]n[^\n]*(?:\n[^\n]*nota final)?\n(.+?)(?=\nFecha aproximada|\nComentarios|\n[A-ZÁÉÍÓÚ ]{12,}\n|\Z)",
                         ev, re.S):
        val = " ".join(m.group(1).split())
        if val and not val.lower().startswith(("fecha", "comentarios", "ponderaci", "uned ")):
            out.append(f"- **Ponderación**: {val[:400]}")
    if not any("Ponderación" in o for o in out):
        desc = re.search(r"Descripci[óo]n\n(.+?)\nCriterios de evaluaci[óo]n", ev, re.S)
        if desc and desc.group(1).strip():
            out.append("- **Descripción de la evaluación**: " + " ".join(desc.group(1).split())[:500])
    final = re.search(r"¿C[ÓO]MO SE OBTIENE LA NOTA FINAL\?\n(.+?)(?=\n[A-ZÁÉÍÓÚ¿ ]{12,}\n|\Z)", ev, re.S)
    if final and final.group(1).strip():
        out.append("- **Nota final**: " + " ".join(final.group(1).split())[:500])
    return list(dict.fromkeys(out))


def build_ficha(course: dict) -> str:
    sdir = library.find_subject_dir(course)
    st = library.load_state(sdir)
    g = guide.load_guide(sdir)
    name = course.get("fullname") or st.get("curso", {}).get("nombre", "")
    now = time.time()
    L: list[str] = [f"# {name}", ""]

    meta = [f"[Aula virtual]({config.BASE_URL}/course/view.php?id={course['id']})"]
    if g:
        meta = [f"Código **{g.codigo}**", f"{g.ects} ECTS" if g.ects else "", f"{g.horas} h" if g.horas else "",
                g.periodo.capitalize(), "[Guía docente](guia-docente.md)", f"[PDF oficial]({g.url_pdf})", *meta]
    L += ["> " + " · ".join(m for m in meta if m),
          f"> Última sincronización: {client.fmt_ts(st.get('sincronizado'))}", ""]

    # Equipo docente
    L += ["## 👩‍🏫 Equipo docente y contacto", ""]
    if g and g.equipo:
        L += ["| Profesor/a | Correo | Teléfono | Departamento |", "|---|---|---|---|"]
        L += [f"| {t.nombre.title()} | {t.email} | {t.telefono} | {t.departamento.title()} |" for t in g.equipo]
    else:
        contacts = sorted({c.get("fullname", "") for c in st.get("curso", {}).get("contactos", [])})
        L += [f"- {c}" for c in contacts] or ["- (sin datos)"]
    if g and g.secciones.get("HORARIO DE ATENCIÓN AL ESTUDIANTE"):
        L += ["", "**Atención al estudiante:** " + _short(g.secciones["HORARIO DE ATENCIÓN AL ESTUDIANTE"], 700)]
    L.append("")

    # Fechas
    deadlines = sorted(st.get("plazos_detalle", []), key=lambda d: d["ts"] or 9e12)
    L += ["## 📅 Fechas y entregas", ""]
    sesiones = classes.for_subject(name)
    if sesiones:
        L += ["**🏫 Clases / jornadas:**", "", "| Día y hora | Sesión | Profesor/a | Modalidad |", "|---|---|---|---|"]
        for c in sesiones:
            when = c.horario() + (" (pasada)" if c.fin < now else "")
            L.append(f"| {when} | [{c.titulo}]({_link(classes.source_link(c, sdir))}) | {c.profesor} | {c.modalidad} |")
        L.append("")
    if deadlines:
        L += ["| Fecha | Tipo | Actividad | Estado |", "|---|---|---|---|"]
        for d in deadlines:
            when = client.fmt_ts(d["ts"]) if d["ts"] else "sin fecha"
            if d["ts"] and d["ts"] < now and d.get("estado") != "submitted":
                when += " (pasada)"
            estado = _ESTADOS_ENTREGA.get(d.get("estado", ""), d.get("estado", ""))
            if d.get("nota"):
                estado += f" · nota {d['nota']}"
            L.append(f"| {when} | {d['tipo']} | {d['nombre']} | {estado} |")
    other = [e for e in st.get("eventos", []) if e.get("modulo") not in ("assign", "quiz")]
    if other:
        L += ["", "**Otros eventos del calendario:**"]
        L += [f"- {client.fmt_ts(e['ts'])} — {e['nombre']}" for e in sorted(other, key=lambda e: e["ts"])]
    if g and g.fechas_entrega:
        L += ["", "**Fechas aproximadas según la guía:** " + "; ".join(dict.fromkeys(g.fechas_entrega))]
    sessions = [s for s in st.get("secciones", []) if s.get("resumen") and _DATE_WORDS.search(s["resumen"])]
    sessions += [{"nombre": m["nombre"], "resumen": m["texto"]} for s in st.get("secciones", [])
                 for m in s.get("modulos", []) if m.get("texto") and _DATE_WORDS.search(m["texto"])]
    if sessions:
        L += ["", "**Sesiones, jornadas y avisos con fechas (aula virtual):**"]
        L += [f"- *{s['nombre']}*: {_short(s['resumen'], 500)}" for s in sessions[:8]]
    if not (deadlines or other or sessions or sesiones):
        L.append("- Sin fechas publicadas todavía.")
    L.append("")

    # Evaluación
    if g and g.secciones.get("SISTEMA DE EVALUACIÓN"):
        ev = g.secciones["SISTEMA DE EVALUACIÓN"]
        L += ["## 🎯 Evaluación", ""]
        L += _evaluation_summary(ev) or ["- Ver detalle."]
        nota = re.search(r"¿C[ÓO]MO SE OBTIENE LA NOTA FINAL\?\n(.+)", ev, re.S)
        if nota:
            L += ["", "**Cómo se obtiene la nota final:** " + _short(nota.group(1), 900)]
        L += ["", "<details><summary>Sistema de evaluación completo (guía)</summary>", "", ev, "", "</details>", ""]

    # Enunciados
    with_text = [d for d in deadlines if d.get("enunciado")]
    if with_text:
        L += ["## 📝 Enunciados de las actividades", ""]
        for d in with_text:
            L += [f"### {d['nombre']}", f"*Entrega: {client.fmt_ts(d['ts'])}*" if d["ts"] else "", "",
                  _short(d["enunciado"], 1500), ""]
            for adj in d.get("adjuntos", []):
                rel = Path("materiales/Tareas") / library.safe_name(d["nombre"], 60) / library.safe_name(adj["nombre"], 120)
                L.append(f"- 📎 [{adj['nombre']}]({_link(str(rel))})")
            L.append("")

    # Temario + progreso
    prog = planner.load_progress(course, sdir)
    L += ["## 📚 Temario y progreso", ""]
    if prog["temas"]:
        L += [f"- {planner.ESTADO_ICONO.get(t['estado'], '')} {t['tema']} — *{t['estado']}*" for t in prog["temas"]]
        L += ["", f"Avance estimado: **{planner.progress_pct(prog)}%**"]
    elif g and g.secciones.get("CONTENIDOS"):
        L.append(g.secciones["CONTENIDOS"])
    else:
        L.append("- Temario no disponible en la guía.")
    L.append("")

    if g and g.secciones.get("METODOLOGÍA"):
        L += ["## 🧭 Metodología", "", _short(g.secciones["METODOLOGÍA"], 1500), ""]

    # Materiales
    files = [f for f in st.get("archivos", {}).values() if not f.get("omitido")]
    L += [f"## 📂 Materiales descargados ({len(files)})", ""]
    current = None
    for f in sorted(files, key=lambda f: f["ruta"]):
        section = f["ruta"].split("/", 1)[0]
        if section != current:
            current = section
            title = re.sub(r"^\d+ ", "", section)
            L += ["", f"**{title}**"]
        extra = []
        if f.get("paginas"):
            extra.append(f"{f['paginas']} p.")
        if f.get("texto"):
            extra.append(f"[texto]({_link(f['texto'])})")
        if f.get("ocr"):
            extra.append("⚠️ escaneado")
        L.append(f"- [{Path(f['ruta']).name}]({_link('materiales/' + f['ruta'])})" + (f" ({', '.join(extra)})" if extra else ""))
    skipped = [f for f in st.get("archivos", {}).values() if f.get("omitido")]
    if skipped:
        L += ["", f"*{len(skipped)} archivo(s) de vídeo/audio o muy grandes no descargados (están en el aula virtual).*"]
    L.append("")

    if g and g.secciones.get("BIBLIOGRAFÍA BÁSICA"):
        bib = re.findall(r"Título: (.+?)\n(?:.*\n)*?Autor/es: (.+?)\n", g.secciones["BIBLIOGRAFÍA BÁSICA"])
        L += ["## 📖 Bibliografía básica", ""]
        L += [f"- {t.strip().capitalize()} — {a.strip()}" for t, a in bib] or [_short(g.secciones["BIBLIOGRAFÍA BÁSICA"], 1200)]
        L.append("")

    news = st.get("anuncios_detalle", [])
    if news:
        L += ["## 📣 Últimos anuncios", ""]
        L += [f"- **{client.fmt_ts(n['ts'])} — {n['asunto']}** ({n.get('autor') or ''}): {_short(n['texto'], 300)}"
              for n in news[:5]]
        L.append("")

    extras = []
    if (sdir / "enlaces.md").exists():
        extras.append("[Enlaces del aula](enlaces.md)")
    if (sdir / "apuntes").is_dir():
        extras += [f"[{p.stem}]({_link('apuntes/' + p.name)})" for p in sorted((sdir / "apuntes").glob("*.md"))]
    if extras:
        L += ["## 🔗 Más", "", " · ".join(extras), ""]
    return "\n".join(L)


def write_ficha(course: dict) -> Path:
    sdir = library.find_subject_dir(course)
    path = sdir / "ficha.md"
    path.write_text(build_ficha(course), encoding="utf-8")
    return path


def write_index() -> Path:
    gs = library.global_state()
    now = time.time()
    L = ["# 🎓 Mis estudios UNED", "",
         f"> Última sincronización: {client.fmt_ts(gs.get('ultima_sincronizacion'))}"
         + (f" · [Web de la titulación]({gs['titulacion']})" if gs.get("titulacion") else ""), "",
         "## Asignaturas", "", "| Asignatura | Próxima entrega | Avance | Ficha |", "|---|---|---|---|"]
    upcoming = []
    general = []
    for cid, info in gs.get("cursos", {}).items():
        sdir = config.STUDY_DIR / info["carpeta"]
        st = library.load_state(sdir)
        pending = sorted((d for d in st.get("plazos_detalle", []) if d["ts"] > now and d.get("estado") != "submitted"),
                         key=lambda d: d["ts"])
        upcoming += [(d["ts"], info["nombre"], d["nombre"]) for d in pending]
        if not info.get("asignatura"):
            general.append(f"- [{info['nombre']}]({_link(info['carpeta'])}/)")
            continue
        prog = planner.load_progress({"id": int(cid), "fullname": info["nombre"]}, sdir)
        nxt = f"{client.fmt_ts(pending[0]['ts'])[:10]} — {pending[0]['nombre']}" if pending else "—"
        L.append(f"| {info['nombre']} | {nxt} | {planner.progress_pct(prog)}% | "
                 f"[ficha]({_link(info['carpeta'] + '/ficha.md')}) |")
    proximas = [c for c in classes.all_classes() if c.fin >= now]
    if proximas:
        L += ["", "## 🏫 Próximas clases / jornadas", "", "| Día y hora | Sesión | Profesor/a | Modalidad |", "|---|---|---|---|"]
        L += [f"| {c.horario()} | [{c.titulo}]({_link(classes.source_link(c))}) | {c.profesor} | {c.modalidad} |"
              for c in proximas[:20]]
        for fuente, lines in classes.access_info():
            original = re.sub(r"/texto/(.*)[.]md$", r"/materiales/\1", fuente)
            L += ["", f"**Acceso** ([{Path(original).name}]({_link(original)})):", *[f"- {x}" for x in lines]]
    L += ["", "## ⏰ Próximas fechas", ""]
    L += [f"- **{client.fmt_ts(ts)}** — {n} · *{c}*" for ts, c, n in sorted(upcoming)[:15]] or ["- Nada pendiente."]
    if general:
        L += ["", "## Otros espacios del campus", "", *general]
    L += ["", "## Archivos útiles", "", "- [Plan semanal](plan-semanal.md)", "- [Calendario .ics](calendario.ics)",
          "- [Novedades de la última sincronización](novedades.md)", ""]
    path = config.STUDY_DIR / "README.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path
