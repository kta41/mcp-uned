"""Public UNED study guides (guía docente) for each subject."""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from uned_mcp import client, config

UNED_WEB = "https://www.uned.es"
GUIDE_PDF = ("{web}/universidad/pdf/GuiasAsignaturas{tipo}/PDFGuiaPublica?codigoAsignatura={cod}"
             "&curso={curso}&codigoTitulacion={tit}&language=es")

HEADINGS = [
    "PRESENTACIÓN Y CONTEXTUALIZACIÓN",
    "REQUISITOS Y/O RECOMENDACIONES PARA CURSAR ESTA ASIGNATURA",
    "EQUIPO DOCENTE",
    "HORARIO DE ATENCIÓN AL ESTUDIANTE",
    "TUTORIZACIÓN EN CENTROS ASOCIADOS",
    "COMPETENCIAS QUE ADQUIERE EL ESTUDIANTE",
    "RESULTADOS DE APRENDIZAJE",
    "CONTENIDOS",
    "METODOLOGÍA",
    "SISTEMA DE EVALUACIÓN",
    "BIBLIOGRAFÍA BÁSICA",
    "BIBLIOGRAFÍA COMPLEMENTARIA",
    "RECURSOS DE APOYO Y WEBGRAFÍA",
    "PRÁCTICAS DE LABORATORIO",
    "IGUALDAD DE GÉNERO",
]


@dataclass
class Teacher:
    nombre: str
    email: str = ""
    telefono: str = ""
    facultad: str = ""
    departamento: str = ""


@dataclass
class Guide:
    codigo: str
    titulacion: str
    curso: str
    url_pdf: str
    url_web: str
    ects: str = ""
    horas: str = ""
    periodo: str = ""
    equipo: list[Teacher] = field(default_factory=list)
    secciones: dict[str, str] = field(default_factory=dict)
    fechas_entrega: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> Guide:
        data = json.loads(raw)
        data["equipo"] = [Teacher(**t) for t in data.get("equipo", [])]
        return cls(**data)


# --------------------------------------------------------------------------- #
# Degree page: subject codes
# --------------------------------------------------------------------------- #

def degree_url(courses: list[dict]) -> str | None:
    """Guess the public degree page from the Moodle 'MÁSTER/GRADO ...' umbrella course."""
    import os

    if os.environ.get("UNED_TITULACION_URL"):
        return os.environ["UNED_TITULACION_URL"]
    for c in courses:
        name = client.normalize(c.get("fullname", ""))
        if name.startswith(("master universitario", "grado en")):
            kind = "masteres" if name.startswith("master") else "grados"
            return f"{UNED_WEB}/universidad/inicio/estudios/{kind}/{name.replace(' ', '-')}.html"
    return None


def subject_codes(page_html: str) -> dict[str, tuple[str, str]]:
    """Map normalized subject name -> (codAsignatura, codTitulacion)."""
    out = {}
    for cod, tit, name in re.findall(
            r'codAsignatura=([0-9A-Za-z-]+)&(?:amp;)?codTitulacion=(\d+)"[^>]*>\s*([^<]{3,200})', page_html):
        out[client.normalize(html.unescape(name))] = (cod, tit)
    return out


def match_code(course_name: str, codes: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
    n = client.normalize(course_name)
    if n in codes:
        return codes[n]
    hits = [v for k, v in codes.items() if n in k or k in n]
    return hits[0] if len(hits) == 1 else None


def academic_year(course: dict) -> str:
    """UNED guide 'curso' is the ending year of the academic year (2026/27 -> 2027)."""
    m = re.search(r"(20\d\d)", course.get("categoryname") or "")
    if m:
        return m.group(1)
    from datetime import datetime

    end = course.get("enddate") or course.get("startdate")
    if end:
        d = datetime.fromtimestamp(int(end), config.TZ)
        return str(d.year if d.month < 9 else d.year + 1)
    now = datetime.now(config.TZ)
    return str(now.year + 1 if now.month >= 9 else now.year)


# --------------------------------------------------------------------------- #
# Guide PDF parsing
# --------------------------------------------------------------------------- #

_TEACHER_RE = re.compile(
    r"Nombre y Apellidos\n(?P<nombre>.+?)\nCorreo Electr[oó]nico\n(?P<email>\S*)\n"
    r"(?:Tel[eé]fono\n(?P<tel>.*?)\n)?(?:Facultad\n(?P<fac>.*?)\n)?(?:Departamento\n(?P<dep>.*?)\n)?", re.I)
_FOOTER_RE = re.compile(r"(?m)^UNED\n\d+\nCURSO \d{4}/\d{2}\n(?:\n*[^\na-z]+\nC[ÓO]DIGO \S+\n?)?")
_FOOTER2_RE = re.compile(r"(?m)^[^\na-z]{5,}\nC[ÓO]DIGO [0-9][\S]*\n?")
_META_RE = re.compile(r"Nombre de la asignatura\n.*?Idiomas en que se imparte\n[^\n]*\n", re.S)
_CSV_RE = re.compile(r"(?m)^.*(C[óo]digo Seguro de Verificaci[óo]n|sede\.uned\.es/valida|[ÁA]mbito: GUI).*\n?")


def page_text(page) -> str:
    """Text blocks in reading order (plain get_text() mixes up the guide's table cells)."""
    return "".join(b[4] if b[4].endswith("\n") else b[4] + "\n" for b in page.get_text("blocks", sort=True) if b[6] == 0)


def _heading_re(h: str) -> re.Pattern:
    words = [re.escape(w) for w in h.split()]
    return re.compile(r"(?m)^\s*" + r"\s+".join(words) + r"\s*$")


def parse_guide_text(pages: list[str]) -> tuple[dict, list[Teacher], dict[str, str]]:
    meta: dict[str, str] = {}
    teachers: list[Teacher] = []
    clean_pages = []
    for i, text in enumerate(pages):
        text = text.replace("\u00a0", " ")
        text = re.sub(r"[ \t]+\n", "\n", text)
        for m in _TEACHER_RE.finditer(text):
            teachers.append(Teacher(m["nombre"].strip().title() if m["nombre"].isupper() else m["nombre"].strip(),
                                    m["email"].strip(), (m["tel"] or "").strip(),
                                    (m["fac"] or "").strip(), (m["dep"] or "").strip()))
        text = _TEACHER_RE.sub("", text)
        mm = _META_RE.search(text)
        if mm:
            block = mm.group(0)
            for key, label in (("ects", r"N[ºo°] (?:ECTS|ETCS)"), ("horas", "Horas"), ("periodo", "Periodo")):
                v = re.search(label + r"\n([^\n]+)", block)
                if v:
                    meta[key] = v.group(1).strip()
            text = _META_RE.sub("", text)
        text = _CSV_RE.sub("", _FOOTER2_RE.sub("", _FOOTER_RE.sub("", text)))
        if i >= 2 or not re.search(r"(?m)^ÍNDICE$", text):
            clean_pages.append(text)
    full = re.sub(r"\n\s*\n+", "\n\n", "\n".join(clean_pages))

    sections: dict[str, str] = {}
    positions = []
    pos = 0
    for h in HEADINGS:
        m = _heading_re(h).search(full, pos)
        if m:
            positions.append((h, m.start(), m.end()))
            pos = m.end()
    for idx, (h, _start, end) in enumerate(positions):
        stop = positions[idx + 1][1] if idx + 1 < len(positions) else len(full)
        body = full[end:stop].strip()
        if body:
            sections[h] = body
    seen = set()
    teachers = [t for t in teachers if not (t.nombre in seen or seen.add(t.nombre))]
    return meta, teachers, sections


def fetch_guide(course: dict, codes: dict, degree_page: str, dest_dir: Path) -> Guide | None:
    match = match_code(course.get("fullname", ""), codes)
    if not match:
        return None
    cod, tit = match
    curso = academic_year(course)
    tipo = "Master" if "/masteres/" in degree_page else "Grado"
    url_pdf = GUIDE_PDF.format(web=UNED_WEB, tipo=tipo, cod=cod, curso=curso, tit=tit)
    url_web = degree_page.removesuffix(".html") + f"/asignaturas.html?codAsignatura={cod}&codTitulacion={tit}"
    pdf = client.fetch_public(url_pdf, binary=True)
    if not pdf.startswith(b"%PDF"):
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "guia-docente.pdf").write_bytes(pdf)

    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pages = [page_text(p) for p in doc]
    meta, teachers, sections = parse_guide_text(pages)
    evaluation = sections.get("SISTEMA DE EVALUACIÓN", "")
    fechas = [f.strip() for f in re.findall(r"Fecha aproximada de entrega\n([^\n]+)", evaluation)
              if f.strip() and not f.strip().lower().startswith(("ponderaci", "comentarios"))]
    guide = Guide(cod, tit, curso, url_pdf, url_web, meta.get("ects", ""), meta.get("horas", ""),
                  meta.get("periodo", ""), teachers, sections, fechas)
    (dest_dir / "guia-docente.json").write_text(guide.to_json(), encoding="utf-8")
    (dest_dir / "guia-docente.md").write_text(guide_markdown(course.get("fullname", ""), guide), encoding="utf-8")
    return guide


def load_guide(dest_dir: Path) -> Guide | None:
    try:
        return Guide.from_json((dest_dir / "guia-docente.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def guide_markdown(name: str, g: Guide) -> str:
    lines = [f"# Guía docente — {name}", "",
             f"> Código {g.codigo} · Curso {int(g.curso) - 1}/{g.curso[-2:]} · [PDF oficial]({g.url_pdf}) · "
             f"[Web]({g.url_web})", ""]
    for h, body in g.secciones.items():
        lines += [f"## {h.capitalize()}", "", body, ""]
    return "\n".join(lines)
