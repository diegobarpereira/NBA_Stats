import streamlit as st
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import config
from utils.data_loader import DataLoader
from gerador.props_engine import PropsEngine
from gerador.bilheteiro import Bilheteiro
from scrapers.blowout_risk import analyze_games_blowout_risk
from scrapers.matchup_scraper import fetch_and_cache_matchups

st.set_page_config(
    page_title="NBA Milionário",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        border-radius: 4px 4px 0 0;
    }
    section[data-testid="stSidebar"] {
        background-color: #0e1117;
    }
    div[data-testid="stStatusWidget"] {
        display: none;
    }
    .block-container {
        padding-top: 1rem;
    }
</style>
""", unsafe_allow_html=True)


def load_session():
    if "loader" not in st.session_state:
        st.session_state.loader = DataLoader()
        try:
            st.session_state.loader.load_all()
        except FileNotFoundError:
            pass

    if "stats_loaded" not in st.session_state:
        st.session_state.stats_loaded = False
        st.session_state.stats = {}
        if st.session_state.loader.stats_cache:
            st.session_state.stats = st.session_state.loader.stats_cache.copy()
            st.session_state.stats_loaded = True

    if "matchup_data" not in st.session_state:
        st.session_state.matchup_data = None

    if "props_generated" not in st.session_state:
        st.session_state.props_generated = False
        st.session_state.all_props = []

    if "bilhetes_generated" not in st.session_state:
        st.session_state.bilhetes_generated = False
        st.session_state.bilhetes = []


def regenerate_props():
    if not st.session_state.stats_loaded or not st.session_state.loader.games_data:
        return

    matchup = st.session_state.matchup_data
    if matchup is None:
        matchup = fetch_and_cache_matchups()
        st.session_state.matchup_data = matchup

    injured = st.session_state.loader.get_injured_players()
    questionable = st.session_state.loader.get_questionable_players()
    engine = PropsEngine()
    all_props = []

    for game in st.session_state.loader.games_data:
        risk = {}
        if st.session_state.loader.teams_data:
            risks = analyze_games_blowout_risk(
                st.session_state.loader.games_data,
                st.session_state.stats,
                injured,
                st.session_state.loader.teams_data,
            )
            risk = risks.get(game["id"], {})

        game_props = engine.generate_props_for_game(
            game,
            st.session_state.stats,
            injured,
            questionable,
            st.session_state.loader.teams_data,
            matchup,
            risk,
        )
        all_props.extend(game_props)

    st.session_state.all_props = all_props
    st.session_state.props_generated = True

    first_game = st.session_state.loader.games_data[0] if st.session_state.loader.games_data else {}
    game_date = first_game.get("datetime", "")[:10] if first_game else datetime.now().strftime("%Y-%m-%d")

    bilheteiro = Bilheteiro(date=game_date)
    bilheteiro.props_engine = engine
    bilhetes = bilheteiro.generate_multi_game_ticket(all_props, st.session_state.loader.games_data)
    st.session_state.bilhetes = bilhetes
    st.session_state.bilhetes_generated = True


load_session()

with st.sidebar:
    st.markdown("### 🏀 NBA Milionário")
    st.markdown("---")

    if st.session_state.stats_loaded:
        st.success(f"📊 {len(st.session_state.stats)} jogadores em cache")
    else:
        st.warning("⚠️ Cache vazio — execute scraping")

    if st.session_state.loader.games_data:
        st.info(f"📅 {len(st.session_state.loader.games_data)} jogos carregados")
    else:
        st.warning("⚠️ Nenhum jogo carregado")

    if st.session_state.loader.injuries_data:
        total_inj = len(st.session_state.loader.get_injured_players())
        total_quest = len(st.session_state.loader.get_questionable_players())
        st.info(f"🏥 {total_inj} OUT | {total_quest} QUESTIONABLE")
    else:
        st.warning("⚠️ Nenhum relatório de lesões")

    st.markdown("---")
    st.caption("by NBA Stats Generator")

st.markdown("""
<h1 style='text-align: center; color: #FF6B35; font-size: 2.2rem; margin-bottom: 0.2rem;'>
    🏀 NBA MILIONÁRIO
</h1>
<p style='text-align: center; color: #888; margin-top: 0;'>
    Gerador de Bilhetes com Props Dinâmicos
</p>
""", unsafe_allow_html=True)

pg = st.navigation([
    st.Page("pages/1_Dados_do_Dia.py", title="📋 Dados do Dia", default=True),
    st.Page("pages/3_Propriedades.py", title="📊 Propriedades"),
    st.Page("pages/4_Bilhetes.py", title="🎫 Bilhetes"),
    st.Page("pages/A_BetSlip.py", title="🎲 BetSlip v2"),
    st.Page("pages/5_Comparativo.py", title="📈 Comparativo"),
])
pg.run()
