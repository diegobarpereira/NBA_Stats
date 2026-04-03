import streamlit as st
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import config


def _clear_stats_cache():
    cache_path = config.CACHE_FILE
    if cache_path.exists():
        cache_path.unlink()
    if "stats" in st.session_state:
        st.session_state.stats = {}
    if "loader" in st.session_state and hasattr(st.session_state.loader, "stats_cache"):
        st.session_state.loader.stats_cache = {}


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
    if "scrape_log" not in st.session_state:
        st.session_state.scrape_log = ""


_init_session()

st.title("🌐 Scraping de Estatísticas")
st.markdown("Atualize as estatísticas dos jogadores a partir do ESPN.")

st.info("💡 Para buscar jogos e lesões, vá na aba **Dados do Dia** primeiro.")

col_auto1, col_auto2 = st.columns(2)

with col_auto1:
    st.markdown("#### 📊 Status Atual")
    st.metric("Jogos do Dia", len(st.session_state.loader.games_data))
    injured = st.session_state.loader.get_injured_players()
    questionable = st.session_state.loader.get_questionable_players()
    st.metric("Lesionados", len(injured) + len(questionable))

st.markdown("---")

if not st.session_state.loader.games_data:
    st.error("⚠️ Carregue os jogos do dia primeiro na aba **Dados do Dia**.")
    st.stop()

if not st.session_state.loader.teams_data:
    st.error("⚠️ O arquivo `nba_por_equipe.json` não foi encontrado.")
    st.stop()

teams_needed = set()
for game in st.session_state.loader.games_data:
    ha = config.TEAM_NAME_MAPPING.get(game["home"], game["home"])
    aa = config.TEAM_NAME_MAPPING.get(game["away"], game["away"])
    teams_needed.add(ha)
    teams_needed.add(aa)

total_players = sum(
    len(t["players"]) for t in st.session_state.loader.teams_data
    if config.TEAM_NAME_MAPPING.get(t["team"], t["team"]) in teams_needed
)

col1, col2, col3 = st.columns(3)
col1.metric("📊 Jogadores em Cache", len(st.session_state.stats))
col2.metric("🏀 Times nos Jogos", len(teams_needed))
col3.metric("👥 Jogadores Esperados", total_players)

st.markdown("---")

st.markdown("---")
st.markdown("#### 🚀 Scraping de Season Stats")

log_area = st.empty()
log_container = st.container()

with log_container:
    log_placeholder = st.empty()
    log_text = st.session_state.get("scrape_log", "")

if st.button("🚀 Iniciar Scraping (Season Stats)", type="primary", use_container_width=True):
    if not teams_needed:
        log_text = "❌ Erro: Nenhum jogo encontrado. Carregue os dados do dia primeiro."
        log_placeholder.error(log_text)
    else:
        _clear_stats_cache()
        log_text = f"🗑️ Cache limpo. Times a processar: {', '.join(sorted(teams_needed))}\n"
        log_placeholder.text(log_text)

        from scrapers.espn_scraper import ESPNScraper
        from concurrent.futures import ThreadPoolExecutor, as_completed

        scraper = ESPNScraper()
        loader = st.session_state.loader
        loader.load_teams()
        results = {}

        log_text += "\n🏀 Carregando times (multithread)..."
        log_placeholder.text(log_text)

        def fetch_team_stats(team_abbr):
            for attempt in range(1, 4):
                try:
                    team_ts = scraper.get_team_stats(team_abbr)
                    if team_ts:
                        return team_abbr, team_ts
                except Exception:
                    pass
            return team_abbr, None

        team_stats_cache = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(fetch_team_stats, abbr): abbr for abbr in sorted(teams_needed)}
            for future in as_completed(futures):
                abbr, team_ts = future.result()
                if team_ts:
                    team_stats_cache[abbr] = team_ts
                    log_text += f" {abbr}✓"
                else:
                    log_text += f" {abbr}✗"
                log_placeholder.text(log_text)

        log_text += "\n\n🔍 Buscando jogadores (multithread)..."
        log_placeholder.text(log_text)

        def scrape_player(args):
            team_abbr, team_ts, player = args
            name = player["name"]
            ps = scraper._match_player_from_cache(name, team_ts, team_abbr)
            if not ps:
                try:
                    ps = scraper.get_player_stats(name, team_abbr)
                except Exception:
                    ps = scraper._match_player_from_cache(name, team_ts, team_abbr)
            return name, ps

        all_tasks = []
        for team_abbr, team_ts in team_stats_cache.items():
            team_players = [
                p for t in loader.teams_data
                if config.TEAM_NAME_MAPPING.get(t["team"], t["team"]) == team_abbr
                for p in t["players"]
            ]
            for player in team_players:
                if player["name"] not in results:
                    all_tasks.append((team_abbr, team_ts, player))

        processed = 0
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(scrape_player, task): task for task in all_tasks}
            for future in as_completed(futures):
                name, ps = future.result()
                if ps:
                    results[name] = ps
                processed += 1
                if processed % 10 == 0:
                    log_text = log_text.split("🔍")[0] + f"🔍 {processed}/{len(all_tasks)} jogadores..."
                    log_placeholder.text(log_text)

        loader.save_stats_cache(results)
        st.session_state.stats = results.copy()
        st.session_state.stats_loaded = True
        st.session_state.scrape_log = log_text
        st.session_state.loader.stats_cache = results.copy()
        log_text += f"\n\n✅ Concluído! {len(results)} jogadores salvos."
        log_placeholder.success(log_text)
        st.rerun()

if log_text:
    with st.expander("📋 Log do Scraping"):
        st.text(log_text)

st.markdown("---")
st.markdown("#### 📋 Status dos Times")

status_data = []
for team_abbr in sorted(teams_needed):
    team_name = config.TEAM_NAME_REVERSE.get(team_abbr, team_abbr)
    players_in_cache = [
        p for p, d in st.session_state.stats.items()
        if d.get("team") == team_name
    ]
    status_data.append({
        "Time": team_name,
        "Abrev": team_abbr,
        "Em Cache": len(players_in_cache),
        "Status": "✅" if len(players_in_cache) > 0 else "❌",
    })

st.dataframe(
    status_data,
    column_config={
        "Time": st.column_config.TextColumn("Time"),
        "Abrev": st.column_config.TextColumn("Abbr"),
        "Em Cache": st.column_config.NumberColumn("Em Cache"),
        "Status": st.column_config.TextColumn("Status"),
    },
    hide_index=True,
    width='stretch',
)

st.markdown("---")
st.markdown("#### 📈 Scraping de Últimos 5 Jogos (Last5)")

has_real_l5 = sum(
    1 for p in st.session_state.stats.values()
    if (p.get("games_last5") or 0) in range(1, 11)
)
has_pid = sum(1 for p in st.session_state.stats.values() if p.get("pid"))

st.info(
    f"📊 {has_real_l5}/{len(st.session_state.stats)} jogadores com Last5 real | "
    f"{has_pid} com player ID | "
    f"{len(st.session_state.stats) - has_pid} sem PID"
)

need_l5 = [
    (name, data) for name, data in st.session_state.stats.items()
    if (data.get("games_last5") or 0) not in range(1, 11)
]
st.caption(f"⏱️ {len(need_l5)} jogadores precisam de Last5")

speed_map = {
    "🐇 Rápido (10 threads)": 0.1,
    "🐢 Suave (5 threads)": 0.25,
    "🚶 Lento (1 thread)": 0.5,
}
speed_options = list(speed_map.keys())
default_idx = st.selectbox(
    "Velocidade",
    speed_options,
    index=0,
    format_func=lambda x: x,
) if len(need_l5) > 0 else None

col_start, col_skip = st.columns([1, 2])
with col_start:
    start_disabled = not need_l5
    start_label = f"📈 Buscar Last5 ({len(need_l5)} jogadores)"
    do_l5 = st.button(start_label, type="secondary", disabled=start_disabled)

if do_l5:
    delay = speed_map.get(default_idx, 0.1)

    progress_bar = st.progress(0, text="Preparando...")
    log_area = st.empty()
    status_text = st.empty()

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from scrapers.espn_scraper import ESPNScraper
    from utils.data_loader import DataLoader
    import time as time_mod

    scraper = ESPNScraper()
    scraper.delay = delay
    loader = DataLoader()
    stats = st.session_state.stats.copy()
    updated = 0
    errors = 0

    players_to_scrape = [
        (name, data) for name, data in stats.items()
        if (data.get("games_last5") or 0) not in range(1, 11)
    ]
    total = len(players_to_scrape)

    def fetch_last5(item):
        name, data = item
        pid = data.get("pid")
        if not pid:
            return name, None
        try:
            return name, scraper.get_player_last5(pid, name)
        except Exception:
            return name, None

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_last5, item): item for item in players_to_scrape}
        done = 0
        for future in as_completed(futures):
            done += 1
            name, last5_data = future.result()

            if last5_data and 1 <= last5_data.get("games", 0) <= 10:
                stats[name]["avgPoints_last5"] = last5_data["ppg"]
                stats[name]["avgRebounds_last5"] = last5_data["rpg"]
                stats[name]["avgAssists_last5"] = last5_data["apg"]
                stats[name]["avg3PT_last5"] = last5_data["tpg"]
                stats[name]["games_last5"] = last5_data["games"]
                updated += 1
            else:
                errors += 1

            pct = done / total
            progress_bar.progress(
                pct,
                text=f"{done}/{total} — {name} {'OK' if last5_data else 'sem dados'}"
            )
            status_text.text(f"Atualizados: {updated} | Erros: {errors}")

            if done % 25 == 0:
                loader.save_stats_cache(stats)
                st.session_state.stats = stats.copy()
                st.session_state.loader.stats_cache = stats.copy()
                time_mod.sleep(0.5)

    loader.save_stats_cache(stats)
    st.session_state.stats = stats.copy()
    st.session_state.loader.stats_cache = stats.copy()
    progress_bar.progress(1.0, text="Concluído!")
    st.success(f"✅ Last5: {updated} atualizados, {errors} sem dados. Cache salvo.")
    st.rerun()

st.markdown("---")
st.markdown("#### 📊 Preview Last5 (Season vs Últimos 5)")

preview_rows = []
for name, p in list(st.session_state.stats.items())[:80]:
    gl5 = p.get("games_last5", 0)
    if 1 <= gl5 <= 10:
        diff_pts = p.get("avgPoints_last5", 0) - p.get("avgPoints_season", 0)
        arrow = "🔺" if diff_pts > 0 else ("🔻" if diff_pts < 0 else "➖")
        preview_rows.append({
            "Jogador": name,
            "Time": (p.get("team", "") or "")[:12],
            "J5": gl5,
            "S-PTS": p.get("avgPoints_season", 0),
            "L5-PTS": p.get("avgPoints_last5", 0),
            "Δ": round(diff_pts, 1),
            "S-REB": p.get("avgRebounds_season", 0),
            "L5-REB": p.get("avgRebounds_last5", 0),
            "S-AST": p.get("avgAssists_season", 0),
            "L5-AST": p.get("avgAssists_last5", 0),
        })

if preview_rows:
    preview_rows.sort(key=lambda x: -x["L5-PTS"])
    st.dataframe(
        preview_rows,
        column_config={
            "Jogador": st.column_config.TextColumn("Jogador", width="medium"),
            "Time": st.column_config.TextColumn("Time", width="small"),
            "J5": st.column_config.NumberColumn("J5", format="%d"),
            "S-PTS": st.column_config.NumberColumn("S-PTS", format="%.1f"),
            "L5-PTS": st.column_config.NumberColumn("L5-PTS", format="%.1f"),
            "Δ": st.column_config.NumberColumn("Δ", format="%.1f"),
            "S-REB": st.column_config.NumberColumn("S-REB", format="%.1f"),
            "L5-REB": st.column_config.NumberColumn("L5-REB", format="%.1f"),
            "S-AST": st.column_config.NumberColumn("S-AST", format="%.1f"),
            "L5-AST": st.column_config.NumberColumn("L5-AST", format="%.1f"),
        },
        hide_index=True,
        width='stretch',
    )
else:
    st.info("Execute o scraping de Last5 para ver a comparação Season vs L5.")
