"""Deduplicação: hash canônico + fuzzy match.

A mesma notícia chega em vários portais com títulos ligeiramente diferentes.
Estratégia em 2 níveis:

1. Hash canônico: normaliza (lowercase + sem acento + sem stopwords + ordenado).
   Mesmo hash = mesma notícia, garantido.

2. Fuzzy match: se hash novo, compara via rapidfuzz com matérias das últimas 48h.
   Se similaridade >= 85, usa o hash existente (considera mesma notícia).
"""
from __future__ import annotations

import hashlib
import re

from rapidfuzz import fuzz
from unidecode import unidecode

# Stopwords PT-BR que poluem a comparação de títulos
STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas",
    "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas",
    "por", "para", "pra", "pro",
    "com", "sem", "sob", "sobre", "ate", "ate",
    "e", "ou", "mas", "que", "se", "como", "porque",
    "ja", "nao", "sim", "mais", "menos",
    "ele", "ela", "eles", "elas", "isto", "isso", "aquilo",
    "seu", "sua", "seus", "suas",
    "este", "esta", "estes", "estas",
    "esse", "essa", "esses", "essas",
    "aquele", "aquela", "aqueles", "aquelas",
}

FUZZY_THRESHOLD = 75  # similarity ratio para considerar mesma notícia
# Combinamos token_set_ratio (palavras compartilhadas) com partial_ratio
# (substring de menor em maior) — pega variações como "bomba/bombastica".
PARTIAL_THRESHOLD = 80


def normalize_title(title: str) -> str:
    """Reduz título a forma canônica: lowercase, sem acento, sem stopwords, ordenado."""
    text = unidecode(title or "").lower()
    # remove pontuação e mantém só palavras
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [t for t in text.split() if t and t not in STOPWORDS and len(t) > 2]
    # ordenar tokens torna a comparação independente de ordem das palavras
    tokens.sort()
    return " ".join(tokens)


def canonical_hash(title: str) -> str:
    """MD5 do título normalizado."""
    return hashlib.md5(normalize_title(title).encode("utf-8")).hexdigest()


def find_similar(title: str, recent_rows) -> str | None:
    """Busca matéria das últimas 48h com título suficientemente parecido.

    `recent_rows` aceita lista de sqlite3.Row OU lista de dicts — em ambos os
    casos cada item deve responder a row["canonical_hash"] e row["title"].
    Retorna o canonical_hash da matéria existente OU None se nada bate.
    Usa token_set_ratio: tolera ordem, plurais, palavras extras.
    """
    new_normalized = normalize_title(title)
    if not new_normalized:
        return None

    best_score = 0
    best_hash: str | None = None
    for row in recent_rows:
        existing_normalized = normalize_title(row["title"])
        if not existing_normalized:
            continue
        # Dois critérios: tokens compartilhados OU substring forte
        token_score = fuzz.token_set_ratio(new_normalized, existing_normalized)
        partial_score = fuzz.partial_ratio(new_normalized, existing_normalized)
        # combinado: usa o maior; só conta se ao menos um passa do threshold
        if token_score >= FUZZY_THRESHOLD or partial_score >= PARTIAL_THRESHOLD:
            combined = max(token_score, partial_score)
            if combined > best_score:
                best_score = combined
                best_hash = row["canonical_hash"]

    return best_hash


def resolve_hash(title: str, recent_rows: list[sqlite3.Row]) -> str:
    """Decide o hash canônico final: usa existente se houver match fuzzy, senão gera novo."""
    similar = find_similar(title, recent_rows)
    return similar if similar else canonical_hash(title)


def find_artist_hits(title: str, summary: str, artistas_tiered: dict) -> list[dict]:
    """Lista de artistas mencionados, cada um com seu tier.

    `artistas_tiered` = {"tier_1": [...], "tier_2": [...], "tier_3": [...]}
    Retorna: [{"nome": "Virginia", "tier": 1}, ...] (sem duplicatas, mantém menor tier).
    """
    text = unidecode(f"{title} {summary or ''}").lower()
    hits: list[dict] = []
    seen_names: dict[str, int] = {}  # nome → tier (mantém o menor)

    for tier_key in ("tier_1", "tier_2", "tier_3"):
        tier_num = int(tier_key.split("_")[1])
        for nome in artistas_tiered.get(tier_key, []) or []:
            nome_norm = unidecode(nome).lower()
            # match com fronteira de palavra para evitar 'leo' bater em 'leonardo'
            pattern = r"\b" + re.escape(nome_norm) + r"\b"
            if re.search(pattern, text):
                # se já foi pego em tier menor (mais importante), pula
                if nome in seen_names and seen_names[nome] <= tier_num:
                    continue
                seen_names[nome] = tier_num

    for nome, tier in seen_names.items():
        hits.append({"nome": nome, "tier": tier})
    return hits
