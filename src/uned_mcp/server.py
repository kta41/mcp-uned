from __future__ import annotations

import time

from mcp.server.fastmcp import FastMCP

from uned_mcp import auth, classes, client, ficha, index, library, planner, study


def _fail(exc: Exception) -> str:
    return str(exc)


def _events(courses: list[dict], days: int) -> list[dict]:
    names = {c["id"]: c.get("fullname") for c in courses}
    evs = library.calendar_events([c["id"] for c in courses], days_back=0, days_ahead=days)
    return [{"evento": e["nombre"], "cuando": client.fmt_ts(e["ts"]), "curso": names.get(e["curso"]), "ts": e["ts"]}
            for e in sorted(evs, key=lambda e: e["ts"])]


def create_server() -> FastMCP:
    mcp = FastMCP("uned-campus")

    @mcp.tool()
    def uned_login() -> str:
        """Abre un navegador para que hagas login vía SSO de la UNED y guarda el token.

        Ejecútalo una vez (o cuando caduque el token). Tu contraseña nunca pasa por este código.
        """
        return auth.interactive_login()

    @mcp.tool()
    def uned_logout() -> str:
        """Borra el token y la sesión guardados en este ordenador."""
        client.clear_auth()
        return "Token y sesión eliminados."

    @mcp.tool()
    def uned_cursos() -> str:
        """Lista tus cursos matriculados (nombre, id y progreso si existe)."""
        try:
            _, courses = client.get_courses()
        except RuntimeError as exc:
            return _fail(exc)
        if not courses:
            return "No aparecen cursos matriculados para tu cuenta."
        lines = [f"• {c.get('fullname')} (id={c['id']})"
                 + (f" — progreso {round(float(c['progress']))}%" if c.get("progress") else "")
                 for c in courses]
        return f"Tienes {len(courses)} cursos:\n" + "\n".join(lines)

    @mcp.tool()
    def uned_entregas(dias: int = 30) -> str:
        """Tareas con fecha de entrega en los próximos N días, de todos tus cursos."""
        try:
            _, courses = client.get_courses()
        except RuntimeError as exc:
            return _fail(exc)
        items = client.upcoming_assignments(courses, dias)
        if not items:
            return f"Sin entregas en los próximos {dias} días."
        return f"Entregas en los próximos {dias} días:\n" + "\n".join(
            f"• [{i['entrega']}] {i['tarea']} — {i['curso']}" for i in items)

    @mcp.tool()
    def uned_eventos(dias: int = 30) -> str:
        """Eventos del calendario (entregas, exámenes, tutorías…) de los próximos N días."""
        try:
            _, courses = client.get_courses()
        except RuntimeError as exc:
            return _fail(exc)
        evs = _events(courses, dias)
        if not evs:
            return f"Sin eventos de calendario en los próximos {dias} días."
        return f"Eventos en los próximos {dias} días:\n" + "\n".join(
            f"• [{e['cuando']}] {e['evento']}" + (f" — {e['curso']}" if e.get("curso") else "") for e in evs)

    @mcp.tool()
    def uned_anuncios(dias: int = 7) -> str:
        """Últimos anuncios publicados por los profesores en los foros de avisos de cada curso."""
        try:
            _, courses = client.get_courses()
        except RuntimeError as exc:
            return _fail(exc)
        cutoff = time.time() - dias * 86400
        blocks = []
        for c in courses:
            recent = [n for n in client.course_news(c["id"]) if n["ts"] >= cutoff]
            if recent:
                body = "\n".join(f"  - [{n['fecha']}] {n['asunto']} — {n['texto']}" for n in recent)
                blocks.append(f"• {c.get('fullname') or c.get('shortname')}:\n{body}")
        if not blocks:
            return f"Sin anuncios nuevos en los últimos {dias} días."
        return "Anuncios recientes:\n" + "\n".join(blocks)

    @mcp.tool()
    def uned_notas() -> str:
        """Calificaciones publicadas, curso por curso."""
        try:
            _, courses = client.get_courses()
        except RuntimeError as exc:
            return _fail(exc)
        blocks = []
        for c in courses:
            data = client.call("gradereport_user_get_grade_items", courseid=c["id"])
            if client.is_error(data) or not isinstance(data, dict):
                continue
            for ug in data.get("usergrades", []):
                items = [g for g in ug.get("gradeitems", [])
                         if g.get("gradeformatted") and g.get("itemtype") != "category"]
                if items:
                    lines = "\n".join(f"  - {g.get('itemname') or g.get('itemtype')}: {g.get('gradeformatted')}"
                                      for g in items)
                    blocks.append(f"• {c.get('fullname') or c.get('shortname')}:\n{lines}")
                    break
        if not blocks:
            return "No hay calificaciones publicadas todavía."
        return "Calificaciones publicadas:\n" + "\n".join(blocks)

    @mcp.tool()
    def uned_novedades(dias: int = 7) -> str:
        """Resumen: próximas entregas + eventos + anuncios nuevos. Ideal para '¿qué tengo pendiente?'."""
        try:
            _, courses = client.get_courses()
        except RuntimeError as exc:
            return _fail(exc)
        ent = client.upcoming_assignments(courses, max(dias, 14))
        parts = ["ENTREGAS PRÓXIMAS:\n" + ("\n".join(
            f"• [{i['entrega']}] {i['tarea']} — {i['curso']}" for i in ent) or "• Nada pendiente con fecha.")]
        evs = _events(courses, dias)
        parts.append("CALENDARIO:\n" + ("\n".join(
            f"• [{e['cuando']}] {e['evento']}" for e in evs) or "• Sin eventos."))
        cutoff = time.time() - dias * 86400
        news_blocks = []
        for c in courses:
            news = [n for n in client.course_news(c["id"], disc_limit=2) if n["ts"] >= cutoff]
            if news:
                news_blocks.append(f"• {c.get('fullname') or c.get('shortname')}: "
                                   + " | ".join(n["asunto"] or "" for n in news))
        parts.append("ANUNCIOS NUEVOS:\n" + ("\n".join(news_blocks) or "• Sin anuncios nuevos."))
        return "\n\n".join(parts)

    @mcp.tool()
    def uned_curso_contenido(courseid: int) -> str:
        """Secciones y recursos de un curso concreto (usa el id de uned_cursos)."""
        data = client.call("core_course_get_contents", courseid=courseid)
        if client.is_error(data) or not isinstance(data, list):
            return f"{data.get('error')}: {data.get('message')}" if isinstance(data, dict) else "Respuesta inesperada."
        lines = []
        for section in data:
            lines.append(f"## {section.get('name')}")
            for mod in section.get("modules", []):
                lines.append(f"  - {mod.get('modname')}: {mod.get('name')}")
        return "\n".join(lines) or "Curso sin contenido visible."

    # ----------------------------------------------------------------------- #
    # Biblioteca de estudio local (~/UNED)
    # ----------------------------------------------------------------------- #

    @mcp.tool()
    def uned_sincronizar(asignatura: str = "", forzar: bool = False) -> str:
        """Descarga/actualiza materiales, guía docente, plazos y anuncios en la carpeta de estudio (~/UNED).

        Extrae el texto de PDFs/DOCX/PPTX, lo indexa para búsqueda, regenera fichas, índice y calendario .ics
        y devuelve un informe de cambios (materiales nuevos, plazos movidos, anuncios nuevos).
        asignatura: nombre parcial o id (vacío = todas). forzar: re-descarga todo.
        """
        try:
            return study.sync(asignatura or None, forzar)
        except (RuntimeError, ValueError) as exc:
            return _fail(exc)

    @mcp.tool()
    def uned_ficha(asignatura: str) -> str:
        """Ficha de una asignatura: equipo docente y contacto, fechas/entregas y su estado, evaluación,
        enunciados, temario con progreso, materiales, bibliografía y anuncios. También se guarda en ficha.md."""
        try:
            course = study.resolve(asignatura)
        except (RuntimeError, ValueError) as exc:
            return _fail(exc)
        if not library.load_state(library.find_subject_dir(course)):
            return f"'{course['fullname']}' no está sincronizada aún. Ejecuta uned_sincronizar."
        path = ficha.write_ficha(course)
        return f"(Guardada en {path})\n\n" + path.read_text(encoding="utf-8")

    @mcp.tool()
    def uned_materiales(asignatura: str) -> str:
        """Lista los materiales descargados de una asignatura con nº de páginas y la ruta de su texto extraído."""
        try:
            return study.materials(asignatura)
        except (RuntimeError, ValueError) as exc:
            return _fail(exc)

    @mcp.tool()
    def uned_buscar(consulta: str, asignatura: str = "", limite: int = 8) -> str:
        """Búsqueda de texto completo en tus materiales descargados. Devuelve fragmentos con archivo y página
        para citar la fuente. Úsala antes de explicar o resumir algo del temario."""
        name = None
        if asignatura:
            try:
                name = study.resolve(asignatura)["fullname"]
            except (RuntimeError, ValueError) as exc:
                return _fail(exc)
        hits = index.search(consulta, name, max(1, min(limite, 30)))
        if not hits:
            return "Sin resultados en los materiales indexados (¿has sincronizado?)."
        return "\n\n".join(f"[{i}] {h['asignatura']} · {h['archivo']} · {h['ubicacion']}\n{h['fragmento']}"
                            for i, h in enumerate(hits, start=1))

    @mcp.tool()
    def uned_leer(archivo: str, desde_pagina: int = 1, hasta_pagina: int = 0, max_caracteres: int = 30000) -> str:
        """Lee el texto extraído de un material (ruta relativa devuelta por uned_buscar/uned_materiales),
        opcionalmente un rango de páginas. Cita siempre archivo y página al usarlo."""
        return study.read_text(archivo, desde_pagina, hasta_pagina or None, max_caracteres)

    @mcp.tool()
    def uned_foros(asignatura: str, dias: int = 30) -> str:
        """Debates recientes de todos los foros de una asignatura (avisos, dudas por tema, estudiantes)."""
        try:
            course = study.resolve(asignatura)
        except (RuntimeError, ValueError) as exc:
            return _fail(exc)
        posts = library.forum_posts(course["id"], days=dias)
        if not posts:
            return f"Sin actividad en los foros de {course['fullname']} en {dias} días."
        return f"Foros de {course['fullname']} (últimos {dias} días):\n" + "\n".join(
            f"• [{client.fmt_ts(p['ts'])}] {p['foro']} › {p['asunto']} — {p['autor']} "
            f"({p['respuestas']} resp.)\n  {p['texto'][:400]}" for p in posts)

    @mcp.tool()
    def uned_progreso(asignatura: str = "") -> str:
        """Estado de estudio por tema (pendiente/leyendo/visto/repasado/dominado) de una o todas las asignaturas."""
        try:
            targets = [study.resolve(asignatura)] if asignatura else [
                {"id": int(k), "fullname": v["nombre"]}
                for k, v in library.global_state().get("cursos", {}).items() if v.get("asignatura")]
        except (RuntimeError, ValueError) as exc:
            return _fail(exc)
        out = []
        for c in targets:
            prog = planner.load_progress(c)
            out.append(f"## {c['fullname']} — {planner.progress_pct(prog)}%")
            out += [f"{planner.ESTADO_ICONO[t['estado']]} {t['tema']} — {t['estado']}"
                    + (f" ({t['actualizado']})" if t.get("actualizado") else "")
                    + (f" · {t['nota']}" if t.get("nota") else "") for t in prog["temas"]] or ["(sin temario)"]
        return "\n".join(out) or "Sin asignaturas sincronizadas."

    @mcp.tool()
    def uned_progreso_marcar(asignatura: str, tema: str, estado: str, nota: str = "") -> str:
        """Actualiza el estado de un tema: pendiente, leyendo, visto, repasado o dominado.
        tema: nombre o número (p. ej. '3' o 'Tema 3'). nota: comentario opcional (dudas, puntuación de test…)."""
        try:
            course = study.resolve(asignatura)
            msg = planner.mark_topic(course, tema, estado, nota)
            ficha.write_ficha(course)
            ficha.write_index()
            return msg
        except (RuntimeError, ValueError) as exc:
            return _fail(exc)

    @mcp.tool()
    def uned_plan(horas_semana: float = 10, semanas: int = 4) -> str:
        """Genera un plan de estudio semanal repartiendo tus horas según créditos, temario pendiente y
        cercanía de entregas. Se guarda en ~/UNED/plan-semanal.md."""
        path, text = planner.write_plan(horas_semana, max(1, min(semanas, 20)))
        return f"(Guardado en {path})\n\n{text}"

    @mcp.tool()
    def uned_clases(asignatura: str = "", incluir_pasadas: bool = False) -> str:
        """Clases, jornadas y sesiones (online o presenciales) con día, hora y profesor, según los horarios
        publicados en el campus. Requiere haber sincronizado. Incluye los datos de acceso si el horario los trae."""
        items = classes.all_classes()
        if asignatura:
            try:
                name = study.resolve(asignatura)["fullname"]
            except (RuntimeError, ValueError) as exc:
                return _fail(exc)
            items = [c for c in items if c.asignatura == name]
        if not incluir_pasadas:
            items = [c for c in items if c.fin >= time.time()]
        if not items:
            return "No hay clases o jornadas en los horarios descargados (sincroniza o revisa el curso de la titulación)."
        lines = [f"• {c.horario()} — {c.titulo}" + (f" · {c.profesor}" if c.profesor else "")
                 + (f" · {c.modalidad}" if c.modalidad else "") for c in items]
        for fuente, acceso in classes.access_info():
            lines += ["", f"Acceso (según {fuente.rsplit('/', 1)[-1].removesuffix('.md')}):", *[f"  {x}" for x in acceso]]
        return "Clases / jornadas:\n" + "\n".join(lines)

    @mcp.tool()
    def uned_calendario_ics() -> str:
        """Exporta entregas, eventos y clases/jornadas a ~/UNED/calendario.ics (importable en Google/Outlook)."""
        path = planner.write_ics()
        return f"Calendario exportado a {path} ({path.read_text(encoding='utf-8').count('BEGIN:VEVENT')} eventos)."

    @mcp.tool()
    def uned_guardar_apunte(asignatura: str, nombre: str, contenido: str) -> str:
        """Guarda un resumen, esquema, test o apunte en Markdown en <asignatura>/apuntes/ y lo enlaza en la ficha."""
        try:
            return f"Guardado en {study.save_note(asignatura, nombre, contenido)}"
        except (RuntimeError, ValueError) as exc:
            return _fail(exc)

    return mcp
