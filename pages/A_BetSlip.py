import streamlit as st
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from gerador.bilheteiro_v2 import BilheteiroV2
from gerador.props_engine_v2 import PropsEngineV2
from components.ticket_card import render_ticket_card
from utils.data_loader import DataLoader
from scrapers.matchup_scraper import fetch_and_cache_matchups
from scrapers.blowout_risk import analyze_games_blowout_risk


PROP_LABELS = {
    "points": "pts",
    "rebounds": "reb",
    "assists": "ast",
    "3pt": "3pm",
}


def _init_session_v2():
    base_loader = st.session_state.get("loader")

    if "loader_v2" not in st.session_state:
        if base_loader and base_loader.games_data:
            st.session_state.loader_v2 = base_loader
        else:
            st.session_state.loader_v2 = DataLoader()
            try:
                st.session_state.loader_v2.load_all()
            except Exception as e:
                st.error(f"Erro ao carregar dados: {e}")
    elif base_loader and base_loader.games_data:
        st.session_state.loader_v2 = base_loader

    if "stats_v2" not in st.session_state:
        st.session_state.stats_v2 = {}

    if "stats" in st.session_state and st.session_state.stats:
        st.session_state.stats_v2 = st.session_state.stats.copy()
    elif st.session_state.loader_v2.stats_cache:
        st.session_state.stats_v2 = st.session_state.loader_v2.stats_cache.copy()

    st.session_state.stats_loaded_v2 = bool(st.session_state.stats_v2)

    if "matchup_data_v2" not in st.session_state:
        st.session_state.matchup_data_v2 = None
    
    if "props_v2_generated" not in st.session_state:
        st.session_state.props_v2_generated = False

    if "props_v2" not in st.session_state:
        st.session_state.props_v2 = []

    if "bilhetes_v2" not in st.session_state:
        st.session_state.bilhetes_v2 = []

    if "bilhetes_v2_attempted" not in st.session_state:
        st.session_state.bilhetes_v2_attempted = False

    if "bilhetes_v2_error" not in st.session_state:
        st.session_state.bilhetes_v2_error = None

    if "bilhetes_v2_last_mode" not in st.session_state:
        st.session_state.bilhetes_v2_last_mode = None

    if "bilhetes_v2_options" not in st.session_state:
        st.session_state.bilhetes_v2_options = {}

    if "bilhetes_v2_output_path" not in st.session_state:
        st.session_state.bilhetes_v2_output_path = None


_init_session_v2()

st.title("🎫 Bilhetes v2")
st.markdown("""
**Diferenças da versão anterior:**
- Usa odds reais da Bet365 quando disponíveis
- Inclui métrica de agressividade da linha
- Gera múltiplas opções (conservative/balanced/aggressive)
- Score de qualidade considera diversidade
""")

if not st.session_state.get("stats_loaded_v2"):
    st.error("Execute o scraping primeiro.")
    st.stop()

if not st.session_state.loader_v2.games_data:
    st.error("Carregue os jogos do dia.")
    st.stop()

st.caption(f"📊 {len(st.session_state.stats_v2)} jogadores carregados | {len(st.session_state.loader_v2.games_data)} jogos")

st.markdown("---")

mode = st.select_slider(
    "Modo do bilhete",
    ["conservative", "balanced", "aggressive"],
    value="balanced",
    format_func=lambda x: {
        "conservative": "🔒 Conservative",
        "balanced": "⚖️ Equilibrado",
        "aggressive": "🔥 Agressivo",
    }[x]
)

if st.button("Gerar Bilhetes v2", key="btn_gerar_v2"):
    try:
        st.session_state.bilhetes_v2_error = None
        with st.spinner("Gerando bilhetes..."):
            matchup = st.session_state.matchup_data_v2
            if matchup is None:
                matchup = fetch_and_cache_matchups()
                st.session_state.matchup_data_v2 = matchup

            first_game = st.session_state.loader_v2.games_data[0] if st.session_state.loader_v2.games_data else {}
            game_date = first_game.get("datetime", "")[:10] if first_game else datetime.now().strftime("%Y-%m-%d")
            
            engine_v2 = PropsEngineV2()
            bilheteiro_v2 = BilheteiroV2(date=game_date)
            
            injured = st.session_state.loader_v2.get_injured_players()
            questionable = st.session_state.loader_v2.get_questionable_players()
            
            all_props = []
            
            risks = {}
            if st.session_state.loader_v2.teams_data:
                risks = analyze_games_blowout_risk(
                    st.session_state.loader_v2.games_data,
                    st.session_state.stats_v2,
                    injured,
                    st.session_state.loader_v2.teams_data,
                )
            
            for game in st.session_state.loader_v2.games_data:
                risk = risks.get(game["id"], {})
                
                game_props = engine_v2.generate_props_for_game(
                    game,
                    st.session_state.stats_v2,
                    injured,
                    questionable,
                    st.session_state.loader_v2.teams_data,
                    matchup,
                    risk,
                )
                all_props.extend(game_props)
            
            for prop in all_props:
                prop["confidence"] = engine_v2.get_confidence_score(prop)
                prop["aggressiveness"] = engine_v2.calculate_aggressiveness(
                    prop.get("line", 0),
                    prop.get("season_avg", 0),
                    prop.get("last5_avg", 0),
                )
            
            tickets = bilheteiro_v2._generate_ticket_by_mode(
                all_props,
                st.session_state.loader_v2.games_data,
                mode
            )
            ticket_options = bilheteiro_v2.generate_multi_ticket_options(
                all_props,
                st.session_state.loader_v2.games_data,
                mode,
            )
            
            st.session_state.bilhetes_v2 = tickets
            st.session_state.bilhetes_v2_options = ticket_options
            st.session_state.props_v2 = all_props
            st.session_state.props_v2_generated = True
            st.session_state.bilhetes_v2_attempted = True
            st.session_state.bilhetes_v2_last_mode = mode

            if tickets:
                output_path = bilheteiro_v2.save_all_tickets(
                    tickets,
                    mode=mode,
                    options_by_game=ticket_options,
                )
                st.session_state.bilhetes_v2_output_path = str(output_path)
        
        st.rerun()
    except Exception as e:
        st.session_state.bilhetes_v2 = []
        st.session_state.bilhetes_v2_attempted = True
        st.session_state.bilhetes_v2_error = str(e)
        st.error(f"Erro: {e}")
        import traceback
        st.code(traceback.format_exc())

if st.session_state.get("bilhetes_v2_error"):
    st.error(f"Falha ao gerar bilhetes v2: {st.session_state.bilhetes_v2_error}")

if st.session_state.get("bilhetes_v2"):
    tickets = st.session_state.bilhetes_v2
    
    st.success(f"✅ Gerados {len(tickets)} bilhetes")

    output_path = st.session_state.get("bilhetes_v2_output_path")
    if output_path:
        output_file = Path(output_path)
        if output_file.exists():
            json_data = output_file.read_text(encoding="utf-8")
            col_save1, col_save2 = st.columns(2)
            with col_save1:
                st.success(f"💾 Bilhetes v2 salvos em: `{output_file.name}`")
            with col_save2:
                st.download_button(
                    "📥 Download JSON v2",
                    data=json_data,
                    file_name=output_file.name,
                    mime="application/json",
                    key="download_bilhetes_v2",
                )
    
    for ticket in tickets:
        st.markdown("---")

        st.subheader(f"{ticket.get('away', '')} vs {ticket.get('home', '')}")
        cols = st.columns([1, 3, 1])

        with cols[0]:
            st.metric("Odd Total", f"{ticket.get('odds', 0):.2f}")
            st.metric("Quality Score", f"{ticket.get('quality', 0):.2f}")
            st.metric("Atletas", ticket.get("num_props", len(ticket.get("props", []))))

        with cols[1]:
            for prop in ticket.get("props", []):
                p = prop.get("player", "")
                t = prop.get("type", "")
                l = prop.get("line", 0)
                o = prop.get("dynamic_odds", 0)
                aggr = prop.get("aggressiveness", 0)
                conf = prop.get("confidence", 0)
                odds_source = prop.get("odds_source", "calculated")
                market_line = prop.get("market_line")
                label = PROP_LABELS.get(t, t or "prop")

                aggr_emoji = "🟢" if aggr < 0.15 else "🟡" if aggr < 0.25 else "🔴"

                line_text = f"{l}+ {label}"
                if market_line is not None:
                    line_text = f"modelo {l}+ {label} | mercado {market_line}+ {label}"

                source_text = "Bet365" if odds_source == "api" else "calc"
                st.markdown(
                    f"- **{p}** ({label}): {line_text} | Odd: {o:.2f} [{source_text}] | "
                    f"Aggr: {aggr_emoji} {aggr:.0%} | Conf: {conf:.0f}"
                )

        with cols[2]:
            pass

else:
    if st.session_state.get("bilhetes_v2_attempted"):
        mode_label = st.session_state.get("bilhetes_v2_last_mode", mode)
        props_count = len(st.session_state.get("props_v2", []))
        st.warning(
            f"Nenhum bilhete valido foi encontrado no modo '{mode_label}'. "
            f"O pipeline gerou {props_count} props, mas nenhuma combinacao passou pelos filtros finais."
        )
    else:
        st.info("Clique em 'Gerar Bilhetes v2' para criar os bilhetes.")