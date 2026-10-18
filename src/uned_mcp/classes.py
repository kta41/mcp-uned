"""Class / session schedules (jornadas, clases, sesiones) parsed from downloaded course documents.

Degree coordinators usually publish the timetable of the live sessions as a PDF in the general degree
course (e.g. "Horario de tutorías y jornadas.pdf"). This module finds those documents among the
extracted texts, parses day headers ("VIERNES 23 OCTUBRE Y 11 DE DICIEMBRE DE 2026"), time slots
("De 17,00 a 18,15"), titles and teachers, and maps every slot to the enrolled subject it belongs to.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from uned_mcp import client, config, library

MONTHS = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                      "septiembre", "octubre", "noviembre", "diciembre"), start=1)}
_WEEKDAY_RE = re.compile(r"^(lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b")
_DATE_RE = re.compile(r"\b(\d{1,2})\s+(?:de\s+)?(" + "|".join(MONTHS) + r")\b")
_YEAR_RE = re.compile(r"\b(20\d\d)\b")
_COURSE_YEAR_RE = re.compile(r"curso\s+(20\d\d)\s*[-/]\s*(20\d\d)")
_SLOT_RE = re.compile(r"^de\s+(\d{1,2})[:.,h](\d{2})\s*(?:h\s*)?a\s+(\d{1,2})[:.,h](\d{2})")
_PROF_RE = re.compile(r"\bProf(?:esor(?:a|es)?|s)?\s*[.:]\s*", re.I)
_DOC_NAME_RE = re.compile(r"jornada|sesion|clase|horario|calendario|cronograma|tutoria", re.I)
_ACCESS_RE = re.compile(r"(https?://\S*(?:zoom|teams|meet|webex|intecca)\S*|ID de reuni[oó]n\s*:.*|C[oó]digo de acceso\s*:.*)", re.I)
_GENERAL_RE = re.compile(r"presentaci[oó]n|bienvenida|inaugura|acogida")


@dataclass
class Clase:
    inicio: float
    fin: float
    titulo: str
    profesor: str = ""
    modalidad: str = ""
    fuente: str = ""
    asignatura: str = ""

    @property
    def uid(self) -> str:
        return "clase-" + hashlib.sha1(f"{self.inicio}|{client.normalize(self.titulo)}".encode()).hexdigest()[:16]

    def horario(self) -> str:
        a = datetime.fromtimestamp(self.inicio, config.TZ)
        b = datetime.fromtimestamp(self.fin, config.TZ)
        return f"{_DIAS[a.weekday()]} {a.strftime('%d/%m/%Y')} · {a.strftime('%H:%M')}–{b.strftime('%H:%M')}"


_DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


@dataclass
class Horario:
    fuente: str
    modalidad: str
    clases: list[Clase] = field(default_factory=list)
    acceso: list[str] = field(default_factory=list)


def _clean_lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ">")) or line in ("−", "-", "–"):
            continue
        out.append(line)
    return out


def _default_year(norm_text: str) -> tuple[int, int]:
    m = _COURSE_YEAR_RE.search(norm_text)
    if m:
        return int(m.group(1)), int(m.group(2))
    y = datetime.now(config.TZ).year
    return y, y + 1


def parse_schedule(text: str, fuente: str = "") -> Horario:
    """Parse a timetable document. Returns an empty Horario when it does not look like one."""
    norm_all = client.normalize(text)
    modalidad = "online" if re.search(r"\bonline\b|videoconferencia|zoom|teams", norm_all) else (
        "presencial" if "presencial" in norm_all else "")
    first_year, second_year = _default_year(norm_all)
    h = Horario(fuente=fuente, modalidad=modalidad)
    dates: list[tuple[int, int, int]] = []
    slot: dict | None = None

    def close():
        nonlocal slot
        if slot and slot["title"] and dates:
            title = " ".join(slot["title"]).strip(" .-–")
            only_first = re.search(r"s[oó]lo la primera", title, re.I)
            title = re.sub(r"\s*[-–]\s*s[oó]lo la primera.*$", "", title, flags=re.I).strip(" .-–")
            for y, mo, d in (dates[:1] if only_first else dates):
                try:
                    start = datetime(y, mo, d, slot["h1"], slot["m1"], tzinfo=config.TZ)
                    end = datetime(y, mo, d, slot["h2"], slot["m2"], tzinfo=config.TZ)
                except ValueError:
                    continue
                h.clases.append(Clase(start.timestamp(), end.timestamp(), title, slot["prof"], modalidad, fuente))
        slot = None

    for line in _clean_lines(text):
        norm = client.normalize(line)
        if _WEEKDAY_RE.match(norm) and _DATE_RE.search(norm):
            close()
            year_m = _YEAR_RE.search(norm)
            dates = []
            for d, month in _DATE_RE.findall(norm):
                mo = MONTHS[month]
                y = int(year_m.group(1)) if year_m else (first_year if mo >= 9 else second_year)
                dates.append((y, mo, int(d)))
            continue
        m = _SLOT_RE.match(line.lower())
        if m:
            close()
            h1, m1, h2, m2 = map(int, m.groups())
            slot = {"h1": h1, "m1": m1, "h2": h2, "m2": m2, "title": [], "prof": "", "done": False}
            continue
        if slot is None or slot["done"]:
            continue
        parts = _PROF_RE.split(line, maxsplit=1)
        if len(parts) == 2:
            if parts[0].strip():
                slot["title"].append(parts[0].strip())
            slot["prof"] = parts[1].strip(" .")
            slot["done"] = True
        elif len(slot["title"]) < 4:
            slot["title"].append(line)
    close()
    if h.clases:
        h.acceso = list(dict.fromkeys(m.group(1).strip() for m in _ACCESS_RE.finditer(text)))
    return h


def _course_year_start(now: datetime) -> datetime:
    return datetime(now.year if now.month >= 9 else now.year - 1, 9, 1, tzinfo=config.TZ)


def schedules() -> list[Horario]:
    """Every current timetable found in the study folder (documents of past academic years are ignored)."""
    if not config.STUDY_DIR.is_dir():
        return []
    since = _course_year_start(datetime.now(config.TZ)).timestamp()
    out = []
    for path in sorted(config.STUDY_DIR.glob("**/texto/**/*.md")):
        if not _DOC_NAME_RE.search(client.normalize(path.name)):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = path.relative_to(config.STUDY_DIR).as_posix()
        h = parse_schedule(text, rel)
        h.clases = [c for c in h.clases if c.inicio >= since]
        if h.clases and not any(o.fuente == rel for o in out):
            out.append(h)
    return out


def _subject_names() -> list[str]:
    return [i["nombre"] for i in library.global_state().get("cursos", {}).values() if i.get("asignatura")]


def match_subject(title: str, subjects: list[str]) -> str:
    nt = client.normalize(title)
    for name in subjects:
        nn = client.normalize(name)
        if nt == nn or (len(nt) > 12 and (nt in nn or nn in nt)):
            return name
    return ""


def all_classes() -> list[Clase]:
    """Classes of enrolled subjects plus general sessions (degree presentation), de-duplicated and sorted."""
    subjects = _subject_names()
    seen: dict[tuple, Clase] = {}
    for h in schedules():
        for c in h.clases:
            c.asignatura = match_subject(c.titulo, subjects)
            if not c.asignatura and not _GENERAL_RE.search(client.normalize(c.titulo)):
                continue
            key = (c.inicio, client.normalize(c.titulo))
            if key not in seen or (not seen[key].profesor and c.profesor):
                seen[key] = c
    return sorted(seen.values(), key=lambda c: c.inicio)


def access_info() -> list[tuple[str, list[str]]]:
    """(source document, access lines) for timetables that include connection details."""
    return [(h.fuente, h.acceso) for h in schedules() if h.acceso]


def for_subject(name: str) -> list[Clase]:
    return [c for c in all_classes() if c.asignatura == name]


def source_link(c: Clase, from_dir: Path | None = None) -> str:
    """Markdown-friendly relative path from a subject folder (or the study root) to the original document."""
    src = re.sub(r"^(.*?)/texto/(.*)\.md$", r"\1/materiales/\2", c.fuente)
    if from_dir is not None and from_dir != config.STUDY_DIR:
        depth = len(from_dir.relative_to(config.STUDY_DIR).parts)
        src = "../" * depth + src
    return src
