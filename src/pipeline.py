"""Orquestrador: fetch (todas as fontes) → dedup → score → persiste → notifica."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from .ai_copy import GeminiRateLimiter, generate_copy
from .db import (
    fetch_news_needing_copy,
    fetch_pending_notifications,
    fetch_recent_titles,
    get_conn,
    init_schema,
    mark_notified,
    update_copy,
    update_score,
    upsert_news,
)
from .dedup import canonical_hash, find_artist_hits, find_similar
from .fetchers import instagram as f_instagram
from .fetchers import rss as f_rss
from .fetchers import twitter as f_twitter
from .notify import notify_rows
from .scoring import score_news

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
NOTIFY_THRESHOLD = 0.75
COPY_THRESHOLD = 0.6        # gera copy IA acima deste score
COPY_MAX_PER_RUN = 15       # limite por execução (margem dos 1.500/dia da Gemini)


@dataclass
class PipelineStats:
    portais_items: int = 0
    twitter_items: int = 0
    instagram_items: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    notified: int = 0
    copies_gemini: int = 0
    copies_fallback: int = 0

    def __str__(self) -> str:
        return (
            f"Portais/Sertanejo: {self.portais_items} | "
            f"Twitter: {self.twitter_items} | "
            f"Instagram: {self.instagram_items} | "
            f"Inseridas: {self.inserted} | "
            f"Atualizadas (multi-fonte): {self.updated} | "
            f"Puladas (já existia): {self.skipped} | "
            f"Copy IA: {self.copies_gemini} (+{self.copies_fallback} fallback) | "
            f"Notificadas: {self.notified}"
        )


def load_config() -> tuple[dict, dict]:
    sources = yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text(encoding="utf-8"))
    artistas_doc = yaml.safe_load((CONFIG_DIR / "artistas.yaml").read_text(encoding="utf-8"))
    # Suporta novo formato com tiers OU formato antigo (lista plana)
    if isinstance(artistas_doc, dict):
        if "tier_1" in artistas_doc or "tier_2" in artistas_doc or "tier_3" in artistas_doc:
            artistas = {
                "tier_1": artistas_doc.get("tier_1", []) or [],
                "tier_2": artistas_doc.get("tier_2", []) or [],
                "tier_3": artistas_doc.get("tier_3", []) or [],
            }
        else:
            # compat retroativa: lista plana vira tier_1
            artistas = {"tier_1": artistas_doc.get("artistas", []) or [], "tier_2": [], "tier_3": []}
    else:
        artistas = {"tier_1": [], "tier_2": [], "tier_3": []}
    return sources, artistas


def run() -> PipelineStats:
    stats = PipelineStats()

    sources, artistas = load_config()

    # 1) FETCH — cada fonte é tolerante a falha
    log.info("→ Buscando RSS de portais...")
    portais_items = f_rss.fetch_all(sources.get("portais", []), sources.get("sertanejo", []))
    stats.portais_items = len(portais_items)

    log.info("→ Buscando Twitter (Nitter/RSSHub)...")
    twitter_items: list[dict] = []
    if sources.get("twitter"):
        twitter_items = f_twitter.fetch_all(sources["twitter"])
    stats.twitter_items = len(twitter_items)

    log.info("→ Buscando Instagram (RSSHub)...")
    instagram_items: list[dict] = []
    if sources.get("instagram"):
        instagram_items = f_instagram.fetch_all(sources["instagram"])
    stats.instagram_items = len(instagram_items)

    all_items = portais_items + twitter_items + instagram_items
    log.info("Total bruto coletado: %d items", len(all_items))

    # 2) DEDUP + UPSERT
    conn = get_conn()
    init_schema(conn)
    recent = fetch_recent_titles(conn, hours=48)

    # mantém em memória os hashes/títulos já vistos NESTA execução (evita dedup só com DB)
    seen_this_run: dict[str, str] = {row["canonical_hash"]: row["title"] for row in recent}

    touched_ids: list[int] = []

    for item in all_items:
        title = item["title"]
        # decide hash: tenta fuzzy contra o conjunto "recent + já vistos nesta run"
        # find_similar precisa de Rows com keys canonical_hash/title; vamos montar uma lista compatível
        recent_for_match = [
            {"canonical_hash": h, "title": t} for h, t in seen_this_run.items()
        ]
        # rapidfuzz aceita dict desde que find_similar use índice de chave — adapto função:
        # como find_similar usa row["canonical_hash"], passamos um objeto com __getitem__
        similar_hash = find_similar(title, recent_for_match)  # noqa: type
        item["canonical_hash"] = similar_hash if similar_hash else canonical_hash(title)
        item["artist_hits"] = find_artist_hits(title, item.get("summary", ""), artistas)

        # registra para próximo item desta run (evita duplicatas dentro do mesmo batch)
        seen_this_run.setdefault(item["canonical_hash"], title)

        status, news_id = upsert_news(conn, item)
        if status == "inserted":
            stats.inserted += 1
        elif status == "updated":
            stats.updated += 1
        else:
            stats.skipped += 1
        if news_id:
            touched_ids.append(news_id)

    # 3) SCORE — recalcula score para tudo que foi tocado (insert OR update)
    touched_ids_unique = list(dict.fromkeys(touched_ids))
    if touched_ids_unique:
        placeholders = ",".join("?" * len(touched_ids_unique))
        rows = conn.execute(
            f"""
            SELECT id, published_at, source_count, artist_hits, source
            FROM news WHERE id IN ({placeholders})
            """,
            touched_ids_unique,
        ).fetchall()
        for row in rows:
            try:
                hits = json.loads(row["artist_hits"] or "[]")
            except (json.JSONDecodeError, TypeError):
                hits = []
            s = score_news(
                row["published_at"],
                row["source_count"],
                hits,
                row["source"],
            )
            update_score(conn, row["id"], s)

    # 4) GERAR COPY IA — só pra matérias com score alto que ainda não têm
    pending_copy = fetch_news_needing_copy(conn, threshold=COPY_THRESHOLD, limit=COPY_MAX_PER_RUN)
    if pending_copy:
        log.info("→ Gerando copy IA para %d matérias (score >= %.2f)",
                 len(pending_copy), COPY_THRESHOLD)
        limiter = GeminiRateLimiter(max_per_min=8)
        for row in pending_copy:
            try:
                hits_raw = json.loads(row["artist_hits"] or "[]")
            except (json.JSONDecodeError, TypeError):
                hits_raw = []
            nomes = [h["nome"] if isinstance(h, dict) else str(h) for h in hits_raw]
            limiter.wait_if_needed()
            copy = generate_copy(row["title"], row["summary"] or "", nomes)
            update_copy(conn, row["id"], copy["titulos"], copy["legenda"], copy["source"])
            if copy["source"] == "gemini":
                stats.copies_gemini += 1
            else:
                stats.copies_fallback += 1

    # 5) NOTIFICAR — só matérias com score alto que ainda não foram notificadas
    pending = fetch_pending_notifications(conn, threshold=NOTIFY_THRESHOLD)
    if pending:
        log.info("→ Enviando %d notificações (score >= %.2f)", len(pending), NOTIFY_THRESHOLD)
        sent_ids = notify_rows(pending)
        mark_notified(conn, sent_ids)
        stats.notified = len(sent_ids)

    conn.close()
    log.info("Pipeline finalizado: %s", stats)
    return stats
