import time
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests

import config


class NBANewScraper:
    BASE_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.nba.com",
        "Referer": "https://www.nba.com/",
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.BASE_HEADERS)
        self.delay = config.SCRAPING_CONFIG["request_delay_seconds"]

    def get_player_stats(self, player_name: str, team_abbr: str) -> Optional[Dict]:
        player_id = self._find_player_id(player_name)
        if not player_id:
            return None

        season_avg = self._get_season_averages(player_id, team_abbr)
        last_5 = self._get_last_n_games(player_id, 5)

        if not season_avg:
            return None

        result = {
            "name": player_name,
            "team": config.TEAM_NAME_REVERSE.get(team_abbr, team_abbr),
            "position": season_avg.get("position", "-"),
            "avgPoints_season": season_avg.get("ppg", 0),
            "avgRebounds_season": season_avg.get("rpg", 0),
            "avgAssists_season": season_avg.get("apg", 0),
            "avg3PT_season": season_avg.get("tpg", 0),
            "games_season": season_avg.get("games_played", 0),
        }

        if last_5:
            result["avgPoints_last5"] = last_5.get("ppg", 0)
            result["avgRebounds_last5"] = last_5.get("rpg", 0)
            result["avgAssists_last5"] = last_5.get("apg", 0)
            result["avg3PT_last5"] = last_5.get("tpg", 0)
            result["games_last5"] = last_5.get("games", 0)
        else:
            result["avgPoints_last5"] = result["avgPoints_season"]
            result["avgRebounds_last5"] = result["avgRebounds_season"]
            result["avgAssists_last5"] = result["avgAssists_season"]
            result["avg3PT_last5"] = result["avg3PT_season"]
            result["games_last5"] = 0

        return result

    def _find_player_id(self, player_name: str) -> Optional[str]:
        parts = player_name.strip().split()
        if len(parts) < 2:
            return None
        last = parts[-1].lower()
        first = parts[0].lower()

        url = f"https://cdn.nba.com/headshots/nba.json"
        try:
            time.sleep(self.delay * 0.5)
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for league in data.get("league", {}).get("standard", []):
                    p_last = league.get("lastName", "").lower()
                    p_first = league.get("firstName", "").lower()
                    if p_last == last or last in p_last or p_last in last:
                        if p_first == first or first in p_first:
                            return league.get("personId")
        except Exception:
            pass

        search_url = "https://cdn.nba.com/xsearch/search/nba_players"
        params = {"Keyword": player_name, "Limit": 5}
        try:
            time.sleep(self.delay * 0.5)
            resp = self.session.get(search_url, params=params, timeout=10)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                for r in results:
                    if last in r.get("name", "").lower() or r.get("name", "").lower() in player_name.lower():
                        return r.get("id")
                if results:
                    return results[0].get("id")
        except Exception:
            pass

        return None

    def _get_season_averages(self, player_id: str, team_abbr: str) -> Optional[Dict]:
        url = f"https://stats.nba.com/stats/playercareerstats"
        params = {
            "PlayerID": player_id,
            "PerMode": "PerGame",
            "SeasonType": "Regular Season",
        }

        try:
            time.sleep(self.delay)
            resp = self.session.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                return None

            data = resp.json()
            sets = data.get("resultSets", [])
            if not sets:
                return None

            season_stats = sets[0].get("rowSet", [])
            if not season_stats:
                return None

            headers = sets[0].get("headers", [])

            season_idx = headers.index("SEASON") if "SEASON" in headers else 2
            pts_idx = headers.index("PTS") if "PTS" in headers else 26
            reb_idx = headers.index("REB") if "REB" in headers else 21
            ast_idx = headers.index("AST") if "AST" in headers else 22
            fg3_idx = headers.index("FG3M") if "FG3M" in headers else 20
            gp_idx = headers.index("GP") if "GP" in headers else 5
            pos_idx = headers.index("PLAYER_POSITION") if "PLAYER_POSITION" in headers else -1

            current_season = None
            for row in reversed(season_stats):
                season = str(row[season_idx]) if season_idx < len(row) else ""
                if season and re.match(r"\d{4}-\d{2}", season):
                    current_season = row
                    break

            if not current_season:
                return None

            def safe(val):
                return float(val) if val and str(val) not in ("None", "") else 0.0

            return {
                "ppg": round(safe(current_season[pts_idx]), 1),
                "rpg": round(safe(current_season[reb_idx]), 1),
                "apg": round(safe(current_season[ast_idx]), 1),
                "tpg": round(safe(current_season[fg3_idx]), 1),
                "games_played": int(safe(current_season[gp_idx])) if current_season[gp_idx] else 0,
                "position": str(current_season[pos_idx]) if pos_idx >= 0 else "-",
            }
        except Exception as e:
            print(f"    Career stats error: {e}")
            return None

    def _get_last_n_games(self, player_id: str, n: int = 5) -> Optional[Dict]:
        url = f"https://stats.nba.com/stats/playerdashptshotlog"
        params = {
            "PlayerID": player_id,
            "TeamID": 0,
            "Season": "2025-26",
            "SeasonType": "Regular Season",
            "PlayerPosition": "",
            "DateFrom": "",
            "DateTo": "",
            "GameScope": "",
            "LastNGames": n,
            "Location": "",
            "Month": 0,
            "OpponentTeamID": 0,
            "PerMode": "Totals",
            "Period": 0,
            "PlayerExperience": "",
            "StartRange": "",
            "EndRange": "",
            "VsConference": "",
            "VsDivision": "",
        }

        try:
            time.sleep(self.delay)
            resp = self.session.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                return None

            data = resp.json()
            sets = data.get("resultSets", [])
            if not sets:
                return None

            rows = sets[0].get("rowSet", [])
            headers = sets[0].get("headers", [])

            if not rows or not headers:
                return None

            pts_idx = next((i for i, h in enumerate(headers) if h == "PTS"), 12)
            reb_idx = next((i for i, h in enumerate(headers) if h == "REB"), 18)
            ast_idx = next((i for i, h in enumerate(headers) if h == "AST"), 19)
            fg3_idx = next((i for i, h in enumerate(headers) if h == "FG3M"), 8)

            games = min(n, len(rows))
            if games == 0:
                return None

            def avg(idx):
                vals = [float(row[idx]) for row in rows[:games] if row[idx] not in (None, "", "None")]
                return round(sum(vals) / len(vals), 1) if vals else 0.0

            return {
                "ppg": avg(pts_idx),
                "rpg": avg(reb_idx),
                "apg": avg(ast_idx),
                "tpg": avg(fg3_idx),
                "games": games,
            }
        except Exception as e:
            return None

    def get_team_players(self, team_abbr: str) -> List[Dict]:
        team_id = self._get_team_id(team_abbr)
        if not team_id:
            return []

        url = f"https://cdn.nba.com/team/{team_abbr}/roster.json"
        try:
            time.sleep(self.delay)
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                return []

            data = resp.json()
            players = data.get("people", [])
            return [
                {
                    "name": p.get("displayName", ""),
                    "position": p.get("position", "-"),
                    "team": config.TEAM_NAME_REVERSE.get(team_abbr, team_abbr),
                    "jersey": p.get("jersey", ""),
                }
                for p in players
            ]
        except Exception:
            return []

    def _get_team_id(self, team_abbr: str) -> Optional[str]:
        TEAM_IDS = {
            "ATL": "1610612737", "BOS": "1610612738", "BKN": "1610612751",
            "CHA": "1610612766", "CHI": "1610612741", "CLE": "1610612739",
            "DAL": "1610612742", "DEN": "1610612743", "DET": "1610612765",
            "GSW": "1610612744", "HOU": "1610612745", "IND": "1610612754",
            "LAC": "1610612746", "LAL": "1610612747", "MEM": "1610612763",
            "MIA": "1610612748", "MIL": "1610612749", "MIN": "1610612750",
            "NOP": "1610612740", "NYK": "1610612752", "OKC": "1610612760",
            "ORL": "1610612753", "PHI": "1610612755", "PHX": "1610612756",
            "POR": "1610612757", "SAC": "1610612758", "SAS": "1610612759",
            "TOR": "1610612761", "UTA": "1610612762", "WAS": "1610612764",
        }
        return TEAM_IDS.get(team_abbr)

    def scrape_all_players_from_games(
        self, games_data: List[Dict], teams_data: List[Dict]
    ) -> Dict[str, Dict]:
        stats = {}

        players_by_team = {}
        for team in teams_data:
            abbr = config.TEAM_NAME_MAPPING.get(team["team"], team["team"])
            players_by_team[abbr] = team["players"]

        teams_needed = set()
        for game in games_data:
            home_abbr = config.TEAM_NAME_MAPPING.get(game["home"], game["home"])
            away_abbr = config.TEAM_NAME_MAPPING.get(game["away"], game["away"])
            teams_needed.add(home_abbr)
            teams_needed.add(away_abbr)

        total = sum(len(players_by_team.get(t, [])) for t in teams_needed)
        print(f"\nBuscando estatisticas de ~{total} jogadores...")

        count = 0
        for team_abbr in sorted(teams_needed):
            team_players = players_by_team.get(team_abbr, [])
            team_name = config.TEAM_NAME_REVERSE.get(team_abbr, team_abbr)

            for player in team_players:
                name = player["name"]
                if name in stats:
                    continue

                count += 1
                print(f"  [{count}/{total}] {name} ({team_abbr})...", end=" ", flush=True)

                player_stats = self.get_player_stats(name, team_abbr)

                if player_stats:
                    stats[name] = player_stats
                    print(f"OK (PTS: {player_stats.get('avgPoints_season', '?')})")
                else:
                    print("FALHOU")

        print(f"\nEstatisticas obtidas: {len(stats)}/{total}")
        return stats
