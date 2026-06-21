"""Fetcher de Twitter/X via Nitter ou RSSHub (com fallback).

Estratégia:
  1. Tenta instâncias Nitter em ordem ({inst}/{handle}/rss)
  2. Se todas falharem, tenta RSSHub ({inst}/twitter/user/{handle})
  3. Primeira que devolve 200 + tem entradas vence
  4. Cache local da instância "que funcionou hoje" para acelerar próxima execução

Não usa API oficial paga do X — só leitura pública via espelhos.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import feedparser
import requests

log = logging.getLogger(__name__)

MAX_ITEMS_PER_PROFILE = 15
MAX_AGE_DAYS = 3
REQUEST_TIMEOUT = 12  # segundos

# Cache simples em arquivo: { "nitter": "https://...funciona", "rsshub": "https://..." }
CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "_instance_cache.json"


def _load_cache() -> dict[str, str]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict[str, str]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
    except OSError as exc:
        log.debug("Não foi possível salvar cache de instância: %s", exc)


def _try_fetch(url: str) -> str | None:
    """Tenta baixar a URL; devolve body se 200 + content > 200 bytes, senão None."""
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


def _ordered_instances(provider: str, configured: list[str]) -> list[str]:
    """Coloca a instância cacheada (última que funcionou) na frente da lista."""
    cache = _load_cache()
    cached = cache.get(provider)
    if cached and cached in configured:
        return [cached] + [x for x in configured if x != cached]
    return list(configured)


def _parse_rss(text: str, handle: str, tag: str) -> list[dict[str, Any]]:
    """Parseia feed RSS (Nitter ou RSSHub) em items normalizados."""
    parsed = feedparser.parse(text)
    if not parsed.entries:
        return []

    cutoff = datetime.now(timezone.utc).timestamp() - (MAX_AGE_DAYS * 86400)
    items: list[dict[str, Any]] = []

    for entry in parsed.entries[:MAX_ITEMS_PER_PROFILE]:
        # data
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

        # título: Nitter usa o texto do tweet como title
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        # tweet costuma vir com "R to @x:" — corta o prefixo retweet pra limpar
        if title.startswith("R to @") or title.startswith("RT @"):
            continue

        items.append({
            "title": title,
            "summary": (entry.get("summary") or "").strip()[:500],
            "url": entry.get("link") or "",
            "source": f"@{handle}",        # ex: @choquei
            "source_type": "twitter",
            "published_at": published.strftime("%Y-%m-%d %H:%M:%S"),
            "_handle": handle,
            "_tag": tag,
        })
    return items


def fetch_profile(
    handle: str,
    tag: str,
    nitter_instances: list[str],
    rsshub_instances: list[str],
) -> list[dict[str, Any]]:
    """Tenta Nitter → RSSHub; primeira que funciona vence."""
    # 1) Nitter
    for inst in _ordered_instances("nitter", nitter_instances):
        url = f"{inst.rstrip('/')}/{handle}/rss"
        body = _try_fetch(url)
        if body:
            items = _parse_rss(body, handle, tag)
            if items:
                cache = _load_cache()
                cache["nitter"] = inst
                _save_cache(cache)
                log.info("Twitter @%s: %d itens via Nitter %s", handle, len(items), inst)
                return items
        time.sleep(0.3)  # delicadeza com instâncias públicas

    # 2) RSSHub
    for inst in _ordered_instances("rsshub", rsshub_instances):
        url = f"{inst.rstrip('/')}/twitter/user/{handle}"
        body = _try_fetch(url)
        if body:
            items = _parse_rss(body, handle, tag)
            if items:
                cache = _load_cache()
                cache["rsshub"] = inst
                _save_cache(cache)
                log.info("Twitter @%s: %d itens via RSSHub %s", handle, len(items), inst)
                return items
        time.sleep(0.3)

    log.warning("Twitter @%s: nenhuma instância funcionou", handle)
    return []


def fetch_all(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Busca todos os perfis configurados em sources.yaml -> twitter."""
    nitter = config.get("instancias_nitter", [])
    rsshub = config.get("instancias_rsshub", [])
    perfis = config.get("perfis", [])
    out: list[dict[str, Any]] = []
    for perfil in perfis:
        out.extend(fetch_profile(perfil["handle"], perfil.get("tag", ""), nitter, rsshub))
    return out
