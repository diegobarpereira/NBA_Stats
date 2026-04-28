from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Set, Tuple

import config
from scrapers.espn_scraper import ESPNScraper


ProgressCallback = Optional[Callable[[float, str], None]]
LogCallback = Optional[Callable[[str], None]]


def _emit_progress(callback: ProgressCallback, value: float, message: str) -> None:
    if callback is not None:
        callback(max(0.0, min(1.0, value)), message)


def _emit_log(callback: LogCallback, message: str) -> None:
    if callback is not None:
        callback(message)


def clear_stats_cache(loader) -> None:
    if config.CACHE_FILE.exists():
        config.CACHE_FILE.unlink()
    loader.stats_cache = {}


def collect_teams_needed(loader) -> Set[str]:
    teams_needed: Set[str] = set()
    for game in loader.games_data:
        home_abbr = config.TEAM_NAME_MAPPING.get(game["home"], game["home"])
        away_abbr = config.TEAM_NAME_MAPPING.get(game["away"], game["away"])
        teams_needed.add(home_abbr)
        teams_needed.add(away_abbr)
    return teams_needed


def scrape_season_stats(
    loader,
    progress_callback: ProgressCallback = None,
    log_callback: LogCallback = None,
) -> Dict:
    clear_stats_cache(loader)
    loader.load_teams()

    teams_needed = sorted(collect_teams_needed(loader))
    _emit_progress(progress_callback, 0.02, "Preparando scraping de Season Stats...")
    _emit_log(log_callback, f"Times do dia: {', '.join(teams_needed)}")

    scraper = ESPNScraper()
    team_stats_cache: Dict[str, List[Dict]] = {}

    def fetch_team(team_abbr: str) -> Tuple[str, Optional[List[Dict]]]:
        for _ in range(3):
            try:
                team_stats = scraper.get_team_stats(team_abbr)
                if team_stats:
                    return team_abbr, team_stats
            except Exception:
                continue
        return team_abbr, None

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_team, abbr): abbr for abbr in teams_needed}
        done = 0
        total = len(futures) or 1
        for future in as_completed(futures):
            done += 1
            abbr, team_stats = future.result()
            if team_stats:
                team_stats_cache[abbr] = team_stats
                _emit_log(log_callback, f"{abbr}: {len(team_stats)} jogadores")
            else:
                _emit_log(log_callback, f"{abbr}: sem resposta")
            _emit_progress(progress_callback, 0.05 + (done / total) * 0.20, f"Carregando elencos ESPN... {done}/{total}")

    tasks = []
    for team_abbr, team_stats in team_stats_cache.items():
        team_players = [
            player
            for team in loader.teams_data
            if config.TEAM_NAME_MAPPING.get(team["team"], team["team"]) == team_abbr
            for player in team["players"]
        ]
        for player in team_players:
            tasks.append((team_abbr, team_stats, player))

    results: Dict[str, Dict] = {}

    def scrape_player(task: Tuple[str, List[Dict], Dict]) -> Tuple[str, Optional[Dict]]:
        team_abbr, team_stats, player = task
        name = player["name"]
        player_stats = scraper._match_player_from_cache(name, team_stats, team_abbr)
        if not player_stats:
            try:
                player_stats = scraper.get_player_stats(name, team_abbr)
            except Exception:
                player_stats = scraper._match_player_from_cache(name, team_stats, team_abbr)
        return name, player_stats

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(scrape_player, task): task for task in tasks}
        done = 0
        total = len(futures) or 1
        for future in as_completed(futures):
            done += 1
            name, player_stats = future.result()
            if player_stats:
                results[name] = player_stats
            if done % 10 == 0 or done == total:
                _emit_progress(progress_callback, 0.25 + (done / total) * 0.40, f"Buscando Season Stats... {done}/{total}")

    loader.save_stats_cache(results)
    _emit_log(log_callback, f"Season Stats salvos: {len(results)} jogadores")

    return {
        "stats": results,
        "teams_needed": teams_needed,
        "players_expected": len(tasks),
        "players_saved": len(results),
    }


def enrich_last5_stats(
    loader,
    stats: Dict[str, Dict],
    progress_callback: ProgressCallback = None,
    log_callback: LogCallback = None,
) -> Dict:
    players_to_scrape = [
        (name, data) for name, data in stats.items()
        if (data.get("games_last5") or 0) not in range(1, 11)
    ]

    scraper = ESPNScraper()
    updated = 0
    errors = 0
    total = len(players_to_scrape) or 1

    _emit_log(log_callback, f"Last5 pendentes: {len(players_to_scrape)}")

    def fetch_last5(item: Tuple[str, Dict]) -> Tuple[str, Optional[Dict]]:
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

            if last5_data and last5_data.get("games", 0) >= 2:
                stats[name]["avgPoints_last5"] = last5_data["ppg"]
                stats[name]["avgRebounds_last5"] = last5_data["rpg"]
                stats[name]["avgAssists_last5"] = last5_data["apg"]
                stats[name]["avg3PT_last5"] = last5_data["tpg"]
                stats[name]["games_last5"] = last5_data["games"]
                stats[name]["avgMinutes_last5"] = last5_data.get("mpg", stats[name].get("avgMinutes_last5", 0.0))
                stats[name]["early_minutes_avg"] = last5_data.get("early_minutes_avg", 0.0)
                stats[name]["recent_minutes_avg"] = last5_data.get("recent_minutes_avg", 0.0)
                stats[name]["minute_trend"] = last5_data.get("minute_trend", 0.0)
                stats[name]["minute_volatility"] = last5_data.get("minute_volatility", 0.0)

                for i in range(1, 6):
                    pts_key = f"game_{i}_pts"
                    reb_key = f"game_{i}_reb"
                    ast_key = f"game_{i}_ast"
                    min_key = f"game_{i}_min"
                    if pts_key in last5_data:
                        stats[name][f"last5_game_{i}_pts"] = last5_data[pts_key]
                    if reb_key in last5_data:
                        stats[name][f"last5_game_{i}_reb"] = last5_data[reb_key]
                    if ast_key in last5_data:
                        stats[name][f"last5_game_{i}_ast"] = last5_data[ast_key]
                    if min_key in last5_data:
                        stats[name][f"last5_game_{i}_min"] = last5_data[min_key]

                if "home_ppg" in last5_data:
                    stats[name]["home_ppg"] = last5_data["home_ppg"]
                    stats[name]["away_ppg"] = last5_data["away_ppg"]
                    stats[name]["home_reb"] = last5_data["home_reb"]
                    stats[name]["away_reb"] = last5_data["away_reb"]
                    stats[name]["home_ast"] = last5_data["home_ast"]
                    stats[name]["away_ast"] = last5_data["away_ast"]
                    stats[name]["home_games"] = last5_data.get("home_games", 0)
                    stats[name]["away_games"] = last5_data.get("away_games", 0)

                updated += 1
            else:
                errors += 1

            if done % 10 == 0 or done == total:
                _emit_progress(progress_callback, 0.68 + (done / total) * 0.32, f"Buscando Last5... {done}/{total}")

    loader.save_stats_cache(stats)
    loader.stats_cache = stats.copy()
    _emit_log(log_callback, f"Last5 atualizados: {updated} | sem dados: {errors}")

    return {
        "stats": stats,
        "updated": updated,
        "errors": errors,
        "requested": len(players_to_scrape),
    }


def run_full_stats_refresh(
    loader,
    progress_callback: ProgressCallback = None,
    log_callback: LogCallback = None,
) -> Dict:
    season_result = scrape_season_stats(loader, progress_callback, log_callback)
    last5_result = enrich_last5_stats(loader, season_result["stats"], progress_callback, log_callback)
    _emit_progress(progress_callback, 1.0, "Scraping concluído")

    return {
        "stats": last5_result["stats"],
        "season": season_result,
        "last5": last5_result,
    }