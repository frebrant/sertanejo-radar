"""SQLite: schema + CRUD para matérias coletadas."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "radar.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_hash TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  url TEXT NOT NULL,
  source TEXT NOT NULL,
  source_type TEXT NOT NULL,
  published_at TIMESTAMP NOT NULL,
  fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  artist_hits TEXT,
  source_count INTEGER DEFAULT 1,
  sources_list TEXT,
  score REAL DEFAULT 0,
  notified INTEGER DEFAULT 0,
  copy_titles TEXT,
  copy_caption TEXT,
  copy_source TEXT
);
CREATE INDEX IF NOT EXISTS idx_score_pub ON news(score DESC, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_published ON news(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_hash ON news(canonical_hash);
"""

# ALTER TABLE seguro para bancos antigos que ainda não têm as colunas de copy
MIGRATIONS = [
    "ALTER TABLE news ADD COLUMN copy_titles TEXT",
    "ALTER TABLE news ADD COLUMN copy_caption TEXT",
    "ALTER TABLE news ADD COLUMN copy_source TEXT",
]


def get_conn(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # roda migrations idempotentes (cada ALTER falha silenciosamente se a coluna já existe)
    for stmt in MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # coluna já existe
    conn.commit()


def fetch_recent_titles(conn: sqlite3.Connection, hours: int = 48) -> list[sqlite3.Row]:
    """Retorna matérias das últimas N horas para deduplicação fuzzy."""
    cur = conn.execute(
        """
        SELECT id, canonical_hash, title, sources_list, source_count
        FROM news
        WHERE published_at >= datetime('now', ?)
        """,
        (f"-{hours} hours",),
    )
    return cur.fetchall()


def upsert_news(conn: sqlite3.Connection, item: dict[str, Any]) -> tuple[str, int | None]:
    """Insere matéria nova OU atualiza uma existente (dedup).

    Retorna ('inserted'|'updated'|'skipped', news_id).
    A lógica de dedup espera que `item['canonical_hash']` JÁ tenha sido decidido
    pelo módulo `dedup.py` — se o hash bate com algo existente, faz UPDATE
    incrementando source_count e adicionando à sources_list.
    """
    existing = conn.execute(
        "SELECT id, source_count, sources_list FROM news WHERE canonical_hash = ?",
        (item["canonical_hash"],),
    ).fetchone()

    if existing is None:
        sources_list = json.dumps([item["source"]])
        artist_hits = json.dumps(item.get("artist_hits", []))
        cur = conn.execute(
            """
            INSERT INTO news (
                canonical_hash, title, summary, url, source, source_type,
                published_at, artist_hits, source_count, sources_list, score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 0)
            """,
            (
                item["canonical_hash"],
                item["title"],
                item.get("summary", ""),
                item["url"],
                item["source"],
                item["source_type"],
                item["published_at"],
                artist_hits,
                sources_list,
            ),
        )
        conn.commit()
        return ("inserted", cur.lastrowid)

    # Existe: se a fonte já está na sources_list, é re-fetch, pula
    sources = json.loads(existing["sources_list"] or "[]")
    if item["source"] in sources:
        return ("skipped", existing["id"])

    sources.append(item["source"])
    conn.execute(
        """
        UPDATE news
        SET source_count = ?, sources_list = ?
        WHERE id = ?
        """,
        (len(sources), json.dumps(sources), existing["id"]),
    )
    conn.commit()
    return ("updated", existing["id"])


def update_score(conn: sqlite3.Connection, news_id: int, score: float) -> None:
    conn.execute("UPDATE news SET score = ? WHERE id = ?", (score, news_id))
    conn.commit()


def update_copy(
    conn: sqlite3.Connection,
    news_id: int,
    titles: list[str],
    caption: str,
    source: str,
) -> None:
    conn.execute(
        "UPDATE news SET copy_titles = ?, copy_caption = ?, copy_source = ? WHERE id = ?",
        (json.dumps(titles, ensure_ascii=False), caption, source, news_id),
    )
    conn.commit()


def fetch_news_needing_copy(
    conn: sqlite3.Connection,
    threshold: float = 0.6,
    limit: int = 20,
) -> list[sqlite3.Row]:
    """Matérias com score alto que ainda não têm copy gerada (ou tem fallback)."""
    cur = conn.execute(
        """
        SELECT id, title, summary, artist_hits, score
        FROM news
        WHERE score >= ?
          AND (copy_titles IS NULL OR copy_source = 'fallback')
          AND published_at >= datetime('now', '-48 hours')
        ORDER BY score DESC, published_at DESC
        LIMIT ?
        """,
        (threshold, limit),
    )
    return cur.fetchall()


def fetch_pending_notifications(conn: sqlite3.Connection, threshold: float = 0.75) -> list[sqlite3.Row]:
    """Matérias com score alto que ainda não foram notificadas."""
    cur = conn.execute(
        """
        SELECT id, title, url, source, sources_list, source_count, score, published_at,
               copy_titles, copy_caption, copy_source
        FROM news
        WHERE score >= ? AND notified = 0
        ORDER BY score DESC, published_at DESC
        LIMIT 10
        """,
        (threshold,),
    )
    return cur.fetchall()


def mark_notified(conn: sqlite3.Connection, news_ids: Iterable[int]) -> None:
    ids = list(news_ids)
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"UPDATE news SET notified = 1 WHERE id IN ({placeholders})", ids)
    conn.commit()


def fetch_top_news(
    conn: sqlite3.Connection,
    hours: int = 48,
    limit: int = 30,
    artist_filter: str | None = None,
    source_type_filter: str | None = None,
) -> list[sqlite3.Row]:
    """Para o dashboard: top matérias rankeadas."""
    where_clauses = ["published_at >= datetime('now', ?)"]
    params: list[Any] = [f"-{hours} hours"]

    if source_type_filter:
        where_clauses.append("source_type = ?")
        params.append(source_type_filter)

    if artist_filter:
        where_clauses.append("artist_hits LIKE ?")
        params.append(f"%{artist_filter}%")

    where = " AND ".join(where_clauses)
    sql = f"""
        SELECT id, title, summary, url, source, source_type, sources_list,
               source_count, score, published_at, artist_hits, notified,
               copy_titles, copy_caption, copy_source
        FROM news
        WHERE {where}
        ORDER BY score DESC, published_at DESC
        LIMIT ?
    """
    params.append(limit)
    cur = conn.execute(sql, params)
    return cur.fetchall()


def cleanup_old(conn: sqlite3.Connection, days: int = 14) -> int:
    """Apaga matérias mais velhas que N dias (mantém SQLite enxuto)."""
    cur = conn.execute(
        "DELETE FROM news WHERE published_at < datetime('now', ?)",
        (f"-{days} days",),
    )
    conn.commit()
    return cur.rowcount
