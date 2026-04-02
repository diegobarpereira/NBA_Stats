import time
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

import config


class StatsScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        self.base_url = config.SCRAPING_CONFIG["base_url"]
        self.delay = config.SCRAPING_CONFIG["request_delay_seconds"]

    def scrape_player_stats(self, player_name: str, team_abbr: str) -> Optional[Dict]:
        url = self._build_player_url(player_name, team_abbr)
        if not url:
            return None

        try:
            time.sleep(self.delay)
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            stats = {}
            stats["name"] = player_name
            stats["team"] = config.TEAM_NAME_REVERSE.get(team_abbr, team_abbr)

            per_game = self._parse_per_game_stats(soup)
            if per_game:
                stats.update(per_game)

            last_5 = self._parse_last_games(soup, 5)
            if last_5:
                stats["games_last5"] = len(last_5)
                for key in ["points", "rebounds", "assists", "3pt"]:
                    stats[f"avg{key.capitalize()}_last5"] = last_5[key]["avg"]
                    stats[f"avg{key.capitalize()}_last5_formatted"] = last_5[key]["formatted"]

            return stats
        except Exception as e:
            print(f"  Erro ao buscar {player_name}: {e}")
            return None

    def _build_player_url(self, player_name: str, team_abbr: str) -> Optional[str]:
        parts = player_name.lower().split()
        if len(parts) < 2:
            return None
        last_name = parts[-1][:5]
        first_inicial = parts[0][:2]
        url = f"{self.base_url}/players/{first_inicial[0]}/{last_name}01.html"
        return url

    def _parse_per_game_stats(self, soup: BeautifulSoup) -> Optional[Dict]:
        try:
            per_game_table = soup.find("table", {"id": "per_game"})
            if not per_game_table:
                return None

            tbody = per_game_table.find("tbody")
            if not tbody:
                return None

            rows = tbody.find_all("tr")
            if not rows:
                return None

            last_row = rows[-1]
            cells = last_row.find_all("td")

            if len(cells) < 28:
                return None

            def safe_float(val, default=0.0):
                try:
                    return float(val) if val and val != "None" else default
                except:
                    return default

            pts = safe_float(cells[27].get_text()) if len(cells) > 27 else 0
            trb = safe_float(cells[21].get_text()) if len(cells) > 21 else 0
            ast = safe_float(cells[22].get_text()) if len(cells) > 22 else 0
            three_p = safe_float(cells[19].get_text()) if len(cells) > 19 else 0

            return {
                "avgPoints_season": round(pts, 1),
                "avgRebounds_season": round(trb, 1),
                "avgAssists_season": round(ast, 1),
                "avg3PT_season": round(three_p, 1),
                "games_season": int(cells[5].get_text()) if len(cells) > 5 and cells[5].get_text().isdigit() else 0,
            }
        except Exception:
            return None

    def _parse_last_games(self, soup: BeautifulSoup, num_games: int = 5) -> Optional[Dict]:
        try:
            splits_table = soup.find("table", {"id": "splits"})
            if not splits_table:
                return None

            tbody = splits_table.find("tbody")
            if not tbody:
                return None

            rows = tbody.find_all("tr")
            game_data = []
            for row in rows[:num_games]:
                cells = row.find_all("td")
                if len(cells) < 30:
                    continue
                try:
                    pts = float(cells[27].get_text()) if cells[27].get_text() else 0
                    trb = float(cells[21].get_text()) if cells[21].get_text() else 0
                    ast = float(cells[22].get_text()) if cells[22].get_text() else 0
                    three_p = float(cells[19].get_text()) if cells[19].get_text() else 0
                    game_data.append({
                        "points": pts, "rebounds": trb, "assists": ast, "3pt": three_p
                    })
                except:
                    continue

            if not game_data:
                return None

            result = {}
            for key in ["points", "rebounds", "assists", "3pt"]:
                values = [g[key] for g in game_data if g[key] > 0]
                if values:
                    avg = sum(values) / len(values)
                    result[key] = {
                        "avg": round(avg, 1),
                        "formatted": f"{avg:.1f}",
                        "games": len(values),
                    }
            return result
        except Exception:
            return None

    def scrape_team_roster(self, team_abbr: str) -> List[Dict]:
        url = f"{self.base_url}/teams/{team_abbr}/2025.html"
        players = []

        try:
            time.sleep(self.delay)
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            roster_table = soup.find("table", {"id": "roster"})
            if not roster_table:
                return players

            tbody = roster_table.find("tbody")
            if not tbody:
                return players

            for row in tbody.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) >= 2:
                    player_name = cells[0].get_text(strip=True)
                    position = cells[1].get_text(strip=True)
                    players.append({
                        "name": player_name,
                        "position": position,
                        "team": config.TEAM_NAME_REVERSE.get(team_abbr, team_abbr),
                    })
        except Exception as e:
            print(f"  Erro ao buscar roster {team_abbr}: {e}")

        return players

    def scrape_all_players_from_games(self, games_data: List[Dict], teams_data: List[Dict]) -> Dict[str, Dict]:
        stats = {}
        players_to_scrape = []

        team_players = {}
        for team in teams_data:
            team_abbr = config.TEAM_NAME_MAPPING.get(team["team"], team["team"])
            for player in team["players"]:
                player_name = player["name"]
                players_to_scrape.append({
                    "name": player_name,
                    "team_abbr": team_abbr,
                    "team": team["team"],
                    "position": player["position"],
                })

        total = len(players_to_scrape)
        print(f"\nBuscando estatísticas de {total} jogadores...")

        for i, player in enumerate(players_to_scrape):
            name = player["name"]
            if name in stats:
                continue

            print(f"  [{i+1}/{total}] {name}...", end=" ", flush=True)
            player_stats = self.scrape_player_stats(name, player["team_abbr"])

            if player_stats:
                stats[name] = player_stats
                print(f"OK (PTS: {player_stats.get('avgPoints_season', '?')})")
            else:
                print("NÃO ENCONTRADO")

        print(f"\nEstatísticas obtidas: {len(stats)}/{total}")
        return stats

def _pos_key(position: str) -> str:
    p = position.upper()
    if p in ("C", "F-C", "C-F"):
        return "C"
    if p in ("F", "G-F", "F-G"):
        return "F"
    return "G"


_FALLBACK_TEMPLATES = {
    "G": {
        "pts": 12.0, "reb": 3.5, "ast": 5.0, "3pt": 2.0,
        "pts_l5": 12.0, "reb_l5": 3.5, "ast_l5": 5.0, "3pt_l5": 2.0,
    },
    "F": {
        "pts": 14.0, "reb": 6.5, "ast": 2.5, "3pt": 1.5,
        "pts_l5": 14.0, "reb_l5": 6.5, "ast_l5": 2.5, "3pt_l5": 1.5,
    },
    "C": {
        "pts": 11.0, "reb": 8.0, "ast": 1.8, "3pt": 0.5,
        "pts_l5": 11.0, "reb_l5": 8.0, "ast_l5": 1.8, "3pt_l5": 0.5,
    },
}


def generate_fallback_stats(players: List[Dict]) -> Dict[str, Dict]:
    stats = {}
    for i, player in enumerate(players):
        name = player["name"]
        pk = _pos_key(player.get("position", "G"))
        base = _FALLBACK_TEMPLATES[pk]

        variation = ((i * 7) % 20) - 10
        pts = round(base["pts"] + variation * 0.3, 1)
        reb = round(base["reb"] + variation * 0.15, 1)
        ast = round(base["ast"] + variation * 0.2, 1)
        three = round(max(0, base["3pt"] + variation * 0.1), 1)

        l5_var = ((i * 13) % 30) - 15
        pts_l5 = round(pts + l5_var * 0.1, 1)
        reb_l5 = round(reb + l5_var * 0.05, 1)
        ast_l5 = round(ast + l5_var * 0.1, 1)
        three_l5 = round(max(0, three + l5_var * 0.05), 1)

        games_season = 30 + (i % 30)

        stats[name] = {
            "name": name,
            "team": player["team"],
            "position": player.get("position", "-"),
            "avgPoints_season": pts,
            "avgRebounds_season": reb,
            "avgAssists_season": ast,
            "avg3PT_season": three,
            "avgPoints_last5": pts_l5,
            "avgRebounds_last5": reb_l5,
            "avgAssists_last5": ast_l5,
            "avg3PT_last5": three_l5,
            "games_last5": 5,
            "games_season": games_season,
            "fallback": True,
        }
    return stats
