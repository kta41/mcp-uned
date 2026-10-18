from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from uned_mcp import config, extract, ficha, guide, index, library, planner

GUIDE_PAGE_1 = """ÍNDICE
EQUIPO DOCENTE
CONTENIDOS
"""
GUIDE_PAGE_2 = """Nombre de la asignatura
HISTORIA DEL ARTE MODERNO
Nº ETCS
4
Horas
100
Periodo
SEMESTRE 1
Idiomas en que se imparte
CASTELLANO
UNED
3
CURSO 2026/27

HISTORIA DEL ARTE MODERNO
CÓDIGO 6701203-
PRESENTACIÓN Y CONTEXTUALIZACIÓN
Texto de presentación.
EQUIPO DOCENTE
Nombre y Apellidos
ANA PÉREZ GARCÍA
Correo Electrónico
aperez@example.uned.es
CONTENIDOS
Temario de la asignatura
1. El Renacimiento en Italia
2. Los orígenes del Barroco
europeo. Detalle que no forma parte del título.
3, Arte y poder en la corte de los Austrias
3.1 Subtema que no es un tema
SISTEMA DE EVALUACIÓN
Tipo de examen
No hay prueba presencial
Ponderación de la prueba presencial y/o
los trabajos en la nota final
Ensayo 1: 50% y ensayo 2: 50%
Fecha aproximada de entrega
Antes del 20/12/2026
Comentarios y observaciones
"""


@pytest.fixture()
def study_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STUDY_DIR", tmp_path)
    monkeypatch.setattr(config, "INDEX_DB", tmp_path / ".idx.sqlite")
    monkeypatch.setattr(config, "STATE_FILE", tmp_path / ".estado.json")
    return tmp_path


def _guide() -> guide.Guide:
    meta, teachers, sections = guide.parse_guide_text(["portada", GUIDE_PAGE_1, GUIDE_PAGE_2])
    return guide.Guide(codigo="6701203-", titulacion="670101", curso="2027", url_pdf="", url_web="",
                       ects=meta.get("ects", ""), horas=meta.get("horas", ""),
                       periodo=meta.get("periodo", ""), equipo=teachers, secciones=sections)


def test_parse_guide_meta_teachers_and_sections():
    meta, teachers, sections = guide.parse_guide_text(["portada", GUIDE_PAGE_1, GUIDE_PAGE_2])
    assert meta == {"ects": "4", "horas": "100", "periodo": "SEMESTRE 1"}
    assert [(t.nombre, t.email, t.telefono) for t in teachers] == [("Ana Pérez García", "aperez@example.uned.es", "")]
    assert "CURSO 2026/27" not in "\n".join(sections.values())
    assert sections["CONTENIDOS"].startswith("Temario")


def test_topics_join_lines_and_skip_subtopics():
    assert planner.topics_from_guide(_guide()) == [
        "1. El Renacimiento en Italia",
        "2. Los orígenes del Barroco europeo",
        "3. Arte y poder en la corte de los Austrias",
    ]


def test_evaluation_summary_multiline_weighting():
    summary = ficha._evaluation_summary(_guide().secciones["SISTEMA DE EVALUACIÓN"])
    assert "- **Tipo de examen**: No hay prueba presencial" in summary
    assert "- **Ponderación**: Ensayo 1: 50% y ensayo 2: 50%" in summary


def test_extract_docx_and_pptx(tmp_path):
    docx = tmp_path / "a.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>Hola</w:t></w:r>'
                                        '<w:r><w:t> mundo</w:t></w:r></w:p></w:body></w:document>')
    pptx = tmp_path / "b.pptx"
    with zipfile.ZipFile(pptx, "w") as z:
        z.writestr("ppt/slides/slide1.xml", '<p:sld xmlns:a="a" xmlns:p="p"><a:p><a:r><a:t>Diapositiva</a:t></a:r></a:p></p:sld>')
    assert "Hola mundo" in extract.extract(docx).chunks[0].text
    ext = extract.extract(pptx)
    assert ext.chunks[0].location.endswith("1") and "Diapositiva" in ext.chunks[0].text


def test_index_search_ignores_accents(study_dir):
    index.replace_file("Asig", "Asig/texto/t.md", [extract.Chunk("p. 4", "La teoría de la ventaja comparativa según Ricardo")])
    hits = index.search("VENTAJA comparatíva")
    assert hits and hits[0]["ubicacion"] == "p. 4" and "**" in hits[0]["fragmento"]
    index.remove_file("Asig/texto/t.md")
    assert index.search("ventaja") == []


def test_progress_marking_by_number_and_pct(study_dir, monkeypatch):
    course = {"id": 1, "fullname": "Historia del Arte Moderno"}
    sdir = library.find_subject_dir(course)
    sdir.mkdir(parents=True)
    monkeypatch.setattr(guide, "load_guide", lambda _d: _guide())
    assert planner.mark_topic(course, "3", "dominado").startswith("3. Arte y poder")
    planner.mark_topic(course, "orígenes", "visto")
    prog = planner.load_progress(course, sdir)
    assert [t["estado"] for t in prog["temas"]] == ["pendiente", "visto", "dominado"]
    assert planner.progress_pct(prog) == 53
    with pytest.raises(ValueError):
        planner.mark_topic(course, "1", "aprobado")


def test_ics_escape():
    assert planner._ics_escape("a,b;c\nd") == "a\\,b\\;c\\nd"


def test_safe_name_is_filesystem_safe():
    name = library.safe_name('a/b:c*?"<>|')
    assert not set(name) & set('/\\:*?"<>|')
    assert Path(name).name == name


SCHEDULE = """# Horario de jornadas.pdf

## [p. 1]

GRADO EN EJEMPLO
CURSO 2026-2027
VIERNES 6 NOVIEMBRE Y 15 DE ENERO
De 16:00 a 16:30
 Presentación del Grado- sólo la primera jornada
De 16:30 a 17,45
Derecho Constitucional
Prof: Ana Pérez García
SÁBADO 7 DE NOVIEMBRE DE 2026
De 10,00 a 11,15
Historia del Arte
Moderno. Profs. Luis Gómez y Eva Ruiz
INSTITUTO DE EJEMPLO
Acceso por videoconferencia (Zoom)
https://example.zoom.us/j/123
ID de reunión: 123 456
"""


def test_parse_class_schedule():
    from datetime import datetime

    from uned_mcp import classes

    h = classes.parse_schedule(SCHEDULE, "x")
    got = [(datetime.fromtimestamp(c.inicio, config.TZ).strftime("%d/%m/%Y %H:%M"), c.titulo, c.profesor) for c in h.clases]
    assert got == [
        ("06/11/2026 16:00", "Presentación del Grado", ""),
        ("06/11/2026 16:30", "Derecho Constitucional", "Ana Pérez García"),
        ("15/01/2027 16:30", "Derecho Constitucional", "Ana Pérez García"),
        ("07/11/2026 10:00", "Historia del Arte Moderno", "Luis Gómez y Eva Ruiz"),
    ]
    assert h.modalidad == "online"
    assert h.acceso == ["https://example.zoom.us/j/123", "ID de reunión: 123 456"]
    assert classes.match_subject("Historia del arte moderno.", ["Derecho Constitucional", "Historia del Arte Moderno"]) \
        == "Historia del Arte Moderno"
