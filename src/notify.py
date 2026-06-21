"""Notificação Telegram via API HTTP (sem dependência pesada)."""
from __future__ import annotations

import json
import logging
import os
from typing import Iterable

import requests

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_TITLE_LEN = 130


def _escape_md(text: str) -> str:
    """Escape leve para MarkdownV1 do Telegram (formato antigo, mais permissivo)."""
    # Telegram parse_mode='Markdown' (v1): escapa *, _, ` e [
    out = []
    for ch in text:
        if ch in "*_`[":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _format_message(row) -> str:
    title = row["title"][:MAX_TITLE_LEN]
    if len(row["title"]) > MAX_TITLE_LEN:
        title += "…"

    score = float(row["score"])
    sources = []
    try:
        sources = json.loads(row["sources_list"] or "[]")
    except (json.JSONDecodeError, TypeError):
        sources = [row["source"]]

    fontes_str = ", ".join(sources[:5])
    if len(sources) > 5:
        fontes_str += f" +{len(sources) - 5}"

    fire = "🔥🔥🔥" if score >= 0.9 else ("🔥🔥" if score >= 0.8 else "🔥")

    lines = [
        f"{fire} *Score {score:.2f}* — {_escape_md(title)}",
        f"Fontes ({row['source_count']}): {_escape_md(fontes_str)}",
        f"📰 {row['url']}",
    ]

    # Inclui copy se disponível (e veio do Gemini, fallback fica fora)
    copy_titles_raw = _safe_get(row, "copy_titles")
    copy_caption = _safe_get(row, "copy_caption")
    copy_source = _safe_get(row, "copy_source") or ""
    if copy_titles_raw and copy_source == "gemini":
        try:
            titulos = json.loads(copy_titles_raw)
            if titulos:
                lines.append("")
                lines.append("✍️ *Copy pronto:*")
                for i, t in enumerate(titulos[:3], 1):
                    lines.append(f"{i}\\. {_escape_md(str(t))}")
                if copy_caption:
                    lines.append(f"📝 {_escape_md(copy_caption)}")
        except (json.JSONDecodeError, TypeError):
            pass

    return "\n".join(lines)


def _safe_get(row, key, default=None):
    """sqlite3.Row.get() não existe — emulamos."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def send_message(text: str, token: str | None = None, chat_id: str | None = None) -> bool:
    """Envia uma mensagem ao Telegram. Retorna True se ok."""
    token = token or os.environ.get("TELEGRAM_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.warning("Telegram não configurado (TELEGRAM_TOKEN/TELEGRAM_CHAT_ID ausente)")
        return False

    try:
        r = requests.post(
            TELEGRAM_API.format(token=token),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
        if r.status_code == 200:
            return True
        log.warning("Telegram %d: %s", r.status_code, r.text[:200])
    except requests.RequestException as exc:
        log.warning("Telegram falhou: %s", exc)
    return False


def notify_rows(rows: Iterable, token: str | None = None, chat_id: str | None = None) -> list[int]:
    """Envia uma mensagem por matéria. Retorna lista de IDs que foram notificados."""
    sent_ids: list[int] = []
    for row in rows:
        msg = _format_message(row)
        if send_message(msg, token, chat_id):
            sent_ids.append(row["id"])
    return sent_ids
