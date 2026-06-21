"""Geração de copy para Instagram via Gemini Flash (free tier).

Para cada matéria com score alto, gera:
  - 3 sugestões de título curto (max 65 chars, com emoji, tom de fofoca)
  - 1 legenda de Instagram (max 220 chars, com hashtags)

Limites do free tier (Gemini 2.5/3 Flash, jun/2026):
  - 10 requests/min
  - 1.500 requests/dia
Mais que suficiente para ~100 matérias prioritárias por dia.

Se GEMINI_API_KEY não estiver setada OU API falhar, retorna fallback estático.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/{model}:generateContent"
)
REQUEST_TIMEOUT = 20

PROMPT_TEMPLATE = """Você é um social media de uma página de fofocas e notícias do sertanejo brasileiro com foco em Instagram.

A matéria abaixo está bombando. Gere conteúdo pronto pra postar.

TÍTULO DA MATÉRIA: {title}

RESUMO: {summary}

ARTISTAS CITADOS: {artistas}

Gere a resposta em JSON puro (sem markdown, sem ```), com esta estrutura EXATA:
{{
  "titulos": [
    "primeiro título com emoji (máx 65 chars)",
    "segundo título alternativo (máx 65 chars)",
    "terceiro título alternativo (máx 65 chars)"
  ],
  "legenda": "legenda completa pra Instagram com tom de fofoca, sem ser sensacionalista demais, com 3-5 hashtags no final relacionadas (#sertanejo #virginiafonseca etc). Máximo 220 chars total."
}}

REGRAS:
- Use português brasileiro, tom informal, expressões de fofoca ("será que...", "olha só...", "ó o babado").
- 1 emoji por título no máximo (no início ou meio).
- Não use aspas dentro dos textos (quebra o JSON).
- Hashtags só no fim da legenda.
- NÃO inclua nada além do JSON puro."""


_FALLBACK_HASHTAGS = "#sertanejo #fofoca #famosos"


def _fallback_copy(title: str, artistas: list[str] | None = None) -> dict:
    """Copy básico estático quando a API falha — pra nunca deixar a matéria sem copy."""
    clean = title.strip()
    short = clean[:62] + "..." if len(clean) > 65 else clean
    hashtags = _FALLBACK_HASHTAGS
    if artistas:
        for a in artistas[:2]:
            tag = re.sub(r"\W+", "", a.lower())
            if tag and len(tag) > 3:
                hashtags += f" #{tag}"
    return {
        "titulos": [
            f"🚨 {short}",
            f"Olha o que rolou: {short[:50]}",
            f"Bombou! {short[:55]}",
        ],
        "legenda": f"{clean[:180]}{'...' if len(clean) > 180 else ''} {hashtags}",
        "source": "fallback",
    }


def _strip_md_fences(text: str) -> str:
    """Remove ```json … ``` se o modelo teimar em incluir mesmo a gente pedindo pra não."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def generate_copy(
    title: str,
    summary: str = "",
    artistas: list[str] | None = None,
    api_key: str | None = None,
) -> dict:
    """Chama Gemini Flash e devolve dict {titulos: [...], legenda: ...}.

    Sempre devolve algo — usa fallback se a API falhar.
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log.debug("GEMINI_API_KEY ausente — usando fallback")
        return _fallback_copy(title, artistas)

    artistas_str = ", ".join(artistas) if artistas else "nenhum específico"
    prompt = PROMPT_TEMPLATE.format(
        title=title, summary=summary[:300], artistas=artistas_str
    )

    url = GEMINI_URL.format(model=GEMINI_MODEL)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.9,
            # Gemini 2.5 Flash gasta ~500 tokens em "thinking" antes de responder.
            # Precisamos margem suficiente para thinking + 200-300 tokens de output JSON.
            "maxOutputTokens": 1500,
            "responseMimeType": "application/json",
            # thinkingBudget=0 desliga o thinking mode (tarefa simples não precisa)
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    # Retry para 503 (modelo sobrecarregado) — espera curta entre tentativas
    r = None
    for attempt in range(3):
        try:
            r = requests.post(
                url,
                params={"key": api_key},
                json=body,
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code != 503:
                break
            log.info("Gemini 503 (tentativa %d/3), aguardando...", attempt + 1)
            time.sleep(2 + attempt * 2)
        except requests.RequestException as exc:
            log.warning("Gemini request falhou: %s", exc)
            return _fallback_copy(title, artistas)
    if r is None:
        return _fallback_copy(title, artistas)

    try:
        if r.status_code != 200:
            log.warning("Gemini %d: %s", r.status_code, r.text[:200])
            return _fallback_copy(title, artistas)

        data = r.json()
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        if not text:
            log.warning("Gemini devolveu resposta vazia")
            return _fallback_copy(title, artistas)

        text = _strip_md_fences(text)
        parsed = json.loads(text)
        if not isinstance(parsed, dict) or "titulos" not in parsed:
            log.warning("Gemini devolveu JSON inesperado: %s", text[:200])
            return _fallback_copy(title, artistas)

        # validações leves
        titulos = parsed.get("titulos") or []
        if not isinstance(titulos, list) or len(titulos) < 1:
            return _fallback_copy(title, artistas)
        legenda = str(parsed.get("legenda") or "").strip()
        if not legenda:
            legenda = _fallback_copy(title, artistas)["legenda"]

        return {
            "titulos": [str(t).strip()[:120] for t in titulos[:3]],
            "legenda": legenda[:400],
            "source": "gemini",
        }
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        log.warning("Gemini parse falhou: %s", exc)
        return _fallback_copy(title, artistas)


# ---------- Rate limit helper ----------
class GeminiRateLimiter:
    """Garante até MAX_PER_MIN chamadas/minuto. Útil quando pipeline gera copy
    pra muitas matérias seguidas."""

    def __init__(self, max_per_min: int = 8):  # 10 é o limite, deixamos margem
        self.max_per_min = max_per_min
        self.timestamps: list[float] = []

    def wait_if_needed(self) -> None:
        now = time.time()
        # remove timestamps fora da janela de 60s
        self.timestamps = [t for t in self.timestamps if now - t < 60]
        if len(self.timestamps) >= self.max_per_min:
            sleep_for = 60 - (now - self.timestamps[0]) + 0.5
            if sleep_for > 0:
                log.info("Rate limit Gemini: aguardando %.1fs", sleep_for)
                time.sleep(sleep_for)
                # remove o mais antigo após o sleep
                self.timestamps = self.timestamps[1:]
        self.timestamps.append(time.time())


# ============================================================================
# Classificador de conteúdo (filtro 2ª camada)
# ============================================================================

CLASSIFY_PROMPT = """Você está ajudando a curar matérias para uma página de fofocas SERTANEJO no Instagram.

A página NÃO POSTA:
- Notícias negativas (críticas, polêmicas, processos, cancelamentos, acusações sérias)
- Divulgações de música (lançamento de single/EP/álbum, bastidores de gravação)

A página POSTA (NÃO bloquear):
- Tretas, brigas, separações, romances entre artistas (fofoca pura)
- Críticas leves / comentários de internautas
- Anúncios de show / turnê
- Clipes e parcerias
- Curiosidades, declarações, viagens, vida pessoal

MATÉRIA:
Título: {title}
Resumo: {summary}

Responda em JSON puro (sem markdown):
{{"block": true/false, "reason": "razão curta em 5 palavras"}}

Use block=true APENAS se for claramente negativa OU divulgação de música.
Na dúvida, use block=false (preferimos enviar e deixar usuário decidir)."""


def classify_content(
    title: str,
    summary: str = "",
    api_key: str | None = None,
) -> tuple[bool, str]:
    """Pergunta ao Gemini se a matéria deve ser bloqueada.

    Retorna (block, reason). Em caso de erro, sempre retorna (False, "ai_fail")
    para não bloquear injustamente.
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return False, "no_api_key"

    prompt = CLASSIFY_PROMPT.format(title=title, summary=summary[:300])
    url = GEMINI_URL.format(model=GEMINI_MODEL)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,           # determinístico para classificação
            "maxOutputTokens": 200,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    r = None
    for attempt in range(2):
        try:
            r = requests.post(
                url,
                params={"key": api_key},
                json=body,
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code != 503:
                break
            time.sleep(1 + attempt)
        except requests.RequestException as exc:
            log.warning("Gemini classify request falhou: %s", exc)
            return False, "ai_fail"
    if r is None or r.status_code != 200:
        return False, "ai_fail"

    try:
        data = r.json()
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        text = _strip_md_fences(text)
        parsed = json.loads(text)
        block = bool(parsed.get("block", False))
        reason = str(parsed.get("reason", ""))[:80]
        return block, ("ai:" + reason if block else "")
    except (json.JSONDecodeError, KeyError, IndexError, ValueError) as exc:
        log.warning("Gemini classify parse falhou: %s", exc)
        return False, "ai_fail"


def render_copy_for_telegram(copy: dict) -> str:
    """Formata as 3 sugestões + legenda para entrar na mensagem do Telegram."""
    lines = ["✍️ *Copy pronto:*"]
    for i, t in enumerate(copy.get("titulos") or [], 1):
        lines.append(f"  {i}. {t}")
    legenda = (copy.get("legenda") or "").strip()
    if legenda:
        lines.append(f"📝 {legenda}")
    return "\n".join(lines)
