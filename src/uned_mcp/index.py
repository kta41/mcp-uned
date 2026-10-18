"""Local full-text index (SQLite FTS5) over extracted course materials."""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing

from uned_mcp import config
from uned_mcp.extract import Chunk

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    asignatura UNINDEXED, archivo UNINDEXED, ubicacion UNINDEXED, texto,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def _connect() -> sqlite3.Connection:
    config.STUDY_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.INDEX_DB)
    conn.executescript(_SCHEMA)
    return conn


def replace_file(asignatura: str, archivo: str, chunks: list[Chunk]) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM chunks WHERE archivo = ?", (archivo,))
        conn.executemany(
            "INSERT INTO chunks (asignatura, archivo, ubicacion, texto) VALUES (?, ?, ?, ?)",
            [(asignatura, archivo, c.location, c.text) for c in chunks],
        )


def remove_file(archivo: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM chunks WHERE archivo = ?", (archivo,))


def _fts_query(query: str, op: str) -> str:
    words = [w for w in re.findall(r"\w+", query) if len(w) > 1]
    return f" {op} ".join(f'"{w}"' for w in words)


def search(query: str, asignatura: str | None = None, limit: int = 8) -> list[dict]:
    """Search chunks; AND of all words first, then OR as fallback. Results ranked by bm25."""
    sql = ("SELECT asignatura, archivo, ubicacion, snippet(chunks, 3, '**', '**', ' … ', 40) "
           "FROM chunks WHERE chunks MATCH ?")
    with closing(_connect()) as conn:
        for op in ("AND", "OR"):
            q = _fts_query(query, op)
            if not q:
                return []
            params: list = [q]
            stmt = sql
            if asignatura:
                stmt += " AND asignatura = ?"
                params.append(asignatura)
            rows = conn.execute(stmt + " ORDER BY bm25(chunks) LIMIT ?", (*params, limit)).fetchall()
            if rows:
                return [{"asignatura": r[0], "archivo": r[1], "ubicacion": r[2], "fragmento": r[3]} for r in rows]
    return []


def stats() -> dict[str, int]:
    with closing(_connect()) as conn:
        return dict(conn.execute("SELECT asignatura, count(DISTINCT archivo) FROM chunks GROUP BY asignatura"))
