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
from gerador.performance_analyzer import save_calibration_snapshot, save_mode_backtest_summary


def _normalize_name(name):
    import re
    name = name.lower().replace(".", "").replace("-", " ").replace("'", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _build_team_aliases() -> Dict[str, str]:
    aliases = {}
    for full_name, abbr in config.TEAM_NAME_MAPPING.items():
        aliases[_normalize_name(full_name)] = abbr
        aliases[_normalize_name(abbr)] = abbr

        parts = full_name.split()
        if parts:
            aliases[_normalize_name(parts[-1])] = abbr
        if len(parts) >= 2:
            aliases[_normalize_name(" ".join(parts[-2:]))] = abbr
        if len(parts) >= 3:
            aliases[_normalize_name(" ".join(parts[1:]))] = abbr

    aliases.update({
        "phx suns": "PHX",
        "okc thunder": "OKC",
        "orl magic": "ORL",
        "det pistons": "DET",
        "la lakers": "LAL",
        "la clippers": "LAC",
        "gs warriors": "GSW",
        "sa spurs": "SAS",
        "ny knicks": "NYK",
        "no pelicans": "NOP",
    })
    return aliases


TEAM_ALIASES = _build_team_aliases()


def _resolve_team_abbr(team_text: str) -> Optional[str]:
    normalized = _normalize_name(team_text)
    if not normalized:
        return None

    first_token = normalized.split()[0].upper()
    if first_token in set(config.TEAM_NAME_MAPPING.values()):
        return first_token

    if normalized in TEAM_ALIASES:
        return TEAM_ALIASES[normalized]

    for alias in sorted(TEAM_ALIASES.keys(), key=len, reverse=True):
        if alias and alias in normalized:
            return TEAM_ALIASES[alias]

    return None


def _extract_game_abbrs(game_label: str):
    label = str(game_label or "")
    if "@" not in label:
        return None, None

    away_text, home_text = [part.strip() for part in label.split("@", 1)]
    return _resolve_team_abbr(away_text), _resolve_team_abbr(home_text)


def _build_game_cache_key(player_name: str, game_label: str, reference_date: Optional[datetime.date] = None) -> str:
    normalized_date = ""
    if reference_date is not None:
        normalized_date = str(reference_date)
    return f"{_normalize_name(player_name)}::{_normalize_name(game_label)}::{normalized_date}"


def _should_refresh_cached_game_result(cached: Optional[Dict], reference_date: Optional[datetime.date] = None) -> bool:
    if not cached:
        return True
    status = cached.get("status")
    if status == "played":
        if reference_date is not None:
            expected_date = f"{reference_date.month}/{reference_date.day}"
            cached_date = str(cached.get("date", "")).strip()
            if cached_date != expected_date:
                return True
        return False
    if status == "void":
        return True
    return True


def _market_price_bucket(price_delta):
    if price_delta is None:
        return "no_reference"
    try:
        price_delta = float(price_delta)
    except (TypeError, ValueError):
        return "no_reference"
    if price_delta >= 0.05:
        return "bet365_better"
    if price_delta <= -0.05:
        return "market_better"
    return "near_market"

def _load_comparison_from_file():
    comparison_file = config.DATA_DIR / "comparison_history.json"
    if comparison_file.exists():
        try:
            with open(comparison_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}


def _build_player_team_index() -> Dict[str, str]:
    player_team_index = {}

    try:
        if config.CACHE_FILE.exists():
            with open(config.CACHE_FILE, "r", encoding="utf-8") as f:
                stats_cache = json.load(f)
            for player_name, stats in stats_cache.items():
                team_name = stats.get("team", "")
                team_abbr = config.TEAM_NAME_MAPPING.get(team_name)
                if player_name and team_abbr:
                    player_team_index[_normalize_name(player_name)] = team_abbr
    except Exception:
        pass

    try:
        teams_file = config.DATA_FILES.get("teams")
        if teams_file and teams_file.exists():
            with open(teams_file, "r", encoding="utf-8") as f:
                teams_data = json.load(f)
            for team_entry in teams_data:
                team_name = team_entry.get("team", "")
                team_abbr = config.TEAM_NAME_MAPPING.get(team_name)
                if not team_abbr:
                    continue
                for player in team_entry.get("players", []):
                    player_name = player.get("name", "")
                    if player_name:
                        player_team_index.setdefault(_normalize_name(player_name), team_abbr)
    except Exception:
        pass

    return player_team_index


PLAYER_TEAM_INDEX = _build_player_team_index()


def _resolve_player_team_abbr(player_name: str) -> Optional[str]:
    normalized = _normalize_name(player_name)
    if not normalized:
        return None
    if normalized in PLAYER_TEAM_INDEX:
        return PLAYER_TEAM_INDEX[normalized]

    normalized_base = normalized.replace(" jr", "").replace(" iii", "").replace(" ii", "").strip()
    for key, team_abbr in PLAYER_TEAM_INDEX.items():
        key_base = key.replace(" jr", "").replace(" iii", "").replace(" ii", "").strip()
        if normalized_base == key_base:
            return team_abbr
    return None


def _validate_selection_game(player_name: str, game_label: str) -> Dict[str, Optional[str]]:
    away_abbr, home_abbr = _extract_game_abbrs(game_label)
    player_team_abbr = _resolve_player_team_abbr(player_name)
    if not game_label:
        return {
            "player_team_abbr": player_team_abbr,
            "away_abbr": away_abbr,
            "home_abbr": home_abbr,
            "game_label_valid": True,
        }

    valid = bool(player_team_abbr and player_team_abbr in {away_abbr, home_abbr})
    return {
        "player_team_abbr": player_team_abbr,
        "away_abbr": away_abbr,
        "home_abbr": home_abbr,
        "game_label_valid": valid,
    }


def _resolve_selection_prop_type(stat_label: str) -> str:
    stat_text = str(stat_label or "").lower()

    if "3pm" in stat_text or "tripl" in stat_text or "cestas de 3" in stat_text or "3 convertidas" in stat_text:
        return "3PM"
    if "assist" in stat_text or "ast" in stat_text:
        return "AST"
    if "rebot" in stat_text or "rebat" in stat_text or "reb" in stat_text:
        return "REB"
    if "pontos" in stat_text or "pts" in stat_text:
        return "PTS"
    return "PTS"


def _resolve_selection_side(stat_label: str) -> str:
    stat_text = str(stat_label or "").lower()
    if "under" in stat_text or "baixa" in stat_text:
        return "Under"
    if "over" in stat_text or "alta" in stat_text:
        return "Over"
    if " - " in stat_text:
        return "Under"
    return "Over"


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
        if "saved_player_game_results" not in st.session_state:
            st.session_state.saved_player_game_results = saved.get("player_game_results", {})
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
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total de Apostas Analisadas", total_bets)
        with col2:
            weights = summary.get("suggested_weights", (0.6, 0.4))
            st.metric("Pesos Sugeridos (S/L5)", f"{weights[0]:.1f}/{weights[1]:.1f}")
        roi_summary = summary.get("roi_summary", {})
        with col3:
            st.metric("Stake Total", f"{roi_summary.get('total_stake', 0.0):.1f}u")
        with col4:
            st.metric("ROI Histórico", f"{roi_summary.get('roi_pct', 0.0):.2f}%", delta=f"{roi_summary.get('total_profit', 0.0):.2f}u")
        
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

    default_bet_date = (datetime.now() - timedelta(days=1)).date()
    bet_reference_date = st.date_input("Data de referência da aposta", value=default_bet_date, key="bet365_reference_date")

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
                            "player_game_results": st.session_state.get("saved_player_game_results", {}),
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

                    over_under = prop.get("over_under", "Over")
                    actual_found = bool(pl)
                    diff = actual - line if actual_found else None
                    result = "SEM DADOS"
                    if diff is not None:
                        if over_under == "Over":
                            if actual > line:
                                result = "✅ ACERTOU"
                                total_hit += 1
                            elif actual < line:
                                result = "❌ ERROU"
                                total_miss += 1
                            else:
                                result = "➖ PUSH"
                                total_push += 1
                        else:
                            if actual < line:
                                result = "✅ ACERTOU"
                                total_hit += 1
                            elif actual > line:
                                result = "❌ ERROU"
                                total_miss += 1
                            else:
                                result = "➖ PUSH"
                                total_push += 1

                    odds_snapshot = prop.get("odds_snapshot", {})
                    picked_odds = prop.get("picked_odds", odds_snapshot.get("selected_odds", prop.get("odds")))
                    reference_odds = odds_snapshot.get("reference_odds_over") if over_under == "Over" else odds_snapshot.get("reference_odds_under")
                    price_delta = odds_snapshot.get("price_delta_over") if over_under == "Over" else odds_snapshot.get("price_delta_under")
                    price_bucket = _market_price_bucket(price_delta)
                    try:
                        picked_odds = float(picked_odds) if picked_odds is not None else None
                    except (TypeError, ValueError):
                        picked_odds = None
                    try:
                        reference_odds = float(reference_odds) if reference_odds is not None else None
                    except (TypeError, ValueError):
                        reference_odds = None
                    try:
                        price_delta = float(price_delta) if price_delta is not None else None
                    except (TypeError, ValueError):
                        price_delta = None

                    stake = 1.0 if picked_odds else None
                    profit = None
                    if picked_odds and result == "✅ ACERTOU":
                        profit = round(picked_odds - 1.0, 3)
                    elif picked_odds and result == "❌ ERROU":
                        profit = -1.0
                    elif picked_odds and result == "➖ PUSH":
                        profit = 0.0

                    comparison_results.append({
                        "game": game_label,
                        "player": player,
                        "type": prop_type,
                        "line": line,
                        "actual": actual if actual_found else "?",
                        "diff": f"{diff:+.1f}" if diff is not None else "?",
                        "result": result,
                        "conf": prop.get("confidence", 0),
                        "trend": prop.get("advanced_filters", {}).get("trend", "stable"),
                        "consistency": prop.get("advanced_filters", {}).get("consistency", 0),
                        "is_home": prop.get("is_home", True),
                        "over_under": over_under,
                        "matchup_mult": prop.get("matchup_mult", 1.0),
                        "aggressiveness": prop.get("aggressiveness"),
                        "odds_source": prop.get("odds_source", "unknown"),
                        "market_line": prop.get("market_line"),
                        "market_gap": round(line - float(prop.get("market_line")), 2) if prop.get("market_line") is not None else None,
                        "history_multiplier": prop.get("history_multiplier"),
                        "picked_odds": picked_odds,
                        "stake": stake,
                        "profit": profit,
                        "odds_snapshot_time": odds_snapshot.get("captured_at") or ticket.get("odds_snapshot_time"),
                        "reference_odds": reference_odds,
                        "reference_bookmaker": odds_snapshot.get("reference_bookmaker"),
                        "reference_source": odds_snapshot.get("reference_source"),
                        "reference_bookmakers": odds_snapshot.get("reference_bookmakers", []),
                        "price_delta": price_delta,
                        "market_price_bucket": price_bucket,
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

                settled_profit_rows = [row for row in comparison_results if row.get("profit") is not None]
                if settled_profit_rows:
                    total_stake = sum(row.get("stake", 0.0) or 0.0 for row in settled_profit_rows)
                    total_profit = sum(row.get("profit", 0.0) or 0.0 for row in settled_profit_rows)
                    roi_pct = (total_profit / total_stake * 100) if total_stake > 0 else 0.0
                    roi1, roi2, roi3 = st.columns(3)
                    roi1.metric("Stake", f"{total_stake:.1f}u")
                    roi2.metric("Lucro", f"{total_profit:.2f}u")
                    roi3.metric("ROI", f"{roi_pct:.2f}%")

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
                        "picked_odds": st.column_config.NumberColumn("Odd", format="%.2f"),
                        "reference_odds": st.column_config.NumberColumn("Ref", format="%.2f"),
                        "reference_bookmaker": st.column_config.TextColumn("Casa Ref"),
                        "price_delta": st.column_config.NumberColumn("Δ B365", format="%.2f"),
                        "profit": st.column_config.NumberColumn("Lucro", format="%.2f"),
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
                    over_under = cr.get("over_under", "Over")
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

                roi_by_type = {}
                roi_by_side = {}
                roi_by_market_price = {}
                market_price_analysis = {}
                for cr in comparison_results:
                    profit = cr.get("profit")
                    stake = cr.get("stake", 1.0)
                    price_bucket = cr.get("market_price_bucket", "no_reference")
                    if price_bucket not in market_price_analysis:
                        market_price_analysis[price_bucket] = {"hit": 0, "miss": 0, "push": 0}
                    if "ACERTOU" in cr["result"]:
                        market_price_analysis[price_bucket]["hit"] += 1
                    elif "ERROU" in cr["result"]:
                        market_price_analysis[price_bucket]["miss"] += 1
                    else:
                        market_price_analysis[price_bucket]["push"] += 1

                    if profit is None:
                        continue
                    type_key = cr.get("type", "unknown")
                    side_key = cr.get("over_under", "Over")
                    for bucket, key in ((roi_by_type, type_key), (roi_by_side, side_key), (roi_by_market_price, price_bucket)):
                        if key not in bucket:
                            bucket[key] = {"stake": 0.0, "profit": 0.0}
                        bucket[key]["stake"] += stake
                        bucket[key]["profit"] += profit

                market_price_rows = []
                for key, stats in market_price_analysis.items():
                    total = stats["hit"] + stats["miss"]
                    market_price_rows.append({
                        "bucket": key,
                        "acertos": stats["hit"],
                        "erros": stats["miss"],
                        "push": stats["push"],
                        "taxa": f"{(stats['hit'] / total * 100):.1f}%" if total > 0 else "0.0%",
                    })

                if market_price_rows:
                    st.markdown("---")
                    st.markdown("### 📉 Bet365 vs Mercado")
                    st.dataframe(market_price_rows, hide_index=True, use_container_width=True)

                if roi_by_type or roi_by_side or roi_by_market_price:
                    st.markdown("---")
                    st.markdown("### 💸 ROI")

                    roi_type_rows = []
                    for key, stats in roi_by_type.items():
                        stake = stats["stake"]
                        roi_type_rows.append({
                            "tipo": key,
                            "stake": round(stake, 2),
                            "lucro": round(stats["profit"], 2),
                            "roi": f"{(stats['profit'] / stake * 100):.2f}%" if stake > 0 else "0.00%",
                        })

                    roi_side_rows = []
                    for key, stats in roi_by_side.items():
                        stake = stats["stake"]
                        roi_side_rows.append({
                            "lado": key,
                            "stake": round(stake, 2),
                            "lucro": round(stats["profit"], 2),
                            "roi": f"{(stats['profit'] / stake * 100):.2f}%" if stake > 0 else "0.00%",
                        })

                    roi_market_rows = []
                    for key, stats in roi_by_market_price.items():
                        stake = stats["stake"]
                        roi_market_rows.append({
                            "bucket": key,
                            "stake": round(stake, 2),
                            "lucro": round(stats["profit"], 2),
                            "roi": f"{(stats['profit'] / stake * 100):.2f}%" if stake > 0 else "0.00%",
                        })

                    roi_col1, roi_col2, roi_col3 = st.columns(3)
                    with roi_col1:
                        if roi_type_rows:
                            st.dataframe(roi_type_rows, hide_index=True)
                    with roi_col2:
                        if roi_side_rows:
                            st.dataframe(roi_side_rows, hide_index=True)
                    with roi_col3:
                        if roi_market_rows:
                            st.dataframe(roi_market_rows, hide_index=True)

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
                        "aggressiveness_analysis": {},
                        "market_gap_analysis": {},
                        "market_price_analysis": {},
                        "odds_source_analysis": {},
                        "profit_summary": {
                            "total_stake": 0.0,
                            "total_profit": 0.0,
                            "roi_pct": 0.0,
                        },
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

                        aggr = cr.get("aggressiveness")
                        if isinstance(aggr, (int, float)):
                            if aggr < 0.15:
                                aggr_key = "low"
                            elif aggr < 0.25:
                                aggr_key = "medium"
                            else:
                                aggr_key = "high"
                            if aggr_key not in history_entry["aggressiveness_analysis"]:
                                history_entry["aggressiveness_analysis"][aggr_key] = {"hit": 0, "miss": 0}
                            if "ACERTOU" in cr["result"]:
                                history_entry["aggressiveness_analysis"][aggr_key]["hit"] += 1
                            elif "ERROU" in cr["result"]:
                                history_entry["aggressiveness_analysis"][aggr_key]["miss"] += 1

                        market_gap = cr.get("market_gap")
                        if market_gap is None:
                            gap_key = "no_market"
                        elif market_gap >= 0.5:
                            gap_key = "model_above_market"
                        elif market_gap <= -0.5:
                            gap_key = "market_above_model"
                        else:
                            gap_key = "aligned"
                        if gap_key not in history_entry["market_gap_analysis"]:
                            history_entry["market_gap_analysis"][gap_key] = {"hit": 0, "miss": 0}
                        if "ACERTOU" in cr["result"]:
                            history_entry["market_gap_analysis"][gap_key]["hit"] += 1
                        elif "ERROU" in cr["result"]:
                            history_entry["market_gap_analysis"][gap_key]["miss"] += 1

                        price_bucket = cr.get("market_price_bucket", "no_reference")
                        if price_bucket not in history_entry["market_price_analysis"]:
                            history_entry["market_price_analysis"][price_bucket] = {"hit": 0, "miss": 0}
                        if "ACERTOU" in cr["result"]:
                            history_entry["market_price_analysis"][price_bucket]["hit"] += 1
                        elif "ERROU" in cr["result"]:
                            history_entry["market_price_analysis"][price_bucket]["miss"] += 1

                        odds_source = cr.get("odds_source", "unknown")
                        if odds_source not in history_entry["odds_source_analysis"]:
                            history_entry["odds_source_analysis"][odds_source] = {"hit": 0, "miss": 0}
                        if "ACERTOU" in cr["result"]:
                            history_entry["odds_source_analysis"][odds_source]["hit"] += 1
                        elif "ERROU" in cr["result"]:
                            history_entry["odds_source_analysis"][odds_source]["miss"] += 1

                        profit = cr.get("profit")
                        stake = cr.get("stake", 1.0)
                        if profit is not None:
                            history_entry["profit_summary"]["total_stake"] += stake
                            history_entry["profit_summary"]["total_profit"] += profit

                    if history_entry["profit_summary"]["total_stake"] > 0:
                        history_entry["profit_summary"]["total_stake"] = round(history_entry["profit_summary"]["total_stake"], 2)
                        history_entry["profit_summary"]["total_profit"] = round(history_entry["profit_summary"]["total_profit"], 2)
                        history_entry["profit_summary"]["roi_pct"] = round(
                            history_entry["profit_summary"]["total_profit"] / history_entry["profit_summary"]["total_stake"] * 100,
                            2,
                        )
                    
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

                    snapshot_file = save_calibration_snapshot()
                    backtest_file = save_mode_backtest_summary()
                    
                    st.success(f"✅ Salvo! Total de {len(existing)} registros")
                    st.caption(f"Calibração automática atualizada em {snapshot_file.name}")
                    st.caption(f"Backtest automático por modo atualizado em {backtest_file.name}")

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

                        prop_type = _resolve_selection_prop_type(stat)
                        over_under = _resolve_selection_side(stat)

                        line_match = re.search(r"(\d+\.?\d*)", valor)
                        line = float(line_match.group(1)) if line_match else 0

                        validation = _validate_selection_game(player, jogo)
                        lookup_jogo = jogo if validation["game_label_valid"] else ""

                        selections.append({
                            "player": player,
                            "type": prop_type,
                            "line": line,
                            "over_under": over_under,
                            "jogo": jogo,
                            "lookup_jogo": lookup_jogo,
                            "player_team_abbr": validation["player_team_abbr"],
                            "game_label_valid": validation["game_label_valid"],
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

                        prop_type = _resolve_selection_prop_type(line_info)
                        over_under = _resolve_selection_side(line_info)

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
                mismatch_tag = ""
                if sel.get("jogo") and not sel.get("game_label_valid", True):
                    detected_team = sel.get("player_team_abbr") or "?"
                    mismatch_tag = f" [jogo inconsistente para {detected_team}; usando último jogo real]"
                st.write(f"{i+1}. **{sel['player']}** - {sel['over_under']} {sel['line']} {sel['type']}{jogo_tag}{mismatch_tag}")

            st.markdown("---")
            st.markdown("### 🔍 Buscar Resultados Reais")

            # Load cached player stats
            saved_data = _load_comparison_from_file()
            cached_players = saved_data.get("player_last_game", {}) if saved_data else {}
            cached_game_results = saved_data.get("player_game_results", {}) if saved_data else {}
            cached_team_players = st.session_state.get("comparison_team_players_cache", {})
            
            if cached_players:
                st.info(f"📦 Cache disponível: {len(cached_players)} jogadores")
            
            unique_selection_keys = {
                _build_game_cache_key(
                    sel.get("player", ""),
                    sel.get("lookup_jogo", sel.get("jogo", "")),
                    bet_reference_date,
                )
                for sel in selections
            }
            missing_game_keys = [key for key in unique_selection_keys if key not in cached_game_results]
            
            if missing_game_keys:
                st.warning(f"⚠️ {len(missing_game_keys)} seleções ainda precisam de consulta no ESPN")
            
            if st.button("📊 Buscar Stats dos Jogadores"):
                with st.spinner("Buscando stats..."):
                    from scrapers.espn_scraper import ESPNScraper
                    from concurrent.futures import ThreadPoolExecutor, as_completed

                    scraper = ESPNScraper()

                    needed_team_abbrs = set()
                    for sel in selections:
                        away_abbr, home_abbr = _extract_game_abbrs(sel.get("lookup_jogo", sel.get("jogo", "")))
                        if away_abbr:
                            needed_team_abbrs.add(away_abbr)
                        if home_abbr:
                            needed_team_abbrs.add(home_abbr)
                        if sel.get("player_team_abbr"):
                            needed_team_abbrs.add(sel.get("player_team_abbr"))

                    if not needed_team_abbrs:
                        needed_team_abbrs = set(cached_team_players.keys())

                    for abbr in sorted(needed_team_abbrs):
                        if abbr in cached_team_players:
                            continue
                        ts = scraper.get_team_stats(abbr)
                        if ts:
                            team_map = {}
                            for p in ts:
                                name = p.get("name", "").lower()
                                if name not in team_map:
                                    team_map[name] = {"pid": p.get("pid"), "abbr": abbr}
                            cached_team_players[abbr] = team_map

                    st.session_state.comparison_team_players_cache = cached_team_players

                    team_players = {}
                    for abbr in sorted(needed_team_abbrs):
                        for name, info in cached_team_players.get(abbr, {}).items():
                            if name not in team_players:
                                team_players[name] = info

                    st.success(f"✅ {len(team_players)} jogadores indexados em {len(needed_team_abbrs)} times")

                    def find_game_result(name, game_label):
                        cache_key = _build_game_cache_key(name, game_label, bet_reference_date)
                        cached = cached_game_results.get(cache_key)
                        if cached and not _should_refresh_cached_game_result(cached, bet_reference_date):
                            return cached

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
                            away_abbr, home_abbr = _extract_game_abbrs(game_label)
                            player_team = player_info.get("abbr")
                            opponent_abbr = None
                            if player_team and away_abbr and home_abbr:
                                if player_team == away_abbr:
                                    opponent_abbr = home_abbr
                                elif player_team == home_abbr:
                                    opponent_abbr = away_abbr

                            scraper_i = ESPNScraper()
                            if opponent_abbr:
                                target_game = scraper_i.get_player_game_against_opponent(
                                    player_info["pid"], name, opponent_abbr, bet_reference_date, max_age_days=0
                                )
                                if target_game:
                                    return target_game

                            last5 = scraper_i.get_player_last5(player_info["pid"], name, last_game_only=True)
                            if last5:
                                return {
                                    "status": "played",
                                    "pts": int(last5.get("ppg", 0)),
                                    "reb": int(last5.get("rpg", 0)),
                                    "ast": int(last5.get("apg", 0)),
                                    "fg3": int(last5.get("tpg", 0)),
                                    "source": "last_game_fallback",
                                }
                        return None

                    unique_selection_map = {}
                    for sel in selections:
                        cache_key = _build_game_cache_key(
                            sel.get("player", ""),
                            sel.get("lookup_jogo", sel.get("jogo", "")),
                            bet_reference_date,
                        )
                        if cache_key not in unique_selection_map:
                            unique_selection_map[cache_key] = sel

                    fetched_selection_results = {}
                    selections_to_fetch = []
                    for cache_key, sel in unique_selection_map.items():
                        cached = cached_game_results.get(cache_key)
                        if cached is not None and not _should_refresh_cached_game_result(cached, bet_reference_date):
                            fetched_selection_results[cache_key] = cached
                        else:
                            selections_to_fetch.append((cache_key, sel))

                    if selections_to_fetch:
                        with ThreadPoolExecutor(max_workers=min(8, len(selections_to_fetch))) as executor:
                            futures = {
                                executor.submit(find_game_result, sel["player"], sel.get("lookup_jogo", sel.get("jogo", ""))): cache_key
                                for cache_key, sel in selections_to_fetch
                            }
                            for future in as_completed(futures):
                                fetched_selection_results[futures[future]] = future.result()

                    results = []
                    fetched_players = {}
                    fetched_game_results = {}
                    for i, sel in enumerate(selections):
                        with st.expander(f"{i+1}. {sel['player']}"):
                            game_label = sel.get("lookup_jogo", sel.get("jogo", ""))
                            cache_key = _build_game_cache_key(sel["player"], game_label, bet_reference_date)
                            game_result = fetched_selection_results.get(cache_key)
                            if game_result and game_result.get("status") == "played":
                                fetched_players[sel["player"]] = {
                                    "pts": int(game_result.get("ppg", game_result.get("pts", 0))),
                                    "reb": int(game_result.get("rpg", game_result.get("reb", 0))),
                                    "ast": int(game_result.get("apg", game_result.get("ast", 0))),
                                    "fg3": int(game_result.get("tpg", game_result.get("fg3", 0))),
                                }
                                fetched_game_results[cache_key] = game_result
                                actual = 0
                                if sel["type"] == "PTS":
                                    actual = game_result.get("ppg", game_result.get("pts", 0))
                                elif sel["type"] == "REB":
                                    actual = game_result.get("rpg", game_result.get("reb", 0))
                                elif sel["type"] == "AST":
                                    actual = game_result.get("apg", game_result.get("ast", 0))
                                elif sel["type"] == "3PM":
                                    actual = game_result.get("tpg", game_result.get("fg3", 0))

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
                                    "reference_date": str(bet_reference_date),
                                    "actual": actual,
                                    "result": "✅ ACERTOU" if hit else "❌ ERROU",
                                    "trend": "unknown",
                                    "consistency": 50,
                                    "is_home": True,
                                })
                                st.write(f"Feito: {actual} | Linha: {sel['line']} | {sel['over_under']} → {'✅' if hit else '❌'}")
                            elif game_result and game_result.get("status") == "void":
                                fetched_game_results[cache_key] = game_result
                                results.append({
                                    "player": sel["player"],
                                    "type": sel["type"],
                                    "line": sel["line"],
                                    "over_under": sel["over_under"],
                                    "reference_date": str(bet_reference_date),
                                    "actual": "-",
                                    "result": "➖ ANULADA",
                                    "trend": "unknown",
                                    "consistency": 50,
                                    "is_home": True,
                                    "reason": game_result.get("reason", "did_not_play"),
                                })
                                st.write(f"Seleção anulada: jogador não atuou no jogo alvo ({game_result.get('reason', 'did_not_play')})")
                            else:
                                results.append({
                                    "player": sel["player"],
                                    "type": sel["type"],
                                    "line": sel["line"],
                                    "over_under": sel["over_under"],
                                    "reference_date": str(bet_reference_date),
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
                    all_game_results = cached_game_results.copy()
                    all_game_results.update(fetched_game_results)
                    
                    st.session_state.bet365_results = results
                    st.session_state.saved_bet365_results = results.copy()
                    st.session_state.saved_player_game_results = all_game_results.copy()
                    _save_comparison_to_file({
                        "player_last_game": all_players,
                        "player_game_results": all_game_results,
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