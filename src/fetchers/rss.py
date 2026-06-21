"""Fetcher de feeds RSS dos portais.

Para cada fonte em sources.yaml, busca o feed via feedparser e normaliza
os itens em dicts {title, summary, url, source, source_type, published_at}.

Falha em uma fonte NÃO derruba o pipeline — só loga e segue.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import requests

log = logging.getLogger(__name__)

# Limita itens por feed para não inflar com matéria antiga
MAX_ITEMS_PER_FEED = 30
# Só aceita matérias dos últimos N dias (frescor é requisito do usuário)
MAX_AGE_DAYS = 4
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; SertanejoRadar/0.1; +https://github.com/)"


def _parse_date(entry: Any) -> datetime | None:
    """Extrai data de publicação tentando vários formatos do feedparser."""
    for attr in ("published", "updated", "created"):
        raw = entry.get(attr)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (TypeError, ValueError):
            pass

    # fallback: usa _parsed se feedparser conseguiu
    for attr in ("published_parsed", "updated_parsed"):
        parsed = entry.get(attr)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    return None


def _parse_lenient(raw: bytes):
    """Parse feedparser permissivo: tenta limpar XML mal formado se a 1ª passada falhar."""
    parsed = feedparser.parse(raw)
    if parsed.entries:
        return parsed

    # tentativa 2: remove caracteres de controle inválidos (causa frequente do
    # 'not well-formed (invalid token)' em feeds brasileiros)
    try:
        text = raw.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        text = raw.decode("latin-1", errors="ignore")
    cleaned = "".join(
        ch for ch in text
        if ch == "\n" or ch == "\t" or ch == "\r" or 0x20 <= ord(ch) <= 0xD7FF or 0xE000 <= ord(ch) <= 0xFFFD
    )
    return feedparser.parse(cleaned)


def _http_get(url: str) -> bytes | None:
    """Baixa a URL com requests (lida bem com SSL/redirects/UA) e devolve bytes."""
    try:
        r = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            },
            allow_redirects=True,
        )
        if r.status_code == 200 and r.content:
            return r.content
        log.debug("HTTP %d em %s", r.status_code, url)
    except requests.RequestException as exc:
        log.debug("HTTP erro em %s: %s", url, exc)
    return None


def fetch_feed(url: str, source_name: str, source_type: str) -> list[dict[str, Any]]:
    """Busca um feed RSS e devolve lista de items normalizados.

    Estratégia: baixa via requests (resolve SSL/UA/redirects), depois entrega
    bytes para o feedparser parsear. Tolera bozo=1 desde que haja entries.
    """
    items: list[dict[str, Any]] = []
    cutoff = datetime.now(timezone.utc).timestamp() - (MAX_AGE_DAYS * 86400)

    raw = _http_get(url)
    if raw is None:
        log.warning("Não foi possível baixar %s (%s)", source_name, url)
        return items

    parsed = _parse_lenient(raw)
    if not parsed.entries:
        log.warning("Sem entries em %s: %s", source_name, getattr(parsed, "bozo_exception", "?"))
        return items

    for entry in parsed.entries[:MAX_ITEMS_PER_FEED]:
        published = _parse_date(entry)
        if not published:
            continue
        if published.timestamp() < cutoff:
            continue  # muito antiga

        title = (entry.get("title") or "").strip()
        if not title:
            continue

        items.append({
            "title": title,
            "summary": (entry.get("summary") or entry.get("description") or "").strip()[:500],
            "url": entry.get("link") or url,
            "source": source_name,
            "source_type": source_type,
            "published_at": published.strftime("%Y-%m-%d %H:%M:%S"),
        })

    log.info("RSS %s: %d itens (de %d no feed)", source_name, len(items), len(parsed.entries))
    return items


def fetch_all(portais: list[dict], sertanejo: list[dict]) -> list[dict[str, Any]]:
    """Busca todos os feeds (portais + sertanejo) e devolve lista plana."""
    out: list[dict[str, Any]] = []
    for fonte in portais:
        out.extend(fetch_feed(fonte["url"], fonte["nome"], "portal"))
    for fonte in sertanejo:
        out.extend(fetch_feed(fonte["url"], fonte["nome"], "sertanejo"))
    return out
