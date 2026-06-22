"""Fórmula de viralidade.

score = 0.40*frescor + 0.20*multi_fonte + 0.20*bonus_artista
      + 0.15*bonus_portal_sertanejo + 0.05*bonus_fonte_quente

- frescor: pesa mais (notícia antiga já foi postada)
- multi_fonte: 4 fontes distintas confirmando = 1.0
- bonus_artista: depende do TIER do artista citado:
    tier 1 (Virginia, Gusttavo, Zé Felipe...) = 1.0
    tier 2 (duplas relevantes)                = 0.6
    tier 3 (cobertura ampla)                  = 0.3
- bonus_portal_sertanejo: 1.0 se source_type='sertanejo' (Movimento Country,
    Portal Sertanejo etc.), senão 0. Equilibra fofoca x notícia de sertanejo.
- bonus_fonte_quente: 1 se source é fofoqueiro Twitter (Choquei etc.)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Fontes "quentes" que costumam estourar primeiro
FONTES_QUENTES = {
    "choquei",
    "leodias",                 # Twitter handle (não confundir com "Leo Dias" portal)
    "PortalArrependido",
    "central_fofoca",
    "hugogloss",
}


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        # SQLite devolve strings ISO; tenta múltiplos formatos
        s = str(value).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # fallback: tenta sem timezone
            dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def calc_frescor(published_at: Any, now: datetime | None = None) -> float:
    """1.0 = acabou de sair; 0.0 = >= 48h atrás."""
    now = now or datetime.now(timezone.utc)
    dt = _parse_dt(published_at)
    horas = (now - dt).total_seconds() / 3600
    return max(0.0, 1.0 - horas / 48.0)


def calc_multi_fonte(source_count: int) -> float:
    """4+ fontes diferentes = 1.0."""
    return min(1.0, source_count / 4.0)


# Boost por tier — quanto menor o tier, maior o peso
TIER_BOOST = {1: 1.0, 2: 0.6, 3: 0.3}


def calc_bonus_artista(artist_hits: list | None) -> float:
    """Pega o MAIOR boost entre todos os artistas citados (= menor tier)."""
    if not artist_hits:
        return 0.0
    # cada hit é um dict {"nome": ..., "tier": int} OU string (compat com versão antiga)
    best = 0.0
    for hit in artist_hits:
        tier = hit["tier"] if isinstance(hit, dict) else 1  # compat: string = tier 1
        boost = TIER_BOOST.get(tier, 0.3)
        if boost > best:
            best = boost
    return best


def calc_bonus_fonte_quente(source: str) -> float:
    return 1.0 if source in FONTES_QUENTES else 0.0


def calc_bonus_portal_sertanejo(source_type: str) -> float:
    """1.0 se vem de portal focado em sertanejo (mais notícia do gênero, menos
    fofoca de celebridades em geral)."""
    return 1.0 if source_type == "sertanejo" else 0.0


def score_news(
    published_at: Any,
    source_count: int,
    artist_hits: list[str] | None,
    source: str,
    source_type: str = "portal",
    now: datetime | None = None,
) -> float:
    """Score final entre 0 e 1."""
    return round(
        0.40 * calc_frescor(published_at, now)
        + 0.20 * calc_multi_fonte(source_count)
        + 0.20 * calc_bonus_artista(artist_hits)
        + 0.15 * calc_bonus_portal_sertanejo(source_type)
        + 0.05 * calc_bonus_fonte_quente(source),
        4,
    )
