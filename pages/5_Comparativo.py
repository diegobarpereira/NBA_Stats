import streamlit as st
import sys
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from scrapers.espn_scraper import ESPNScraper


def _normalize_name(name):
    import re
    name = name.lower().replace(".", "").replace("-", " ").replace("'", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name

def _load_comparison_from_file():
    comparison_file = config.DATA_DIR / "comparison_history.json"
    if comparison_file.exists():
        try:
            with open(comparison_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}


def _save_comparison_to_file(data):
    comparison_file = config.DATA_DIR / "comparison_history.json"
    comparison_file.parent.mkdir(parents=True, exist_ok=True)
    with open(comparison_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _init_session():
    if "comparison_history" not in st.session_state:
        st.session_state.comparison_history = []
    if "bet365_selections" not in st.session_state:
        st.session_state.bet365_selections = []
    
    saved = _load_comparison_from_file()
    if saved:
        if "saved_player_last_game" not in st.session_state:
            st.session_state.saved_player_last_game = saved.get("player_last_game", {})
        if "saved_bet365_results" not in st.session_state:
            st.session_state.saved_bet365_results = saved.get("bet365_results", [])
        if "saved_comparison_results" not in st.session_state:
            st.session_state.saved_comparison_results = saved.get("comparison_results", [])


_init_session()

st.set_page_config(page_title="Comparativo", page_icon="📈", layout="wide")

st.markdown("""
<style>
    .hit { color: #2ecc71; font-weight: bold; }
    .miss { color: #e74c3c; font-weight: bold; }
    .push { color: #f39c12; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("📈 Comparativo")
st.markdown("Compare os bilhetes gerados com os resultados reais para ajustar seus filtros.")

try:
    from gerador.performance_analyzer import get_performance_analyzer
    analyzer = get_performance_analyzer()
    summary = analyzer.get_summary()
    
    st.markdown("---")
    st.markdown("### 🎯 Resumo de Performance do Sistema")
    
    total_bets = summary.get("total_bets", 0)
    if total_bets > 0:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total de Apostas Analisadas", total_bets)
        with col2:
            weights = summary.get("suggested_weights", (0.6, 0.4))
            st.metric("Pesos Sugeridos (S/L5)", f"{weights[0]:.1f}/{weights[1]:.1f}")
        
        st.markdown("#### Acurácia por Tipo de Prop:")
        type_acc = summary.get("type_accuracy", {})
        for t, acc in type_acc.items():
            emoji = "🟢" if acc > 0.6 else "🟡" if acc > 0.4 else "🔴"
            st.write(f"{emoji} {t.upper()}: {acc:.1%}")
        
        st.markdown("#### Acurácia por Confiança:")
        conf_acc = summary.get("confidence_accuracy", {})
        for c in sorted(conf_acc.keys())[:5]:
            acc = conf_acc[c]
            emoji = "🟢" if acc > 0.6 else "🟡" if acc > 0.4 else "🔴"
            st.write(f"{emoji} Conf {c}: {acc:.1%}")
        
        st.markdown("#### 💡 Recomendações:")
        recs = summary.get("recommendations", [])
        if recs:
            for r in recs[:5]:
                st.write(r)
        else:
            st.info("Aguardando mais dados para recomendações")
    else:
        st.info("ℹ️ Execute o Comparativo e salve os resultados para ver recomendações")
except Exception as e:
    pass

tab1, tab2 = st.tabs(["🔍 Sistema vs Real", "💰 Minhas Apostas (Bet365)"])

# ==========================================
# TAB 1: Sistema vs Real
# ==========================================
with tab1:
    st.markdown("### Selecione a data dos jogos")

    default_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    selected_date = st.date_input("Data dos jogos", value=datetime.strptime(default_date, "%Y-%m-%d"))
    date_str = selected_date.strftime("%Y-%m-%d")

    output_dir = config.OUTPUT_DIR
    all_bilhetes = []

    if output_dir.exists():
        for f in output_dir.glob(f"bilhetes_{date_str}*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    all_bilhetes.append({"file": f.name, "data": data})
            except Exception:
                pass

    if not all_bilhetes:
        st.info(f"ℹ️ Nenhum bilhete encontrado para {date_str}")
    else:
        st.success(f"📂 {len(all_bilhetes)} arquivo(s) de bilhetes encontrado(s)")

        col_fetch, col_load = st.columns([1, 2])
        with col_fetch:
            if "compare_state" not in st.session_state:
                st.session_state.compare_state = None

            saved_count = len(st.session_state.get("saved_player_last_game", {}))
            if saved_count > 0:
                st.success(f"💾 {saved_count} jogadores em cache (do último carregamento)")
            else:
                st.info("Clique em 'Buscar Stats Reais' para carregar os resultados dos jogos")
            
            if st.button("🔄 Buscar Stats Reais", type="primary", use_container_width=True):
                all_players_needed = set()
                for bh in all_bilhetes:
                    for ticket in bh["data"].get("tickets", []):
                        for prop in ticket.get("props", []):
                            all_players_needed.add(prop.get("player", ""))

                all_teams_abbr = set()
                for bh in all_bilhetes:
                    for ticket in bh["data"].get("tickets", []):
                        game_id = ticket.get("game_id", "")
                        if game_id:
                            parts = game_id.split("_")
                            if len(parts) >= 2:
                                teams = parts[0].split("vs")
                                if len(teams) == 2:
                                    # Keep abbreviations as-is (don't convert to full names)
                                    all_teams_abbr.add(teams[0])
                                    all_teams_abbr.add(teams[1])

                st.session_state.compare_state = {
                    "players_needed": list(all_players_needed),
                    "teams_abbr": list(all_teams_abbr),
                    "phase": "init",
                }
                st.rerun()

            if st.session_state.compare_state:
                state = st.session_state.compare_state
                players_needed = set(state["players_needed"])
                teams_abbr = state["teams_abbr"]

                if state["phase"] == "init":
                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    scraper = ESPNScraper()
                    
                    def fetch_team(abbr):
                        return abbr, scraper.get_team_stats(abbr)
                    
                    all_team_stats = {}
                    with ThreadPoolExecutor(max_workers=4) as executor:
                        futures = {executor.submit(fetch_team, abbr): abbr for abbr in teams_abbr}
                        for future in as_completed(futures):
                            abbr, ts = future.result()
                            if ts:
                                all_team_stats[abbr] = ts

                    all_playable = []
                    players_normalized = {_normalize_name(p): p for p in players_needed}
                    for abbr, ts in all_team_stats.items():
                        for p in ts:
                            pname = p.get("name", "")
                            pname_norm = _normalize_name(pname)
                            original_name = players_normalized.get(pname_norm)
                            if original_name and p.get("pid"):
                                all_playable.append((p["name"], p["pid"]))

                    state["team_stats"] = all_team_stats
                    state["all_playable"] = all_playable
                    state["phase"] = "players"
                    state["processed"] = 0
                    state["player_last_game"] = {}
                    st.rerun()

                elif state["phase"] == "players":
                    all_playable = state["all_playable"]
                    processed = state["processed"]
                    batch_size = min(8, len(all_playable) - processed)
                    
                    if batch_size <= 0:
                        st.session_state.player_last_game = state["player_last_game"]
                        st.success(f"✅ Stats de {len(state['player_last_game'])}/{len(players_needed)} jogadores carregados!")
                        st.session_state.compare_state = None
                        
                        st.session_state.saved_player_last_game = state["player_last_game"].copy()
                        _save_comparison_to_file({
                            "player_last_game": st.session_state.saved_player_last_game,
                            "bet365_results": st.session_state.get("saved_bet365_results", []),
                            "comparison_results": st.session_state.get("saved_comparison_results", []),
                        })
                        
                        st.rerun()

                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    
                    batch = all_playable[processed:processed + batch_size]
                    
                    def fetch_last_game(args):
                        name, pid = args
                        scraper_i = ESPNScraper()
                        last5 = scraper_i.get_player_last5(pid, name, last_game_only=True)
                        if last5 and last5.get("games", 0) > 0:
                            return name, {
                                "pts": int(last5.get("ppg", 0)),
                                "reb": int(last5.get("rpg", 0)),
                                "ast": int(last5.get("apg", 0)),
                                "fg3": int(last5.get("tpg", 0)),
                            }
                        return name, None

                    with ThreadPoolExecutor(max_workers=4) as executor:
                        futures = {executor.submit(fetch_last_game, p): p for p in batch}
                        for future in as_completed(futures):
                            name, data = future.result()
                            if data:
                                state["player_last_game"][name] = data

                    state["processed"] = processed + batch_size
                    progress = state["processed"] / len(all_playable)
                    st.progress(progress, text=f"Jogadores: {state['processed']}/{len(all_playable)}")
                    st.rerun()

        with col_load:
            options = [b["file"] for b in all_bilhetes]
            default_idx = 0
            if "selected_bilhete_file" in st.session_state and st.session_state.selected_bilhete_file in options:
                default_idx = options.index(st.session_state.selected_bilhete_file)
            
            selected_file = st.selectbox(
                "Arquivo de bilhetes",
                options=options,
                index=default_idx,
                key="bilhete_selector",
            )
            
            if selected_file:
                st.session_state.selected_bilhete_file = selected_file

        if selected_file:
            selected_bh = next(b for b in all_bilhetes if b["file"] == selected_file)
            bilhete_data = selected_bh["data"]

            st.markdown("---")
            st.markdown("### 🎫 Comparação de Props")

            comparison_results = []
            total_hit = 0
            total_miss = 0
            total_push = 0

            for ticket in bilhete_data.get("tickets", []):
                game_id = ticket.get("game_id", "")
                home = ticket.get("home", "")
                away = ticket.get("away", "")
                game_label = f"{away} @ {home}"

                for prop in ticket.get("props", []):
                    player = prop.get("player", "")
                    prop_type = prop.get("abbrev", "")
                    line = prop.get("line", 0)

                    actual = 0
                    data_source = "none"

                    player_last_game = st.session_state.get("player_last_game", {})
                    if not player_last_game and "saved_player_last_game" in st.session_state:
                        player_last_game = st.session_state.saved_player_last_game
                        data_source = "saved"
                    
                    if not player_last_game:
                        data_source = "empty"
                    
                    pl = player_last_game.get(player, {})
                    
                    # Also try with normalized name
                    if not pl:
                        player_norm = _normalize_name(player)
                        for key in player_last_game:
                            if _normalize_name(key) == player_norm:
                                pl = player_last_game[key]
                                break
                    
                    if pl:
                        data_source = "found"
                        if prop_type == "PTS":
                            actual = pl.get("pts", 0)
                        elif prop_type == "REB":
                            actual = pl.get("reb", 0)
                        elif prop_type == "AST":
                            actual = pl.get("ast", 0)
                        elif prop_type == "3PM":
                            actual = pl.get("fg3", 0)

                    diff = actual - line if actual > 0 else None
                    result = "SEM DADOS"
                    if diff is not None:
                        if diff > 0:
                            result = "✅ ACERTOU"
                            total_hit += 1
                        elif diff < -0.5:
                            result = "❌ ERROU"
                            total_miss += 1
                        else:
                            result = "➖ PUSH"
                            total_push += 1

                    comparison_results.append({
                        "game": game_label,
                        "player": player,
                        "type": prop_type,
                        "line": line,
                        "actual": actual if actual > 0 else "?",
                        "diff": f"{diff:+.1f}" if diff is not None else "?",
                        "result": result,
                        "conf": prop.get("confidence", 0),
                        "trend": prop.get("advanced_filters", {}).get("trend", "stable"),
                        "consistency": prop.get("advanced_filters", {}).get("consistency", 0),
                        "is_home": prop.get("is_home", True),
                        "over_under": prop.get("over_under", "Over"),
                        "matchup_mult": prop.get("matchup_mult", 1.0),
                    })

            if comparison_results:
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("✅ Acertos", total_hit)
                col2.metric("❌ Erros", total_miss)
                col3.metric("➖ Push", total_push)
                col4.metric("Total", total_hit + total_miss + total_push)

                if total_hit + total_miss > 0:
                    hit_rate = total_hit / (total_hit + total_miss) * 100
                    st.metric("🎯 Taxa de Acerto", f"{hit_rate:.1f}%")

                st.dataframe(
                    comparison_results,
                    column_config={
                        "game": st.column_config.TextColumn("Jogo", width="medium"),
                        "player": st.column_config.TextColumn("Jogador", width="medium"),
                        "type": st.column_config.TextColumn("Tipo"),
                        "line": st.column_config.NumberColumn("Linha", format="%.1f"),
                        "actual": st.column_config.NumberColumn("Real", format="%.1f"),
                        "diff": st.column_config.TextColumn("Diff"),
                        "result": st.column_config.TextColumn("Resultado"),
                        "conf": st.column_config.NumberColumn("Conf", format="%d"),
                        "trend": st.column_config.TextColumn("Trend"),
                        "consistency": st.column_config.TextColumn("Consist."),
                        "is_home": st.column_config.TextColumn("H/A"),
                    },
                    hide_index=True,
                    use_container_width=True,
                )

                st.markdown("---")
                st.markdown("### 📊 Análise por Tipo de Prop")

                type_analysis = {}
                for cr in comparison_results:
                    t = cr["type"]
                    if t not in type_analysis:
                        type_analysis[t] = {"hit": 0, "miss": 0, "push": 0}
                    if "ACERTOU" in cr["result"]:
                        type_analysis[t]["hit"] += 1
                    elif "ERROU" in cr["result"]:
                        type_analysis[t]["miss"] += 1
                    else:
                        type_analysis[t]["push"] += 1

                type_rows = []
                for t, stats in type_analysis.items():
                    total = stats["hit"] + stats["miss"]
                    rate = stats["hit"] / total * 100 if total > 0 else 0
                    type_rows.append({
                        "tipo": t,
                        "acertos": stats["hit"],
                        "erros": stats["miss"],
                        "push": stats["push"],
                        "taxa": f"{rate:.1f}%",
                    })

                if type_rows:
                    st.dataframe(
                        type_rows,
                        column_config={
                            "tipo": st.column_config.TextColumn("Tipo"),
                            "acertos": st.column_config.NumberColumn("✅"),
                            "erros": st.column_config.NumberColumn("❌"),
                            "push": st.column_config.NumberColumn("➖"),
                            "taxa": st.column_config.TextColumn("Taxa"),
                        },
                        hide_index=True,
                    )

                st.markdown("---")
                st.markdown("### 📈 Análise por Confiança")

                conf_analysis = {}
                for cr in comparison_results:
                    conf = cr.get("conf", 0)
                    if conf not in conf_analysis:
                        conf_analysis[conf] = {"hit": 0, "miss": 0, "push": 0}
                    if "ACERTOU" in cr["result"]:
                        conf_analysis[conf]["hit"] += 1
                    elif "ERROU" in cr["result"]:
                        conf_analysis[conf]["miss"] += 1
                    else:
                        conf_analysis[conf]["push"] += 1

                conf_rows = []
                for conf in sorted(conf_analysis.keys()):
                    stats = conf_analysis[conf]
                    total = stats["hit"] + stats["miss"]
                    rate = stats["hit"] / total * 100 if total > 0 else 0
                    conf_rows.append({
                        "conf": conf,
                        "acertos": stats["hit"],
                        "erros": stats["miss"],
                        "taxa": f"{rate:.1f}%",
                        "total": total,
                    })

                if conf_rows:
                    st.dataframe(
                        conf_rows,
                        column_config={
                            "conf": st.column_config.TextColumn("Conf"),
                            "acertos": st.column_config.NumberColumn("✅"),
                            "erros": st.column_config.NumberColumn("❌"),
                            "taxa": st.column_config.TextColumn("Taxa"),
                            "total": st.column_config.NumberColumn("Total"),
                        },
                        hide_index=True,
                    )

                st.markdown("---")
                st.markdown("### 🎯 Análise de Linha (Over vs Under)")

                line_analysis = {"Over": {"hit": 0, "miss": 0}, "Under": {"hit": 0, "miss": 0}}
                for cr in comparison_results:
                    line_val = cr.get("line", 0)
                    over_under = "Over" if line_val > 0 else "Under"
                    if "ACERTOU" in cr["result"]:
                        line_analysis[over_under]["hit"] += 1
                    elif "ERROU" in cr["result"]:
                        line_analysis[over_under]["miss"] += 1

                line_rows = []
                for ou, stats in line_analysis.items():
                    total = stats["hit"] + stats["miss"]
                    rate = stats["hit"] / total * 100 if total > 0 else 0
                    line_rows.append({
                        "tipo": ou,
                        "acertos": stats["hit"],
                        "erros": stats["miss"],
                        "taxa": f"{rate:.1f}%",
                    })

                if line_rows:
                    st.dataframe(
                        line_rows,
                        column_config={
                            "tipo": st.column_config.TextColumn("Tipo"),
                            "acertos": st.column_config.NumberColumn("✅"),
                            "erros": st.column_config.NumberColumn("❌"),
                            "taxa": st.column_config.TextColumn("Taxa"),
                        },
                        hide_index=True,
                    )

                st.markdown("---")
                st.markdown("### 💡 Sugestões de Ajuste")

                suggestions = []

                for t, stats in type_analysis.items():
                    total = stats["hit"] + stats["miss"]
                    if total > 0:
                        rate = stats["hit"] / total * 100
                        if rate < 40:
                            suggestions.append(f"⚠️ {t}: Taxa baixa ({rate:.1f}%) - Considere reduzir peso ou aumentar linha")
                        elif rate > 70:
                            suggestions.append(f"✅ {t}: Excelente ({rate:.1f}%) - Pode aumentar confiança")

                for conf in sorted(conf_analysis.keys()):
                    stats = conf_analysis[conf]
                    total = stats["hit"] + stats["miss"]
                    if total >= 3:
                        rate = stats["hit"] / total * 100
                        if conf >= 9 and rate < 50:
                            suggestions.append(f"⚠️ Conf {conf}: Acurácia baixa ({rate:.1f}%) - Revisar critérios de alta confiança")
                        elif conf <= 6 and rate > 70:
                            suggestions.append(f"💡 Conf {conf}: Acurácia boa ({rate:.1f}%) - Pode considerar aumentar confiança")

                if line_rows:
                    for lr in line_rows:
                        if lr["tipo"] in line_analysis:
                            stats = line_analysis[lr["tipo"]]
                            total = stats["hit"] + stats["miss"]
                            if total >= 3:
                                rate = stats["hit"] / total * 100
                                if rate > 80:
                                    suggestions.append(f"📈 {lr['tipo']}: Acurácia alta ({rate:.1f}%) - Sistema favorece esse tipo de linha")
                                elif rate < 40:
                                    suggestions.append(f"📉 {lr['tipo']}: Acurácia baixa ({rate:.1f}%) - Revisar linhas {lr['tipo']}")

                if suggestions:
                    for s in suggestions:
                        st.write(s)
                else:
                    st.info("Aguardando mais dados para gerar sugestões")

                st.markdown("---")
                st.markdown("### 💾 Salvar para Análise")

                if st.button("💾 Salvar Resultados"):
                    history_entry = {
                        "date": date_str,
                        "comparison_results": comparison_results,
                        "type_analysis": type_analysis,
                        "conf_analysis": conf_analysis,
                        "line_analysis": line_analysis,
                        "trend_analysis": {},
                        "consistency_analysis": {},
                        "home_away_analysis": {},
                    }

                    # Aggregate trend, consistency, home/away analysis
                    for cr in comparison_results:
                        # Trend analysis
                        trend = cr.get("trend", "stable")
                        if trend not in history_entry["trend_analysis"]:
                            history_entry["trend_analysis"][trend] = {"hit": 0, "miss": 0}
                        if "ACERTOU" in cr["result"]:
                            history_entry["trend_analysis"][trend]["hit"] += 1
                        elif "ERROU" in cr["result"]:
                            history_entry["trend_analysis"][trend]["miss"] += 1

                        # Consistency analysis
                        cons = cr.get("consistency", 0)
                        if cons >= 70:
                            key = "high"
                        elif cons >= 40:
                            key = "medium"
                        else:
                            key = "low"
                        if key not in history_entry["consistency_analysis"]:
                            history_entry["consistency_analysis"][key] = {"hit": 0, "miss": 0}
                        if "ACERTOU" in cr["result"]:
                            history_entry["consistency_analysis"][key]["hit"] += 1
                        elif "ERROU" in cr["result"]:
                            history_entry["consistency_analysis"][key]["miss"] += 1

                        # Home/Away analysis
                        is_home = cr.get("is_home", True)
                        ha_key = "home" if is_home else "away"
                        if ha_key not in history_entry["home_away_analysis"]:
                            history_entry["home_away_analysis"][ha_key] = {"hit": 0, "miss": 0}
                        if "ACERTOU" in cr["result"]:
                            history_entry["home_away_analysis"][ha_key]["hit"] += 1
                        elif "ERROU" in cr["result"]:
                            history_entry["home_away_analysis"][ha_key]["miss"] += 1
                    
                    history_file = config.DATA_DIR / "performance_history.json"
                    history_file.parent.mkdir(parents=True, exist_ok=True)
                    
                    existing = []
                    if history_file.exists():
                        try:
                            with open(history_file, "r", encoding="utf-8") as f:
                                existing = json.load(f)
                        except:
                            pass
                    
                    existing.append(history_entry)
                    
                    with open(history_file, "w", encoding="utf-8") as f:
                        json.dump(existing, f, ensure_ascii=False, indent=2)
                    
                    st.success(f"✅ Salvo! Total de {len(existing)} registros")

# ==========================================
# TAB 2: Minhas Apostas (Bet365)
# ==========================================
with tab2:
    st.markdown("### Cole o HTML ou JSON do bilhete da Bet365")

    input_type = st.radio("Formato de entrada", ["HTML", "JSON"], format_func=lambda x: "HTML (Inspecionar)" if x == "HTML" else "JSON (Extensão)")

    raw_input = st.text_area(
        "Cole aqui o conteúdo",
        height=200,
        placeholder='<div><span class="myb-OpenBetBetBuilderSelection_SentenceText">...</span>' if input_type == "HTML" else '[{"jogo": "...", "selecoes": [...]}]',
    )

    if raw_input:
        st.markdown("---")
        st.markdown("### 🎯 Seleções Extraídas")

        selections = []

        if input_type == "JSON":
            try:
                clean_input = raw_input.strip()
                clean_input = re.sub(r'^📋[^\[]*\[', '[', clean_input, flags=re.DOTALL)
                clean_input = clean_input.strip()
                if not clean_input.startswith('['):
                    bracket_idx = clean_input.find('[')
                    if bracket_idx >= 0:
                        clean_input = clean_input[bracket_idx:]
                bets = json.loads(clean_input)
                
                for bet in bets:
                    jogo = bet.get("jogo", "")
                    odd = bet.get("odd", 0)
                    for sel in bet.get("selecoes", []):
                        player = sel.get("selecao", "")
                        stat = sel.get("stat", "")
                        valor = sel.get("valor", "")

                        prop_type = "PTS"
                        if "Pontos" in stat:
                            prop_type = "PTS"
                        elif "Rebotes" in stat or "Rebatidas" in stat:
                            prop_type = "REB"
                        elif "Assistências" in stat:
                            prop_type = "AST"
                        elif "Triplos" in stat or "3PM" in stat:
                            prop_type = "3PM"

                        is_under = "Baixa" in stat or "Under" in stat
                        over_under = "Under" if is_under else "Over"

                        line_match = re.search(r"(\d+\.?\d*)", valor)
                        line = float(line_match.group(1)) if line_match else 0

                        selections.append({
                            "player": player,
                            "type": prop_type,
                            "line": line,
                            "over_under": over_under,
                            "jogo": jogo,
                            "odd": odd,
                        })
            except json.JSONDecodeError as e:
                st.error(f"❌ Erro ao parsear JSON: {e}")

        else:
            pattern = r'<span class="myb-OpenBetBetBuilderSelection_SentenceText[^>]*>([^<]+)</span>'
            matches = re.findall(pattern, raw_input)

            for m in matches:
                m = m.strip()
                if m:
                    parts = m.split(" - ")
                    if len(parts) >= 2:
                        player = parts[0].strip()
                        line_info = parts[1].strip()

                        prop_type = "PTS"
                        if "Pontos" in line_info:
                            prop_type = "PTS"
                        elif "Rebatidas" in line_info or "Reb" in line_info:
                            prop_type = "REB"
                        elif "Assistências" in line_info or "Ast" in line_info:
                            prop_type = "AST"
                        elif "Triplos" in line_info or "3PM" in line_info:
                            prop_type = "3PM"

                        over_under = "Over"
                        if "-" in line_info:
                            over_under = "Under"

                        line_match = re.search(r"(\d+\.?\d*)", line_info)
                        line = float(line_match.group(1)) if line_match else 0

                        selections.append({
                            "player": player,
                            "type": prop_type,
                            "line": line,
                            "over_under": over_under,
                        })

        if selections:
            st.session_state.bet365_selections = selections

            for i, sel in enumerate(selections):
                jogo_tag = f" ({sel.get('jogo', '')})" if sel.get("jogo") else ""
                st.write(f"{i+1}. **{sel['player']}** - {sel['over_under']} {sel['line']} {sel['type']}{jogo_tag}")

            st.markdown("---")
            st.markdown("### 🔍 Buscar Resultados Reais")

            # Load cached player stats
            saved_data = _load_comparison_from_file()
            cached_players = saved_data.get("player_last_game", {}) if saved_data else {}
            
            if cached_players:
                st.info(f"📦 Cache disponível: {len(cached_players)} jogadores")
            
            # Get unique players from selections
            unique_players = list(set(sel.get("player", "") for sel in selections))
            players_to_fetch = [p for p in unique_players if p not in cached_players]
            
            if players_to_fetch:
                st.warning(f"⚠️ {len(players_to_fetch)} jogadores não estão em cache e precisam ser buscados")
            
            if st.button("📊 Buscar Stats dos Jogadores"):
                with st.spinner("Buscando stats..."):
                    from scrapers.espn_scraper import ESPNScraper
                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    
                    team_abbrs = ["LAL", "LAC", "GSW", "PHX", "SAS", "DAL", "HOU", "MEM", 
                                  "NOP", "MIN", "OKC", "DEN", "UTA", "POR", "SAC",
                                  "BOS", "NYK", "BKN", "PHI", "TOR", "CHI", "CLE", "IND", 
                                  "DET", "MIL", "ATL", "CHA", "MIA", "ORL", "WAS"]

                    scraper = ESPNScraper()
                    
                    team_players = {}
                    for abbr in team_abbrs:
                        ts = scraper.get_team_stats(abbr)
                        if ts:
                            for p in ts:
                                name = p.get("name", "").lower()
                                if name not in team_players:
                                    team_players[name] = {"pid": p.get("pid"), "abbr": abbr}

                    st.success(f"✅ {len(team_players)} jogadores carregados")

                    def find_last_game(name):
                        # First check cache
                        cached = cached_players.get(name)
                        if cached:
                            return cached
                        
                        # Also check with normalized name
                        for cached_name, cached_data in cached_players.items():
                            if _normalize_name(cached_name) == _normalize_name(name):
                                return cached_data
                        
                        search_name = name.lower().strip()
                        player_info = team_players.get(search_name)
                        
                        if not player_info:
                            search_base = search_name.replace(" jr", "").replace(" jr.", "").strip()
                            for pname, pinfo in team_players.items():
                                pbase = pname.replace(" jr", "").replace(" jr.", "").strip()
                                if search_base == pbase or search_base in pname or pname in search_base:
                                    player_info = pinfo
                                    break
                        
                        if player_info and player_info.get("pid"):
                            scraper_i = ESPNScraper()
                            last5 = scraper_i.get_player_last5(player_info["pid"], name, last_game_only=True)
                            if last5:
                                return {
                                    "pts": int(last5.get("ppg", 0)),
                                    "reb": int(last5.get("rpg", 0)),
                                    "ast": int(last5.get("apg", 0)),
                                    "fg3": int(last5.get("tpg", 0)),
                                }
                        return None

                    results = []
                    fetched_players = {}
                    for i, sel in enumerate(selections):
                        with st.expander(f"{i+1}. {sel['player']}"):
                            last_game = find_last_game(sel["player"])
                            if last_game:
                                fetched_players[sel["player"]] = last_game
                                actual = 0
                                if sel["type"] == "PTS":
                                    actual = last_game.get("pts", 0)
                                elif sel["type"] == "REB":
                                    actual = last_game.get("reb", 0)
                                elif sel["type"] == "AST":
                                    actual = last_game.get("ast", 0)
                                elif sel["type"] == "3PM":
                                    actual = last_game.get("fg3", 0)

                                hit = False
                                if sel["over_under"] == "Over":
                                    hit = actual >= sel["line"]
                                else:
                                    hit = actual <= sel["line"]

                                results.append({
                                    "player": sel["player"],
                                    "type": sel["type"],
                                    "line": sel["line"],
                                    "over_under": sel["over_under"],
                                    "actual": actual,
                                    "result": "✅ ACERTOU" if hit else "❌ ERROU",
                                    "trend": "unknown",
                                    "consistency": 50,
                                    "is_home": True,
                                })
                                st.write(f"Feito: {actual} | Linha: {sel['line']} | {sel['over_under']} → {'✅' if hit else '❌'}")
                            else:
                                results.append({
                                    "player": sel["player"],
                                    "type": sel["type"],
                                    "line": sel["line"],
                                    "over_under": sel["over_under"],
                                    "actual": "?",
                                    "result": "❓ NÃO ENCONTRADO",
                                    "trend": "unknown",
                                    "consistency": 50,
                                    "is_home": True,
                                })
                                st.write("Jogador não encontrado nos elencos")

                    # Merge fetched players with cached ones
                    all_players = cached_players.copy()
                    all_players.update(fetched_players)
                    
                    st.session_state.bet365_results = results
                    st.session_state.saved_bet365_results = results.copy()
                    _save_comparison_to_file({
                        "player_last_game": all_players,
                        "bet365_results": st.session_state.saved_bet365_results,
                        "comparison_results": st.session_state.get("saved_comparison_results", []),
                    })

            if "bet365_results" in st.session_state and st.session_state.bet365_results:
                results = st.session_state.bet365_results
            elif "saved_bet365_results" in st.session_state and st.session_state.saved_bet365_results:
                results = st.session_state.saved_bet365_results
            else:
                results = []

            if results:
                hits = sum(1 for r in results if "ACERTOU" in r["result"])
                misses = sum(1 for r in results if "ERROU" in r["result"])

                col1, col2 = st.columns(2)
                col1.metric("✅ Acertos", hits)
                col2.metric("❌ Erros", misses)

                st.dataframe(
                    results,
                    column_config={
                        "player": st.column_config.TextColumn("Jogador"),
                        "type": st.column_config.TextColumn("Tipo"),
                        "line": st.column_config.NumberColumn("Linha", format="%.1f"),
                        "over_under": st.column_config.TextColumn("O/U"),
                        "actual": st.column_config.NumberColumn("Real", format="%.1f"),
                        "result": st.column_config.TextColumn("Resultado"),
                    },
                    hide_index=True,
                )

                st.markdown("---")
                if st.button("💾 Salvar Apostas para Análise"):
                    history_entry = {
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "selections": st.session_state.bet365_selections,
                        "results": st.session_state.get("bet365_results", []),
                    }
                    st.session_state.comparison_history.append(history_entry)
                    st.success("✅ Apostas salvas!")

        else:
            st.warning("Nenhuma seleção encontrada no HTML fornecido.")
            st.info("💡 Dica: Use o inspecionador do navegador (F12) para encontrar o elemento com a classe 'myb-OpenBetBetBuilderSelection_SentenceText' e copie o HTML.")

    if st.session_state.comparison_history:
        st.markdown("---")
        st.markdown("### 📜 Histórico de Apostas")

        for i, entry in enumerate(st.session_state.comparison_history):
            st.markdown(f"**Data:** {entry['date']} | **Apostas:** {len(entry['selections'])}")