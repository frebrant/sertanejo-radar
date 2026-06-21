"""Filtros de conteúdo: bloqueia matérias que o usuário não quer postar.

Categorias bloqueadas (definidas pelo usuário):
  0. NÃO-SERTANEJO — matéria que não cita artista da lista nem palavra-chave
                      do universo sertanejo (a maioria dos portais cobre TODAS
                      as celebridades, gera muito ruído)
  1. NEGATIVAS — críticas diretas, polêmicas, processos, cancelamentos
  2. DIVULGAÇÃO — lançamento de single/EP/álbum, bastidores de gravação

LIBERADAS (NÃO bloqueia):
  - Tretas / brigas / separações entre artistas (vira post de fofoca bom)
  - Críticas leves / comentários de internautas
  - Anúncios de show / turnê
  - Clipes / parcerias
  - Curiosidades, declarações, viagens etc.

Estratégia: 3 camadas
  1. FILTRO SERTANEJO (matéria precisa ter algum sinal do universo)
  2. KEYWORDS (negativas + divulgação)
  3. GEMINI (segunda camada para borderline — chamada via ai_copy)
"""
from __future__ import annotations

import re
from unidecode import unidecode


def _normalize(text: str) -> str:
    """Lowercase + sem acento — formato em que comparamos as keywords."""
    return unidecode(text or "").lower()


# ============================================================================
# CATEGORIA 0: NÃO-SERTANEJO (matéria sem conexão com o gênero)
# ============================================================================

# Palavras-chave do universo sertanejo que indicam relevância.
# Se matéria não cita artista da lista (artistas.yaml) E não tem nenhuma
# dessas palavras → considerado "não-sertanejo" e bloqueado.
KEYWORDS_SERTANEJO = [
    # Gênero/identidade
    "sertanejo", "sertaneja", "sertanejos", "sertanejas",
    "sertaneja universitaria", "sertanejo universitario",
    "modao", "moda de viola", "modao raiz",
    "feminejo", "feminejas",
    "agroboy", "agro-boy",
    "country",
    "musica de raiz", "raiz",
    "duplas sertanejas", "dupla sertaneja",

    # Mundo / cultura
    "rodeio", "rodeios",
    "festa do peao", "peao de boiadeiro", "peao boiadeiro",
    "barretos", "festa de barretos",
    "vaquejada", "vaquejadas",
    "cavalgada",
    "boiadeira", "boiadeiro",
    "fazenda", "fazendao",
    "agronegocio",

    # Eventos / contextos típicos
    "sao joao", "festa junina",
    "expo " ,    # ex: Expoagro, Expoinel
    "expoinel",
    "expoagro",

    # Outras palavras fortemente associadas
    "violao caipira", "viola caipira",
    "caipira",
    "arrocha",
    "piseiro", "forro",   # gêneros vizinhos que muitas vezes andam junto
]


def _has_sertanejo_signal(title: str, summary: str, artist_hits) -> bool:
    """True se matéria tem QUALQUER sinal de relevância sertaneja:
    - artist_hits não vazio (cita artista da lista)
    - OU contém alguma palavra-chave do gênero
    """
    if artist_hits:
        return True
    text = _normalize(f"{title} {summary or ''}")
    for kw in KEYWORDS_SERTANEJO:
        # match com fronteira de palavra para evitar 'expo' bater em 'exposicao'
        if re.search(r"\b" + re.escape(kw) + r"\b", text):
            return True
    return False


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

def filter_by_keywords(
    title: str,
    summary: str = "",
    artist_hits=None,
    source_type: str = "portal",
) -> tuple[bool, str]:
    """Retorna (block, reason).

    block=True significa bloquear a matéria.
    reason indica em qual categoria caiu (pra log/debug).

    Ordem de verificação:
      1. NÃO-SERTANEJO (pulado se source_type='sertanejo' — esses portais já
         são focados, não precisam ser filtrados por gênero)
      2. NEGATIVAS
      3. DIVULGAÇÃO
    """
    # 1) Filtro de relevância sertaneja (só para portais gerais)
    if source_type != "sertanejo":
        if not _has_sertanejo_signal(title, summary, artist_hits):
            return True, "nao_sertanejo"

    text = _normalize(f"{title} {summary}")

    # 2) Conteúdo negativo
    for kw in KEYWORDS_NEGATIVAS:
        if kw in text:
            return True, f"negativa:{kw}"

    # 3) Divulgação de música
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
