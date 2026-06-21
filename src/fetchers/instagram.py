"""Fetcher de Instagram via RSSHub (perfis públicos, sem login).

Estratégia idêntica ao twitter.py: tenta cada instância RSSHub em ordem,
primeira que devolve feed válido vence. Sem login = zero risco de banir
sua conta pessoal do Instagram.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import requests

log = logging.getLogger(__name__)

MAX_ITEMS_PER_PROFILE = 10
MAX_AGE_DAYS = 3
REQUEST_TIMEOUT = 12


def _try_fetch(url: str) -> str | None:
    try:
        r = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "SertanejoRadar/0.1 (RSS reader)"},
        )
        if r.status_code == 200 and len(r.content) > 200:
            return r.text
    except requests.RequestException as exc:
        log.debug("Falha em %s: %s", url, exc)
    return None


def _parse_rss(text: str, username: str) -> list[dict[str, Any]]:
    parsed = feedparser.parse(text)
    if not parsed.entries:
        return []

    cutoff = datetime.now(timezone.utc).timestamp() - (MAX_AGE_DAYS * 86400)
    items: list[dict[str, Any]] = []

    for entry in parsed.entries[:MAX_ITEMS_PER_PROFILE]:
        published: datetime | None = None
        for attr in ("published", "updated"):
            raw = entry.get(attr)
            if raw:
                try:
                    dt = parsedate_to_datetime(raw)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    published = dt
                    break
                except (TypeError, ValueError):
                    pass
        if not published:
            parsed_t = entry.get("published_parsed") or entry.get("updated_parsed")
            if parsed_t:
                try:
                    published = datetime(*parsed_t[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    pass
        if not published or published.timestamp() < cutoff:
            continue

        # No Instagram, RSSHub usa a legenda do post como title (geralmente)
        title = (entry.get("title") or "").strip()
        summary = (entry.get("summary") or "").strip()
        if not title and not summary:
            continue
        if not title:
            # alguns retornos vêm sem title — usa início da legenda
            title = summary[:120]

        items.append({
            "title": title[:200],
            "summary": summary[:500],
            "url": entry.get("link") or "",
            "source": f"@{username} (IG)",
            "source_type": "instagram",
            "published_at": published.strftime("%Y-%m-%d %H:%M:%S"),
        })
    return items


def fetch_profile(username: str, rsshub_instances: list[str]) -> list[dict[str, Any]]:
    for inst in rsshub_instances:
        url = f"{inst.rstrip('/')}/instagram/user/{username}"
        body = _try_fetch(url)
        if body:
            items = _parse_rss(body, username)
            if items:
                log.info("Instagram @%s: %d itens via %s", username, len(items), inst)
                return items
        time.sleep(0.3)
    log.warning("Instagram @%s: nenhuma instância funcionou", username)
    return []


def fetch_all(config: dict[str, Any]) -> list[dict[str, Any]]:
    rsshub = config.get("instancias_rsshub", [])
    perfis = config.get("perfis", [])
    out: list[dict[str, Any]] = []
    for username in perfis:
        out.extend(fetch_profile(username, rsshub))
    return out
