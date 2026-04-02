from gerador.props_engine import PropsEngine
from gerador.bilheteiro import Bilheteiro
from scrapers.matchup_scraper import fetch_and_cache_matchups
from scrapers.blowout_risk import analyze_games_blowout_risk


def regenerate_props():
    import streamlit as st

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

    game_date = "2026-03-26"
    if st.session_state.loader.games_data:
        first_game = st.session_state.loader.games_data[0]
        dt = first_game.get("datetime", "")
        if dt:
            game_date = dt[:10]

    bilheteiro = Bilheteiro(date=game_date)
    bilheteiro.props_engine = engine
    bilhetes = bilheteiro.generate_multi_game_ticket(all_props, st.session_state.loader.games_data)
    st.session_state.bilhetes = bilhetes
    st.session_state.bilhetes_generated = True
    st.session_state.bilheteiro = bilheteiro
    st.session_state.generated_time = "agora"
