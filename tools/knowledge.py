import re
import sqlite3
import time

import numpy as np

from config import KB_PATH
from embeddings import embed_texts
from .files import _resolve
from .registry import tool
from .web import page_text

CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
MAX_SOURCE_CHARS = 200_000


class KBError(Exception):
    pass


def _db():
    conn = sqlite3.connect(KB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            title    TEXT NOT NULL,
            source   TEXT NOT NULL UNIQUE,
            added_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id   INTEGER NOT NULL,
            position INTEGER NOT NULL,
            text     TEXT NOT NULL,
            vector   BLOB NOT NULL,
            FOREIGN KEY (doc_id) REFERENCES documents(id)
        );
    """)
    return conn


def _split(text: str):
    """Cut text into pieces of about CHUNK_SIZE characters,
    trying to break at blank lines so sentences stay whole."""
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    pieces, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= CHUNK_SIZE:
            current = f"{current}\n\n{para}" if current else para
            continue
        if current:
            pieces.append(current)
            current = ""
        if len(para) <= CHUNK_SIZE:
            current = para
        else:
            step = CHUNK_SIZE - CHUNK_OVERLAP
            for i in range(0, len(para), step):
                pieces.append(para[i:i + CHUNK_SIZE])
    if current:
        pieces.append(current)
    return pieces


def _store(title: str, source: str, text: str) -> str:
    if not text.strip():
        raise KBError("there was no text to save.")
    text = text[:MAX_SOURCE_CHARS]
    pieces = _split(text)
    vectors = embed_texts(pieces)

    conn = _db()
    try:
        old = conn.execute("SELECT id FROM documents WHERE source = ?", (source,)).fetchone()
        if old:
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (old["id"],))
            conn.execute("DELETE FROM documents WHERE id = ?", (old["id"],))

        cur = conn.execute(
            "INSERT INTO documents (title, source, added_at) VALUES (?, ?, ?)",
            (title, source, time.strftime("%Y-%m-%d %H:%M")),
        )
        doc_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO chunks (doc_id, position, text, vector) VALUES (?, ?, ?, ?)",
            [(doc_id, i, piece, vec.tobytes()) for i, (piece, vec) in enumerate(zip(pieces, vectors))],
        )
        conn.commit()
    finally:
        conn.close()

    action = "Updated" if old else "Saved"
    return f"{action} '{title}' in the knowledge base as {len(pieces)} pieces."


@tool
def kb_add_text(title: str, text: str, source: str = "") -> str:
    """Save some text into the knowledge base so it can be looked up later.

    Args:
        title: A short name for this document.
        text: The full text to save.
        source: Where it came from. Defaults to the title.
    """
    return _store(title, source or f"text:{title}", text)


@tool
def kb_add_file(path: str) -> str:
    """Save a file from the workspace into the knowledge base.

    Args:
        path: File path relative to the workspace root.
    """
    target = _resolve(path)
    if not target.is_file():
        raise KBError(f"no such file: '{path}'.")
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise KBError(f"'{path}' is not a text file.")
    return _store(target.name, f"file:{path}", text)


@tool
def kb_add_url(url: str) -> str:
    """Read a web page and save the whole thing into the knowledge base.
    Use this instead of fetch_url when the page is long or will be needed again.

    Args:
        url: The full web address, starting with https://
    """
    title, text = page_text(url, max_chars=MAX_SOURCE_CHARS)
    return _store(title, url, text)


@tool
def kb_search(query: str, top_k: int = 5) -> str:
    """Search saved documents by meaning and get back the most relevant pieces.
    Use this BEFORE searching the web, in case we already know the answer.

    Args:
        query: What you want to know, written as a full question.
        top_k: How many pieces to return.
    """
    conn = _db()
    try:
        rows = conn.execute("""
            SELECT c.text, c.vector, d.title, d.source
            FROM chunks c JOIN documents d ON d.id = c.doc_id
        """).fetchall()
    finally:
        conn.close()

    if not rows:
        raise KBError("the knowledge base is empty. Add something with kb_add_url or kb_add_file first.")

    question = embed_texts(query)[0]
    matrix = np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
    scores = matrix @ question                      # both are length 1, so this is similarity

    top_k = max(1, min(top_k, 10))
    best = np.argsort(scores)[::-1][:top_k]

    out = []
    for rank, i in enumerate(best, 1):
        row = rows[int(i)]
        out.append(
            f"[{rank}] score {scores[i]:.3f} | {row['title']} | {row['source']}\n"
            f"{row['text']}"
        )
    return "\n\n".join(out)


@tool
def kb_list() -> str:
    """List every document currently in the knowledge base."""
    conn = _db()
    try:
        rows = conn.execute("""
            SELECT d.id, d.title, d.source, d.added_at, COUNT(c.id) AS pieces
            FROM documents d LEFT JOIN chunks c ON c.doc_id = d.id
            GROUP BY d.id ORDER BY d.id
        """).fetchall()
    finally:
        conn.close()
    if not rows:
        return "(the knowledge base is empty)"
    return "\n".join(
        f"{r['id']}. {r['title']}  [{r['pieces']} pieces]  {r['source']}  ({r['added_at']})"
        for r in rows
    )
