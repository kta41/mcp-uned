"""Text extraction from course materials into page/section chunks."""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

TEXT_SUFFIXES = {".pdf", ".docx", ".pptx", ".odt", ".html", ".htm", ".txt", ".md", ".rtf", ".eml"}
MIN_CHARS_PER_PAGE = 60


@dataclass
class Chunk:
    location: str  # "p. 3" or "sección 2"
    text: str


@dataclass
class Extraction:
    chunks: list[Chunk]
    pages: int = 0
    needs_ocr: bool = False

    @property
    def chars(self) -> int:
        return sum(len(c.text) for c in self.chunks)


def _clean(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\r", "")
    text = re.sub(r"-\n(?=[a-záéíóúñ])", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</tr>|</div>", "\n", raw)
    return _clean(html.unescape(re.sub(r"<[^>]+>", " ", raw)))


def _split_sections(text: str, size: int = 2500) -> list[Chunk]:
    paras, chunks, buf = text.split("\n"), [], ""
    for p in paras:
        if len(buf) + len(p) > size and buf:
            chunks.append(Chunk(f"sección {len(chunks) + 1}", buf.strip()))
            buf = ""
        buf += p + "\n"
    if buf.strip():
        chunks.append(Chunk(f"sección {len(chunks) + 1}", buf.strip()))
    return chunks


def _xml_text(xml: str, para_tag: str, text_tag: str) -> str:
    paras = re.findall(rf"<{para_tag}[ >].*?</{para_tag}>", xml, re.S)
    out = []
    for p in paras:
        out.append("".join(re.findall(rf"<{text_tag}(?: [^>]*)?>([^<]*)</{text_tag}>", p)))
    return html.unescape("\n".join(out))


def _pdf(path: Path) -> Extraction:
    import pymupdf

    chunks = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            txt = _clean(page.get_text())
            if txt:
                chunks.append(Chunk(f"p. {i}", txt))
        pages = doc.page_count
    ext = Extraction(chunks, pages)
    ext.needs_ocr = pages > 0 and ext.chars / pages < MIN_CHARS_PER_PAGE
    return ext


def _docx(path: Path) -> Extraction:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    return Extraction(_split_sections(_clean(_xml_text(xml, "w:p", "w:t"))))


def _odt(path: Path) -> Extraction:
    with zipfile.ZipFile(path) as z:
        xml = z.read("content.xml").decode("utf-8", "replace")
    return Extraction(_split_sections(html_to_text(xml)))


def _pptx(path: Path) -> Extraction:
    chunks = []
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        for i, name in enumerate(slides, start=1):
            txt = _clean(_xml_text(z.read(name).decode("utf-8", "replace"), "a:p", "a:t"))
            if txt:
                chunks.append(Chunk(f"diapositiva {i}", txt))
    return Extraction(chunks, len(chunks))


def _rtf(path: Path) -> Extraction:
    raw = path.read_text("latin-1", errors="replace")
    raw = re.sub(r"\\'([0-9a-f]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "replace"), raw)
    raw = re.sub(r"\\par[d]?\b", "\n", raw)
    raw = re.sub(r"\{\\\*[^{}]*\}|\\[a-z]+-?\d* ?|[{}]", "", raw)
    return Extraction(_split_sections(_clean(raw)))


def ocr_available() -> bool:
    return shutil.which("ocrmypdf") is not None


def run_ocr(path: Path) -> Path | None:
    """OCR a scanned PDF with ocrmypdf (if installed). Returns the OCR'd copy path."""
    if not ocr_available():
        return None
    out = path.with_name(path.stem + ".ocr.pdf")
    res = subprocess.run(["ocrmypdf", "-l", "spa+eng", "--skip-text", "--quiet", str(path), str(out)],  # noqa: S603,S607
                         capture_output=True, timeout=900, check=False)
    return out if res.returncode == 0 and out.exists() else None


def extract(path: Path) -> Extraction | None:
    """Extract text from a supported file. Returns None for unsupported types."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            return _pdf(path)
        if suffix == ".docx":
            return _docx(path)
        if suffix == ".odt":
            return _odt(path)
        if suffix == ".pptx":
            return _pptx(path)
        if suffix == ".rtf":
            return _rtf(path)
        if suffix in {".html", ".htm"}:
            return Extraction(_split_sections(html_to_text(path.read_text("utf-8", errors="replace"))))
        if suffix in {".txt", ".md", ".eml"}:
            return Extraction(_split_sections(_clean(path.read_text("utf-8", errors="replace"))))
    except Exception:  # corrupt or encrypted files should not break a sync
        return Extraction([], 0)
    return None


def to_markdown(title: str, source: str, ext: Extraction) -> str:
    head = f"# {title}\n\n> Fuente: `{source}`"
    if ext.pages:
        head += f" · {ext.pages} páginas"
    if ext.needs_ocr:
        head += " · ⚠️ PDF escaneado: texto incompleto (necesita OCR)"
    body = "\n\n".join(f"## [{c.location}]\n\n{c.text}" for c in ext.chunks)
    return f"{head}\n\n{body}\n"
