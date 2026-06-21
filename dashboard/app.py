"""Dashboard Streamlit — Sertanejo Radar.

Visualização read-only do SQLite. Lista as matérias rankeadas por score,
com filtros por janela temporal, artista e tipo de fonte.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import fetch_top_news, get_conn, init_schema  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


@st.cache_data(ttl=60)
def load_artistas() -> list[str]:
    doc = yaml.safe_load((CONFIG_DIR / "artistas.yaml").read_text(encoding="utf-8"))
    return doc.get("artistas", []) if isinstance(doc, dict) else []


def fmt_time_ago(ts: str) -> str:
    """Ex: 'há 2h', 'há 35min'."""
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    secs = int(delta.total_seconds())
    if secs < 3600:
        return f"há {secs // 60} min"
    if secs < 86400:
        return f"há {secs // 3600}h"
    return f"há {secs // 86400}d"


def _artist_names(raw) -> list[str]:
    """artist_hits pode estar no novo formato (list of dicts) ou antigo (list of str)."""
    try:
        parsed = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    names = []
    for h in parsed:
        if isinstance(h, dict) and "nome" in h:
            tier = h.get("tier")
            badge = "⭐" if tier == 1 else ("✨" if tier == 2 else "")
            names.append(f"{badge}{h['nome']}" if badge else h["nome"])
        else:
            names.append(str(h))
    return names


def render_card(row) -> None:
    score = float(row["score"] or 0)
    bar = "🟩" * int(round(score * 10)) + "⬜" * (10 - int(round(score * 10)))
    type_emoji = {
        "portal": "📰",
        "sertanejo": "🎤",
        "twitter": "🐦",
        "instagram": "📸",
    }.get(row["source_type"], "📄")

    try:
        sources = json.loads(row["sources_list"] or "[]")
    except (json.JSONDecodeError, TypeError):
        sources = [row["source"]]
    artists = _artist_names(row["artist_hits"])

    # safe access pra coluna filtered (compat com banco antigo)
    try:
        is_filtered = bool(row["filtered"])
        filter_reason = row["filter_reason"]
    except (IndexError, KeyError):
        is_filtered = False
        filter_reason = None

    with st.container(border=True):
        if is_filtered:
            st.warning(f"🚫 **Filtrada**: `{filter_reason or 'sem motivo registrado'}`")
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(f"#### {type_emoji} {row['title']}")
            sources_str = ", ".join(sources[:6])
            if len(sources) > 6:
                sources_str += f" +{len(sources) - 6}"
            st.caption(
                f"Fontes ({row['source_count']}): **{sources_str}** · "
                f"{fmt_time_ago(row['published_at'])}"
                + (f" · 🎯 {', '.join(artists)}" if artists else "")
            )
            if row["summary"]:
                with st.expander("Resumo da matéria"):
                    st.write(row["summary"])

            # Copy gerada (IA ou fallback)
            copy_titles_raw = row["copy_titles"]
            copy_caption = row["copy_caption"]
            copy_source = row["copy_source"] or ""
            if copy_titles_raw:
                try:
                    titulos = json.loads(copy_titles_raw)
                except (json.JSONDecodeError, TypeError):
                    titulos = []
                source_badge = "🤖 Gemini" if copy_source == "gemini" else "📝 fallback"
                with st.expander(f"✍️ Copy pronto ({source_badge})", expanded=False):
                    if titulos:
                        st.write("**Sugestões de título:**")
                        for i, t in enumerate(titulos, 1):
                            st.code(t, language=None)
                    if copy_caption:
                        st.write("**Legenda Instagram:**")
                        st.code(copy_caption, language=None)
        with col2:
            st.metric("Score", f"{score:.2f}")
            st.caption(bar)
        st.link_button("📰 Abrir matéria", row["url"], use_container_width=True)


def main() -> None:
    st.set_page_config(
        page_title="Sertanejo Radar",
        page_icon="🎤",
        layout="wide",
    )

    st.title("🎤 Sertanejo Radar")
    st.caption("Notícias virais do mundo sertanejo, rankeadas em tempo real.")

    # ---- Sidebar / Filtros ----
    with st.sidebar:
        st.header("Filtros")
        janela = st.selectbox(
            "Janela temporal",
            ["Últimas 24h", "Últimas 48h", "Últimos 7 dias"],
            index=1,
        )
        horas = {"Últimas 24h": 24, "Últimas 48h": 48, "Últimos 7 dias": 168}[janela]

        tipo = st.selectbox(
            "Tipo de fonte",
            ["Todas", "portal", "sertanejo", "twitter", "instagram"],
            index=0,
        )
        tipo_filter = None if tipo == "Todas" else tipo

        artistas = load_artistas()
        artista = st.selectbox(
            "Artista",
            ["Todos"] + sorted(set(artistas)),
            index=0,
        )
        artista_filter = None if artista == "Todos" else artista

        limit = st.slider("Quantidade", 10, 100, 30, 5)

        st.divider()
        st.subheader("⚙️ Avançado")
        mostrar_filtradas = st.checkbox(
            "Mostrar matérias filtradas",
            value=False,
            help="Matérias bloqueadas por serem negativas (críticas/polêmicas) "
                 "ou divulgações de música. Marque pra ver o que foi cortado e "
                 "ajustar as keywords se algo importante foi bloqueado por engano.",
        )

        st.divider()
        st.caption(
            "💡 O pipeline roda na nuvem a cada 30 min. "
            "Pra atualizar manualmente, vá no GitHub Actions → "
            "*Run workflow* no fluxo *Sertanejo Radar Pipeline*."
        )

    # ---- Conteúdo ----
    conn = get_conn()
    init_schema(conn)  # safe se já existir
    rows = fetch_top_news(
        conn,
        hours=horas,
        limit=limit,
        artist_filter=artista_filter,
        source_type_filter=tipo_filter,
        include_filtered=mostrar_filtradas,
    )
    conn.close()

    if not rows:
        st.info(
            "Nenhuma matéria ainda. Se acabou de criar o repo, "
            "rode o workflow manualmente uma vez no GitHub."
        )
        return

    st.caption(f"Mostrando **{len(rows)}** matérias rankeadas por score de viralidade.")
    for row in rows:
        render_card(row)


if __name__ == "__main__":
    main()
