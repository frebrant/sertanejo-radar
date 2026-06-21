"""Filtros de conteúdo: bloqueia matérias que o usuário não quer postar.

Categorias bloqueadas (definidas pelo usuário):
  1. NEGATIVAS — críticas diretas, polêmicas, processos, cancelamentos
  2. DIVULGAÇÃO — lançamento de single/EP/álbum, bastidores de gravação

LIBERADAS (NÃO bloqueia):
  - Tretas / brigas / separações entre artistas (vira post de fofoca bom)
  - Críticas leves / comentários de internautas
  - Anúncios de show / turnê
  - Clipes / parcerias
  - Curiosidades, declarações, viagens etc.

Estratégia: 2 camadas
  1. KEYWORDS (rápido, custo zero, pega casos óbvios)
  2. GEMINI (segunda camada para borderline — chamada via ai_copy)
"""
from __future__ import annotations

import re
from unidecode import unidecode


# ============================================================================
# CATEGORIA 1: NEGATIVAS (críticas, polêmicas, processos, cancelamentos)
# ============================================================================

KEYWORDS_NEGATIVAS = [
    # Críticas diretas
    "fiasco", "fracasso", "fracassou", "fracassa",
    "decepcao", "decepcionou", "decepciona",
    "vergonhoso", "vergonha alheia",
    "humilhante", "humilhacao",
    "patetico", "constrangedor",
    "pessimo show", "pessimo desempenho",
    "vaiado", "vaiada", "vaiaram",
    "criticado por", "criticada por",
    "destruido pelas criticas", "destruida pelas criticas",
    "detonado", "detonada", "detonou",
    "afundou", "afundando",
    "esculacho", "esculachado",

    # Polêmicas sérias
    "polemica", "polemico",
    "envolvido em escandalo", "envolvida em escandalo",
    "acusado de", "acusada de",
    "acusacao de",
    "denunciado por", "denunciada por",
    "denuncia contra",
    "investigado por", "investigada por",
    "preso por", "presa por",
    "indiciado", "indiciada",
    "condenado", "condenada",
    "absolvido", "absolvida",

    # Processos/justiça
    "processo na justica", "processado por", "processada por",
    "processou", "processa",
    "acao judicial",
    "vai a justica",
    "moveu acao",
    "indenizacao",
    "condenado a pagar", "condenada a pagar",
    "multa de",

    # Cancelamentos
    "cancelado nas redes", "cancelada nas redes",
    "cancelamento",
    "boicote", "boicotado", "boicotada",
    "expulso", "expulsa",
    "demitido", "demitida",
    "exonerado", "exonerada",

    # Polêmicas específicas comuns no sertanejo
    "agressao",
    "violencia domestica",
    "assedio", "assediou",
    "estupro",
    "racismo", "racista",
    "homofobia", "homofobico",
    "machismo", "machista",
    "drogas", "preso com drogas",
    "embriaguez", "alcoolizado",
    "fraude", "sonegacao",
    "dividas com a justica",
    "calote",
]

# ============================================================================
# CATEGORIA 2: DIVULGAÇÃO DE MÚSICA (lançamentos + bastidores)
# ============================================================================

KEYWORDS_DIVULGACAO = [
    # Lançamentos
    "lanca nova musica", "lanca novo single", "lanca novo album",
    "lancamento de", "lancamento do single", "lancamento do album",
    "lancou o single", "lancou novo", "lancou nova",
    "estreia o single", "estreia novo album",
    "novo single", "novo album", "novo ep",
    "nova musica de", "nova musica chega",
    "lancara", "lanca em",
    "disco novo", "album inedito",
    "single inedito", "musica inedita",
    "ouca a nova", "ouca o novo",
    "musica disponivel", "ja disponivel",
    "chega as plataformas",
    "agora nas plataformas",
    "single chega",
    "ep estreia",
    "primeira faixa",
    "track-list", "tracklist",
    "faixa-titulo",

    # Bastidores
    "bastidores da gravacao", "bastidores do clipe",
    "making of",
    "veja como foi a gravacao",
    "por tras das cameras",
    "preparacao para o clipe",
    "set de gravacao",
]


# ============================================================================
# Função principal
# ============================================================================

def _normalize(text: str) -> str:
    """Lowercase + sem acento — formato em que comparamos as keywords."""
    return unidecode(text or "").lower()


def filter_by_keywords(title: str, summary: str = "") -> tuple[bool, str]:
    """Retorna (block, reason).

    block=True significa bloquear a matéria.
    reason indica em qual categoria caiu (pra log/debug).
    """
    text = _normalize(f"{title} {summary}")

    for kw in KEYWORDS_NEGATIVAS:
        if kw in text:
            return True, f"negativa:{kw}"

    for kw in KEYWORDS_DIVULGACAO:
        if kw in text:
            return True, f"divulgacao:{kw}"

    return False, ""


def should_ask_ai(title: str, summary: str = "") -> bool:
    """Heurística simples: vale a pena gastar uma chamada Gemini para filtrar?

    Critério: tem keyword "borderline" que pode ser negativa ou divulgação,
    mas não tem match exato. Para v1, sempre retorna False (a camada Gemini
    pode ser ativada em iteração futura via ai_copy.classify_content).
    """
    return False
