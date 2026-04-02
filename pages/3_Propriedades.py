import streamlit as st
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from gerador.props_engine import PropsEngine
from scrapers.matchup_scraper import fetch_and_cache_matchups
from scrapers.blowout_risk import analyze_games_blowout_risk
from utils.data_loader import DataLoader
import config
from utils.session_helpers import regenerate_props


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

st.title("📊 Propriedades (Props)")
st.markdown("Visualize e filtre os props gerados para cada jogo do dia.")

if not st.session_state.stats_loaded:
    st.error("⚠️ Execute o scraping primeiro na aba **Scraping**.")
    st.stop()

if not st.session_state.loader.games_data:
    st.error("⚠️ Carregue os jogos do dia na aba **Dados do Dia**.")
    st.stop()

st.markdown("---")
st.markdown("### 🎯 Análise de Risco de Blowout")

injured = st.session_state.loader.get_injured_players()
risks = analyze_games_blowout_risk(
    st.session_state.loader.games_data,
    st.session_state.stats,
    injured,
    st.session_state.loader.teams_data,
)

for game in st.session_state.loader.games_data:
    game_risk = risks.get(game["id"], {})
    if game_risk:
        prob = game_risk.get("blowout_prob", 0)
        level = game_risk.get("risk_level", "BAIXO")
        away = game_risk.get("away", "")
        home = game_risk.get("home", "")
        direction = game_risk.get("direction", "")
        
        emoji = "🔴" if prob > 0.5 else "🟡" if prob > 0.2 else "🟢"
        st.write(f"{emoji} **{away} @ {home}** | Prob: {prob:.0%} | Risk: {level}")
        if direction and direction != "competitive":
            loser = game_risk.get("loser", "")
            st.write(f"   → {direction} | Perdedor: {loser} | Starter minutos: {game_risk.get('minute_mult_min', 0):.0%}-{game_risk.get('minute_mult_max', 0):.0%}")

if not st.session_state.props_generated:
    with st.spinner("Gerando props..."):
        regenerate_props()
    st.rerun()


props = st.session_state.all_props
engine = PropsEngine()
bilheteiro_obj = st.session_state.get("bilheteiro")
if bilheteiro_obj is None:
    from gerador.bilheteiro import Bilheteiro
    first_game = st.session_state.loader.games_data[0] if st.session_state.loader.games_data else {}
    game_date = first_game.get("datetime", "")[:10] if first_game else datetime.now().strftime("%Y-%m-%d")
    bilheteiro_obj = Bilheteiro(date=game_date)
    bilheteiro_obj.props_engine = engine
    st.session_state.bilheteiro = bilheteiro_obj


def conf_color(conf):
    if conf >= 8:
        return "🟢"
    elif conf >= 5:
        return "🟡"
    return "🔴"


st.markdown(f"**Total de props gerados:** {len(props)}")

col_filter1, col_filter2, col_filter3 = st.columns(3)

all_teams = sorted(set(p["team"] for p in props))
all_types = sorted(set(p["type"] for p in props))

with col_filter1:
    filter_team = st.selectbox("Time", ["Todos"] + all_teams)

with col_filter2:
    filter_type = st.selectbox("Tipo de Prop", ["Todos"] + all_types)

with col_filter3:
    filter_conf = st.slider("Confiança mínima", 0, 10, 0)

filtered = props
if filter_team != "Todos":
    filtered = [p for p in filtered if p["team"] == filter_team]
if filter_type != "Todos":
    filtered = [p for p in filtered if p["type"] == filter_type]
if filter_conf > 0:
    filtered = [p for p in filtered if engine.get_confidence_score(p) >= filter_conf]

st.markdown(f"**Props filtrados:** {len(filtered)}")

rows = []
for p in filtered:
    conf = engine.get_confidence_score(p)
    odds = bilheteiro_obj.calculate_prop_odds(p)
    injury_tag = f" ⚠️ {p.get('injury_status', '')}" if p.get('injury_status') else ""
    rows.append({
        "Jogador": p["player"],
        "Time": p["team"],
        "Tipo": p["type"].upper(),
        "Linha": p["line"],
        "Odds": odds,
        "Conf": f"{conf_color(conf)} {conf}",
        "Season Avg": p.get("season_avg", 0),
        "Last5 Avg": p.get("last5_avg", 0),
        "Matchup": f"{p.get('matchup_mult', 1.0):.2f}x",
        "Status": injury_tag if injury_tag else "✅ Ativo",
    })

st.dataframe(
    rows,
    column_config={
        "Jogador": st.column_config.TextColumn("Jogador", width="medium"),
        "Time": st.column_config.TextColumn("Time", width="small"),
        "Tipo": st.column_config.TextColumn("Tipo", width="small"),
        "Linha": st.column_config.NumberColumn("Linha", format="%.1f", width="small"),
        "Odds": st.column_config.NumberColumn("Odds", format="%.2f", width="small"),
        "Conf": st.column_config.TextColumn("Conf", width="small"),
        "Season Avg": st.column_config.NumberColumn("Season Avg", format="%.1f", width="small"),
        "Last5 Avg": st.column_config.NumberColumn("Last5 Avg", format="%.1f", width="small"),
        "Matchup": st.column_config.TextColumn("Matchup", width="small"),
        "Status": st.column_config.TextColumn("Status", width="medium"),
    },
    hide_index=True,
    width='stretch',
    height=500,
)

st.markdown("---")

st.markdown("#### 🏀 Props por Jogo")

games_with_props = {}
for p in props:
    gid = p.get("game_id", "")
    if gid not in games_with_props:
        games_with_props[gid] = {
            "home": p.get("home", ""),
            "away": p.get("away", ""),
            "datetime": p.get("datetime", ""),
            "props": [],
        }
    games_with_props[gid]["props"].append(p)

for gid, game_data in sorted(games_with_props.items()):
    with st.expander(f"**{game_data['away']} @ {game_data['home']}** — {len(game_data['props'])} props"):
        game_props = sorted(game_data["props"], key=lambda p: -engine.get_confidence_score(p))
        gp_rows = []
        for p in game_props:
            conf = engine.get_confidence_score(p)
            gp_rows.append({
                "Jogador": p["player"],
                "Tipo": p["type"].upper(),
                "Linha": p["line"],
                "Odds": bilheteiro_obj.calculate_prop_odds(p),
                "Conf": f"{conf_color(conf)} {conf}",
                "Season": p.get("season_avg", 0),
                "Last5": p.get("last5_avg", 0),
                "Matchup": f"{p.get('matchup_mult', 1.0):.2f}x",
            })
        st.dataframe(
            gp_rows,
            column_config={
                "Jogador": st.column_config.TextColumn("Jogador"),
                "Tipo": st.column_config.TextColumn("Tipo"),
                "Linha": st.column_config.NumberColumn("Linha", format="%.1f"),
                "Odds": st.column_config.NumberColumn("Odds", format="%.2f"),
                "Conf": st.column_config.TextColumn("Conf"),
                "Season": st.column_config.NumberColumn("Season", format="%.1f"),
                "Last5": st.column_config.NumberColumn("Last5", format="%.1f"),
                "Matchup": st.column_config.TextColumn("Matchup"),
            },
            hide_index=True,
            width='stretch',
        )

st.markdown("---")
if st.button("🎫 Gerar Bilhetes", type="primary"):
    if not st.session_state.bilhetes_generated:
        regenerate_props()
    st.switch_page("pages/4_Bilhetes.py")
