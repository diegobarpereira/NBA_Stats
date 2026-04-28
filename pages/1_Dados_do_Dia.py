import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from scrapers.gameread_scraper import fetch_games_from_gameread, fetch_injuries_from_gameread
from utils.scraping_workflow import run_full_stats_refresh


def _init_session():
    if "loader" not in st.session_state:
        from utils.data_loader import DataLoader

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

    if "daily_refresh_summary" not in st.session_state:
        st.session_state.daily_refresh_summary = None

    if "daily_refresh_logs" not in st.session_state:
        st.session_state.daily_refresh_logs = []


def _render_games_section(games_data):
    if not games_data:
        st.info("Nenhum jogo carregado para a data selecionada.")
        return

    st.dataframe(pd.DataFrame(games_data), use_container_width=True, hide_index=True)


def _render_injuries_section(injuries_data):
    if not injuries_data:
        st.info("Nenhuma lesão reportada.")
        return

    if isinstance(injuries_data, dict) and "relatorio_lesoes" in injuries_data:
        rows = []
        for team in injuries_data.get("relatorio_lesoes", {}).get("times", []):
            for player in team.get("jogadores", []):
                rows.append(
                    {
                        "team": team.get("team", ""),
                        "abbr": team.get("abbr", ""),
                        "player": player.get("nome", ""),
                        "status": player.get("status", ""),
                    }
                )
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("Nenhuma lesão reportada.")
        return

    st.dataframe(pd.DataFrame(injuries_data), use_container_width=True, hide_index=True)


def _render_season_section(stats_cache):
    season_rows = [
        {
            "player": name,
            "team": stats.get("team", ""),
            "ppg": stats.get("avgPoints_season", stats.get("ppg", 0)),
            "rpg": stats.get("avgRebounds_season", stats.get("rpg", 0)),
            "apg": stats.get("avgAssists_season", stats.get("apg", 0)),
            "tpg": stats.get("avg3PT_season", stats.get("tpg", 0)),
            "games": stats.get("games_season", stats.get("gp", 0)),
        }
        for name, stats in stats_cache.items()
    ]

    if not season_rows:
        st.info("Season Stats ainda não carregados.")
        return

    st.dataframe(pd.DataFrame(season_rows), use_container_width=True, hide_index=True)


def _render_last5_section(stats_cache):
    last5_rows = [
        {
            "player": name,
            "team": stats.get("team", ""),
            "games_last5": stats.get("games_last5", 0),
            "avgPoints_last5": stats.get("avgPoints_last5", 0),
            "avgRebounds_last5": stats.get("avgRebounds_last5", 0),
            "avgAssists_last5": stats.get("avgAssists_last5", 0),
        }
        for name, stats in stats_cache.items()
        if (stats.get("games_last5") or 0) >= 2
    ]

    if not last5_rows:
        st.info("Last5 ainda não carregado.")
        return

    st.dataframe(pd.DataFrame(last5_rows), use_container_width=True, hide_index=True)


_init_session()

st.title("📋 Dados do Dia")
st.caption("Ao buscar no GameRead, a página já atualiza jogos, lesões, Season Stats e Last5 em sequência.")

col_tz, col_date = st.columns([1, 1])

with col_tz:
    st.markdown("##### 🌎 Fuso Horário")
    timezone_offset = st.selectbox(
        "Selecione",
        options=[-3, -4, -5, -6, -7, -8],
        index=0,
        format_func=lambda value: f"Brasília (GMT{value})" if value == -3 else f"GMT{value}",
        help="Selecione o timezone da sua localização",
        label_visibility="collapsed",
    )

with col_date:
    st.markdown("##### 📅 Data dos Jogos")
    server_now = datetime.now()
    local_dt = server_now + timedelta(hours=timezone_offset)
    today = local_dt.strftime("%Y-%m-%d")
    selected_date = st.text_input("Data", value=today, label_visibility="collapsed")

progress_placeholder = st.empty()
status_placeholder = st.empty()
log_placeholder = st.empty()

if st.button("📥 Atualizar dados do dia", type="primary", use_container_width=True):
    progress_bar = progress_placeholder.progress(0.0, text="Buscando GameRead...")
    log_lines = []

    def on_progress(value: float, message: str) -> None:
        progress_bar.progress(value, text=message)
        status_placeholder.info(message)

    def on_log(message: str) -> None:
        log_lines.append(message)
        log_placeholder.code("\n".join(log_lines[-12:]), language="text")

    try:
        with st.spinner("Buscando jogos, lesões e estatísticas..."):
            games = fetch_games_from_gameread(selected_date)
            injuries = fetch_injuries_from_gameread(selected_date)

            with open(config.DATA_FILES["games"], "w", encoding="utf-8") as games_file:
                json.dump(games, games_file, indent=2, ensure_ascii=False)

            with open(config.DATA_FILES["injuries"], "w", encoding="utf-8") as injuries_file:
                json.dump(injuries, injuries_file, indent=2, ensure_ascii=False)

            st.session_state.loader.load_all()
            refresh_summary = run_full_stats_refresh(
                st.session_state.loader,
                progress_callback=on_progress,
                log_callback=on_log,
            )

            st.session_state.stats = refresh_summary["stats"].copy()
            st.session_state.stats_loaded = bool(st.session_state.stats)
            st.session_state.props_generated = False
            st.session_state.bilhetes_generated = False
            st.session_state.daily_refresh_summary = {
                "games": len(st.session_state.loader.games_data),
                "injuries": len(st.session_state.loader.get_injured_players()) + len(st.session_state.loader.get_questionable_players()),
                "season_players": refresh_summary["season"]["players_saved"],
                "season_expected": refresh_summary["season"]["players_expected"],
                "last5_updated": refresh_summary["last5"]["updated"],
                "last5_errors": refresh_summary["last5"]["errors"],
                "teams": refresh_summary["season"]["teams_needed"],
                "failed_teams": refresh_summary["season"].get("failed_teams", []),
                "used_cached_stats": refresh_summary["season"].get("used_cached_stats", False),
            }
            st.session_state.daily_refresh_logs = log_lines.copy()

        progress_bar.progress(1.0, text="Atualização concluída")
        status_placeholder.success("Dados do dia, Season Stats e Last5 atualizados.")
        st.rerun()
    except Exception as exc:
        status_placeholder.error(f"Erro ao atualizar dados: {exc}")

loader = st.session_state.loader
stats_cache = loader.stats_cache.copy()
games_data = loader.games_data
injuries_data = loader.injuries_data
summary = st.session_state.daily_refresh_summary

st.markdown("---")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Jogos", len(games_data))
m2.metric("Lesões", len(loader.get_injured_players()) + len(loader.get_questionable_players()))
m3.metric("Season Stats", len(stats_cache))
m4.metric("Last5 válidos", sum(1 for stats in stats_cache.values() if (stats.get("games_last5") or 0) >= 2))

if summary:
    summary_message = " | ".join(
        [
            f"Jogos: {summary['games']}",
            f"Lesões: {summary['injuries']}",
            f"Season: {summary['season_players']}/{summary['season_expected']}",
            f"Last5: {summary['last5_updated']} atualizados",
        ]
    )
    if summary.get("used_cached_stats"):
        st.warning(f"{summary_message} | usando cache existente para preservar dados")
    else:
        st.success(summary_message)
    st.caption(f"Times processados: {', '.join(summary['teams'])}")
    if summary.get("failed_teams"):
        st.caption(f"Times sem resposta da ESPN: {', '.join(summary['failed_teams'])}")

if st.session_state.daily_refresh_logs:
    with st.expander("Log do refresh"):
        st.code("\n".join(st.session_state.daily_refresh_logs[-20:]), language="text")

tab_games, tab_season, tab_last5 = st.tabs(["Jogos do dia - Relatorio de lesoes", "Season Stats", "Last5"])

with tab_games:
    st.markdown("### Jogos do dia")
    _render_games_section(games_data)
    st.markdown("### Relatorio de lesoes")
    _render_injuries_section(injuries_data)

with tab_season:
    _render_season_section(stats_cache)

with tab_last5:
    _render_last5_section(stats_cache)
