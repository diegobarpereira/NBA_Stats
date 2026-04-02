import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gerador.bilheteiro import Bilheteiro
from gerador.props_engine import PropsEngine
from components.ticket_card import render_ticket_card
from utils.session_helpers import regenerate_props
from utils.data_loader import DataLoader


def _init_session():
    if "loader" not in st.session_state:
        st.session_state.loader = DataLoader()
        try:
            st.session_state.loader.load_all()
        except FileNotFoundError:
            pass
    if "stats" not in st.session_state:
        st.session_state.stats = st.session_state.loader.stats_cache.copy()
        st.session_state.stats_loaded = bool(st.session_state.stats)
    if "matchup_data" not in st.session_state:
        st.session_state.matchup_data = None
    if "props_generated" not in st.session_state:
        st.session_state.props_generated = False
    if "bilhetes_generated" not in st.session_state:
        st.session_state.bilhetes_generated = False


_init_session()

st.title("🎫 Bilhetes Gerados")
st.markdown("Visualize os bilhetes por jogo no formato de tabela ou cartão.")

if not st.session_state.bilhetes_generated or not st.session_state.bilhetes:
    with st.spinner("Gerando bilhetes..."):
        regenerate_props()
    st.rerun()

bilhetes = st.session_state.bilhetes
total_combined = 1.0
for t in bilhetes:
    total_combined *= t["total_odds"]

col_m1, col_m2, col_m3, col_m4 = st.columns(4)
col_m1.metric("🎫 Bilhetes", len(bilhetes))
col_m2.metric("🎯 Odd Min", f"{min(t['total_odds'] for t in bilhetes):.2f}x")
col_m3.metric("🎯 Odd Max", f"{max(t['total_odds'] for t in bilhetes):.2f}x")
col_m4.metric("📊 Odd Combinada Total", f"{total_combined:.2f}x", delta=f"{total_combined:.0f}x")

st.markdown("---")

view_mode = st.radio(
    "Modo de Visualização",
    ["📋 Tabela", "🎴 Cartões", "📋 Tabela + 🎴 Cartões"],
    horizontal=True,
    label_visibility="collapsed",
)

if view_mode in ["📋 Tabela", "📋 Tabela + 🎴 Cartões"]:
    st.markdown("#### 📋 Visualização em Tabela")

    table_rows = []
    for t in bilhetes:
        for prop in t["props"]:
            table_rows.append({
                "Jogo": f"{t['away']} @ {t['home']}",
                "Jogador": prop["player"],
                "Tipo": prop["type"].upper(),
                "Linha": f"+{prop['line']}",
                "Odds": prop["odds"],
                "Conf": prop["confidence"],
                "Season": prop.get("season_avg", 0),
                "Last5": prop.get("last5_avg", 0),
                "Odd Total": t["total_odds"],
                "Props": t["num_props"],
            })

    st.dataframe(
        table_rows,
        column_config={
            "Jogo": st.column_config.TextColumn("Jogo", width="medium"),
            "Jogador": st.column_config.TextColumn("Jogador", width="medium"),
            "Tipo": st.column_config.TextColumn("Tipo", width="small"),
            "Linha": st.column_config.TextColumn("Linha", width="small"),
            "Odds": st.column_config.NumberColumn("Odds", format="%.2f", width="small"),
            "Conf": st.column_config.NumberColumn("Conf", format="%d/10", width="small"),
            "Season": st.column_config.NumberColumn("Season", format="%.1f", width="small"),
            "Last5": st.column_config.NumberColumn("Last5", format="%.1f", width="small"),
            "Odd Total": st.column_config.NumberColumn("Odd Total", format="%.2f", width="small"),
            "Props": st.column_config.NumberColumn("Qtd Props", width="small"),
        },
        hide_index=True,
        width='stretch',
        height=600,
    )

if view_mode in ["🎴 Cartões", "📋 Tabela + 🎴 Cartões"]:
    from components.ticket_card import _inject_css
    _inject_css()
    st.markdown("#### 🎴 Visualização em Cartões")

    for i, ticket in enumerate(bilhetes):
        render_ticket_card(ticket, i + 1)
        st.markdown("")

if view_mode == "📋 Tabela + 🎴 Cartões":
    st.markdown("---")

st.markdown("---")

bilheteiro = st.session_state.get("bilheteiro")
if bilheteiro:
    output_path = bilheteiro.save_all_tickets(bilhetes)
    json_data = open(output_path, "r", encoding="utf-8").read()

    col_down1, col_down2 = st.columns(2)
    with col_down1:
        st.success(f"💾 Bilhetes salvos em: `{output_path.name}`")
    with col_down2:
        st.download_button(
            "📥 Download JSON",
            data=json_data,
            file_name="bilhetes_nba.json",
            mime="application/json",
        )

st.markdown("---")
st.caption(f"Gerado em: {st.session_state.get('generated_time', 'agora')}")
