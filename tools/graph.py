import json
import re

import numpy as np

from embeddings import embed_texts
from llm import chat
from .knowledge import _db as _kb_db
from .registry import tool


class GraphError(Exception):
    pass


EXTRACT_PROMPT = """You are building a knowledge graph from a piece of text.

Reply with ONLY JSON, in exactly this shape:
{
  "entities": [
    {"name": "...", "type": "person|organisation|place|product|concept|event|other",
     "description": "one short sentence"}
  ],
  "relations": [
    {"source": "...", "target": "...", "relation": "short verb phrase",
     "description": "one short sentence"}
  ]
}

Rules:
- Use only facts stated in the text. Never add outside knowledge.
- Write each name in full, and spell it the same way every time.
- Every name used in "relations" must also appear in "entities".
- If the text has nothing useful, return empty lists.

TEXT:
"""


def _db():
    conn = _kb_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS entities (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            key         TEXT NOT NULL UNIQUE,
            name        TEXT NOT NULL,
            type        TEXT NOT NULL,
            description TEXT NOT NULL,
            vector      BLOB
        );
        CREATE TABLE IF NOT EXISTS relations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id   INTEGER NOT NULL,
            target_id   INTEGER NOT NULL,
            relation    TEXT NOT NULL,
            description TEXT NOT NULL,
            chunk_id    INTEGER,
            UNIQUE (source_id, target_id, relation)
        );
        CREATE TABLE IF NOT EXISTS built_chunks (
            chunk_id INTEGER PRIMARY KEY
        );
    """)
    return conn


def _key(name: str) -> str:
    """Same thing written slightly differently should end up as one entity."""
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def _read_json(text: str) -> dict:
    """Models sometimes wrap JSON in code fences. Dig it out."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?|```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    return {"entities": [], "relations": []}


def _save_entity(conn, name, etype, description):
    key = _key(name)
    if not key:
        return None
    row = conn.execute("SELECT id, description FROM entities WHERE key = ?", (key,)).fetchone()
    if row:
        # Same thing seen again — keep the longer description.
        if len(description) > len(row["description"]):
            conn.execute("UPDATE entities SET description = ?, vector = NULL WHERE id = ?",
                         (description, row["id"]))
        return row["id"]
    cur = conn.execute(
        "INSERT INTO entities (key, name, type, description, vector) VALUES (?, ?, ?, ?, NULL)",
        (key, name.strip(), (etype or "other").lower(), description.strip()),
    )
    return cur.lastrowid


def _embed_new_entities(conn):
    rows = conn.execute("SELECT id, name, type, description FROM entities WHERE vector IS NULL").fetchall()
    if not rows:
        return 0
    texts = [f"{r['name']} ({r['type']}): {r['description']}" for r in rows]
    vectors = embed_texts(texts)
    for r, v in zip(rows, vectors):
        conn.execute("UPDATE entities SET vector = ? WHERE id = ?", (v.tobytes(), r["id"]))
    return len(rows)


@tool
def graph_build(limit: int = 40) -> str:
    """Read saved documents and pull out the people, companies, products and
    ideas in them, plus how they connect. Run this after adding documents to
    the knowledge base. It is slow, so it works in batches.

    Args:
        limit: How many document pieces to process this run.
    """
    conn = _db()
    try:
        chunks = conn.execute("""
            SELECT c.id, c.text FROM chunks c
            WHERE c.id NOT IN (SELECT chunk_id FROM built_chunks)
            ORDER BY c.id LIMIT ?
        """, (max(1, min(limit, 200)),)).fetchall()

        if not chunks:
            return "Every saved piece is already in the graph. Nothing new to do."

        new_entities = new_relations = 0

        for chunk in chunks:
            reply = chat(
                [{"role": "user", "content": EXTRACT_PROMPT + chunk["text"]}],
                format="json",
            )
            data = _read_json(reply.get("content", ""))

            ids = {}
            for e in data.get("entities", []):
                if not isinstance(e, dict) or not e.get("name"):
                    continue
                eid = _save_entity(conn, e["name"], e.get("type", "other"), e.get("description", ""))
                if eid:
                    ids[_key(e["name"])] = eid
                    new_entities += 1

            for rel in data.get("relations", []):
                if not isinstance(rel, dict):
                    continue
                s = ids.get(_key(rel.get("source", "")))
                t = ids.get(_key(rel.get("target", "")))
                if not s or not t or s == t:
                    continue
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO relations
                            (source_id, target_id, relation, description, chunk_id)
                        VALUES (?, ?, ?, ?, ?)
                    """, (s, t, (rel.get("relation") or "related to").strip(),
                          (rel.get("description") or "").strip(), chunk["id"]))
                    new_relations += 1
                except Exception:
                    pass

            conn.execute("INSERT OR IGNORE INTO built_chunks (chunk_id) VALUES (?)", (chunk["id"],))
            conn.commit()

        embedded = _embed_new_entities(conn)
        conn.commit()

        left = conn.execute("""
            SELECT COUNT(*) AS n FROM chunks
            WHERE id NOT IN (SELECT chunk_id FROM built_chunks)
        """).fetchone()["n"]

        return (f"Processed {len(chunks)} pieces. "
                f"Found {new_entities} entity mentions and {new_relations} links. "
                f"Indexed {embedded} entities. {left} pieces still waiting.")
    finally:
        conn.close()


@tool
def graph_search(query: str, top_entities: int = 4) -> str:
    """Search the knowledge graph. Use this for questions about how things,
    people or companies are connected, or when the answer needs facts from
    several different documents joined together.

    Args:
        query: The question, written in full.
        top_entities: How many starting points to explore.
    """
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, name, type, description, vector FROM entities WHERE vector IS NOT NULL"
        ).fetchall()
        if not rows:
            raise GraphError("the graph is empty. Run graph_build first.")

        question = embed_texts(query)[0]
        matrix = np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
        scores = matrix @ question
        top_entities = max(1, min(top_entities, 8))
        best = np.argsort(scores)[::-1][:top_entities]

        lines, chunk_ids = [], []

        lines.append("THINGS THAT MATCH THE QUESTION")
        for i in best:
            r = rows[int(i)]
            lines.append(f"- {r['name']} ({r['type']}) — {r['description']}")

        lines.append("\nHOW THEY CONNECT")
        seen = set()
        for i in best:
            eid = rows[int(i)]["id"]
            links = conn.execute("""
                SELECT s.name AS src, t.name AS tgt, r.relation, r.description, r.chunk_id
                FROM relations r
                JOIN entities s ON s.id = r.source_id
                JOIN entities t ON t.id = r.target_id
                WHERE r.source_id = ? OR r.target_id = ?
                LIMIT 15
            """, (eid, eid)).fetchall()

            for l in links:
                line = f"- {l['src']} --[{l['relation']}]--> {l['tgt']}"
                if l["description"]:
                    line += f"   ({l['description']})"
                if line in seen:
                    continue
                seen.add(line)
                lines.append(line)
                if l["chunk_id"]:
                    chunk_ids.append(l["chunk_id"])

        if len(seen) == 0:
            lines.append("(no links recorded for these)")

        if chunk_ids:
            lines.append("\nORIGINAL TEXT THESE FACTS CAME FROM")
            for cid in list(dict.fromkeys(chunk_ids))[:3]:
                row = conn.execute("""
                    SELECT c.text, d.title, d.source FROM chunks c
                    JOIN documents d ON d.id = c.doc_id WHERE c.id = ?
                """, (cid,)).fetchone()
                if row:
                    lines.append(f"[{row['title']} | {row['source']}]\n{row['text'][:700]}")

        return "\n".join(lines)
    finally:
        conn.close()


@tool
def graph_neighbours(name: str) -> str:
    """List everything directly connected to one named thing. Use this when you
    already know the name and want its connections.

    Args:
        name: The name of a person, company, product or idea.
    """
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id, name, type, description FROM entities WHERE key = ? OR name LIKE ? LIMIT 1",
            (_key(name), f"%{name}%"),
        ).fetchone()
        if not row:
            raise GraphError(f"'{name}' is not in the graph. Try graph_search instead.")

        links = conn.execute("""
            SELECT s.name AS src, t.name AS tgt, r.relation, r.description
            FROM relations r
            JOIN entities s ON s.id = r.source_id
            JOIN entities t ON t.id = r.target_id
            WHERE r.source_id = ? OR r.target_id = ?
            LIMIT 40
        """, (row["id"], row["id"])).fetchall()

        head = f"{row['name']} ({row['type']}) — {row['description']}"
        if not links:
            return head + "\n(no connections recorded)"
        body = "\n".join(
            f"- {l['src']} --[{l['relation']}]--> {l['tgt']}"
            + (f"   ({l['description']})" if l["description"] else "")
            for l in links
        )
        return f"{head}\n\n{body}"
    finally:
        conn.close()


@tool
def graph_stats() -> str:
    """Show how big the knowledge graph is and what is still unprocessed."""
    conn = _db()
    try:
        ents = conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]
        rels = conn.execute("SELECT COUNT(*) AS n FROM relations").fetchone()["n"]
        left = conn.execute("""
            SELECT COUNT(*) AS n FROM chunks
            WHERE id NOT IN (SELECT chunk_id FROM built_chunks)
        """).fetchone()["n"]
        types = conn.execute(
            "SELECT type, COUNT(*) AS n FROM entities GROUP BY type ORDER BY n DESC"
        ).fetchall()
        kinds = ", ".join(f"{t['type']}: {t['n']}" for t in types) or "none"
        return (f"{ents} entities, {rels} links.\n"
                f"By type — {kinds}\n"
                f"{left} document pieces not yet processed.")
    finally:
        conn.close()