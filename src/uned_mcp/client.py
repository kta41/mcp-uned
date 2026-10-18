from __future__ import annotations

import functools
import html
import json
import os
import re
import ssl
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from uned_mcp import config


@functools.cache
def ssl_context() -> ssl.SSLContext:
    """System CAs plus the optional corporate bundle (httpx ignores REQUESTS_CA_BUNDLE)."""
    ctx = ssl.create_default_context()
    bundle = os.environ.get("UNED_MCP_CA_BUNDLE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if bundle and os.path.isfile(bundle):
        ctx.load_verify_locations(cafile=bundle)
    return ctx


def load_token() -> str | None:
    try:
        return json.loads(config.TOKEN_FILE.read_text(encoding="utf-8"))["token"]
    except Exception:
        return None


def save_auth(data: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.TOKEN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    config.TOKEN_FILE.chmod(0o600)


def clear_auth() -> None:
    for f in (config.TOKEN_FILE, config.SESSION_FILE):
        f.unlink(missing_ok=True)


def call(wsfunction: str, **params: Any) -> Any:
    """Call the Moodle REST API. Returns the decoded JSON, or a dict with an 'error' key."""
    token = load_token()
    if not token:
        return {"error": "NO_TOKEN", "message": "Aún no hay token. Pide: 'haz login en la UNED'."}
    payload = {"wstoken": token, "wsfunction": wsfunction, "moodlewsrestformat": "json", **params}
    try:
        r = httpx.post(f"{config.BASE_URL}/webservice/rest/server.php", data=payload, timeout=30, verify=ssl_context())
        data = r.json()
    except Exception as exc:
        return {"error": "HTTP", "message": f"Fallo de conexión con {config.BASE_URL}: {exc}"}
    if isinstance(data, dict) and (data.get("exception") or data.get("error")):
        return {"error": data.get("errorcode", "wserror"), "message": data.get("message", str(data)[:200])}
    return data


def is_error(data: Any) -> bool:
    return isinstance(data, dict) and bool(data.get("error"))


def arr(name: str, values) -> dict:
    """Moodle REST list encoding: name[0]=..., name[1]=..."""
    return {f"{name}[{i}]": v for i, v in enumerate(values)}


def fmt_ts(ts) -> str:
    if not ts:
        return "sin fecha"
    return datetime.fromtimestamp(int(ts), config.TZ).strftime("%d/%m/%Y %H:%M")


def strip_html(text: str, limit: int = 220) -> str:
    txt = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", txt).strip()[:limit]


def get_courses() -> tuple[dict, list[dict]]:
    """Return (siteinfo, courses). Raises RuntimeError when the token is unusable."""
    site = call("core_webservice_get_site_info")
    if is_error(site):
        raise RuntimeError(
            f"El token no funciona ({site.get('error')}: {site.get('message')}). "
            "Pide de nuevo: 'haz login en la UNED'."
        )
    courses = call("core_enrol_get_users_courses", userid=site.get("userid"))
    if is_error(courses):
        raise RuntimeError(f"No se pudieron listar los cursos ({courses.get('error')}: {courses.get('message')}).")
    return site, [c for c in courses or [] if isinstance(c, dict)]


def upcoming_assignments(courses: list[dict], days: int) -> list[dict]:
    ids = [c["id"] for c in courses]
    name_of = {c["id"]: c.get("fullname") or c.get("shortname") or str(c["id"]) for c in courses}
    data = call("mod_assign_get_assignments", **arr("courseids", ids))
    if is_error(data) or not isinstance(data, dict):
        return []
    now, limit = time.time(), time.time() + days * 86400
    out = []
    for c in data.get("courses", []):
        for a in c.get("assignments", []):
            due = a.get("duedate") or 0
            if due and now <= due <= limit:
                out.append({"curso": name_of.get(c.get("id"), c.get("id")), "tarea": a.get("name"),
                            "entrega": fmt_ts(due), "ts": due})
    out.sort(key=lambda x: x["ts"])
    return out


def course_news(course_id: int, forum_limit: int = 1, disc_limit: int = 3) -> list[dict]:
    """Latest posts from the course 'news' forum (teacher announcements)."""
    forums = call("mod_forum_get_forums_by_courses", **arr("courseids", [course_id]))
    if is_error(forums) or not isinstance(forums, list):
        return []
    news = [f for f in forums if f.get("type") == "news"] or forums[:forum_limit]
    items = []
    for f in news[:forum_limit]:
        res = call("mod_forum_get_forum_discussions", forumid=f.get("id"), sortorder=-1, perpage=disc_limit)
        discs = res.get("discussions", []) if isinstance(res, dict) and not is_error(res) else []
        for d in discs:
            ts = d.get("timemodified") or d.get("created")
            items.append({"asunto": d.get("subject") or d.get("name"), "por": d.get("userfullname"),
                          "fecha": fmt_ts(ts), "ts": ts or 0, "texto": strip_html(d.get("message", ""))})
    return items


def normalize(text: str) -> str:
    """Lowercase, strip accents and collapse whitespace (for fuzzy name matching)."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def resolve_course(courses: list[dict], query: str | int) -> dict:
    """Find a course by id or by (accent-insensitive) name fragment. Raises ValueError otherwise."""
    q = str(query).strip()
    if q.isdigit():
        for c in courses:
            if c["id"] == int(q):
                return c
    nq = normalize(q)
    exact = [c for c in courses if normalize(c.get("fullname", "")) == nq]
    if exact:
        return exact[0]
    hits = [c for c in courses if nq and nq in normalize(c.get("fullname", ""))]
    if not hits:
        words = nq.split()
        hits = [c for c in courses if words and all(w in normalize(c.get("fullname", "")) for w in words)]
    if len(hits) == 1:
        return hits[0]
    options = ", ".join(f"{c.get('fullname')} (id={c['id']})" for c in (hits or courses))
    raise ValueError(f"No identifico la asignatura '{query}'. Opciones: {options}")


def strip_url_token(url: str) -> str:
    """Canonical file URL (without query string) used as a stable manifest key."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def download(url: str, dest: Path) -> int:
    """Download a Moodle file URL (adds the token) to dest atomically. Returns size in bytes."""
    token = load_token()
    if not token:
        raise RuntimeError("Sin token. Haz login primero.")
    sep = "&" if "?" in url else "?"
    full = f"{url}{sep}token={token}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with httpx.stream("GET", full, timeout=120, verify=ssl_context(), follow_redirects=True) as r:
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "application/json" in ctype:
            body = r.read().decode("utf-8", "replace")
            raise RuntimeError(f"Moodle devolvió error al descargar: {body[:200]}")
        with tmp.open("wb") as fh:
            for chunk in r.iter_bytes():
                fh.write(chunk)
    tmp.replace(dest)
    return dest.stat().st_size


def fetch_public(url: str, binary: bool = False) -> str | bytes:
    """GET a public UNED page (guides, degree pages)."""
    r = httpx.get(url, timeout=60, verify=ssl_context(), follow_redirects=True)
    r.raise_for_status()
    return r.content if binary else r.text
