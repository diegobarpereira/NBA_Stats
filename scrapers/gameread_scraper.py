import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path
import time
import logging

import config

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2


def _retry_request(url: str, timeout: int = 30, params: Optional[Dict] = None) -> requests.Response:
    """Faz requisição com retry e exponential backoff."""
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, timeout=timeout, params=params)
            response.raise_for_status()
            return response
        except (requests.ConnectTimeout, requests.ConnectionError) as e:
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY * (2 ** attempt)
                logger.warning(f"Tentativa {attempt + 1} falhou, esperando {wait_time}s: {e}")
                time.sleep(wait_time)
            else:
                raise
    raise requests.RequestException(f"Falhou após {MAX_RETRIES} tentativas")


TEAM_ABBR_TO_NAME = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks", "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings", "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors", "UTA": "Utah Jazz", "WAS": "Washington Wizards",
}

STATUS_MAP = {
    "OUT": "OUT",
    "OUT indefinitely": "OUT",
    "DOUBTFUL": "DOUBTFUL",
    "QUESTIONABLE": "QUESTIONABLE",
    "PROBABLE": "PROBABLE",
    "ACTIVE": "ACTIVE",
    "GAME DECISION": "ACTIVE",
}


def _normalize_injury_status(status: str) -> str:
    if not status:
        return "ACTIVE"
    upper = status.upper().strip()
    return STATUS_MAP.get(upper, "OUT")


def fetch_games_from_gameread(date: str, season: int = 2025) -> List[Dict]:
    url = f"https://gameread.app/nba/api/v1/games/day?date={date}&season={season}"
    response = _retry_request(url, timeout=30)
    data = response.json()
    
    games = []
    for game in data.get("games", []):
        home = game.get("homeTeam", {})
        away = game.get("visitorTeam", {})
        
        home_abbr = home.get("abbreviation", "")
        away_abbr = away.get("abbreviation", "")
        
        home_name = TEAM_ABBR_TO_NAME.get(home_abbr, home.get("name", ""))
        away_name = TEAM_ABBR_TO_NAME.get(away_abbr, away.get("name", ""))
        
        dt_utc = game.get("dateTimeUtc", "")
        if dt_utc:
            try:
                dt = datetime.fromisoformat(dt_utc.replace("+00:00", ""))
                dt = dt.replace(tzinfo=None)
                dt = dt - timedelta(hours=3)
            except Exception:
                dt = datetime.now()
        else:
            dt = datetime.now()
        
        game_id = f"{away_abbr}vs{home_abbr}_{date}"
        
        games.append({
            "id": game_id,
            "home": home_name,
            "away": away_name,
            "datetime": dt.isoformat(),
            "home_abbr": home_abbr,
            "away_abbr": away_abbr,
            "game_api_id": game.get("id"),
        })
    
    return games


def fetch_injuries_from_gameread(date: str, season: int = 2025) -> Dict:
    games_url = f"https://gameread.app/nba/api/v1/games/day?date={date}&season={season}"
    response = _retry_request(games_url, timeout=30)
    data = response.json()
    
    by_team = {}
    
    for game in data.get("games", []):
        game_api_id = game.get("id")
        if not game_api_id:
            continue
        
        matchup_url = f"https://gameread.app/nba/api/v1/games/{game_api_id}/matchup-preview?last=10"
        try:
            resp = _retry_request(matchup_url, timeout=15)
            if resp.status_code != 200:
                continue
            matchup_data = resp.json()
        except Exception:
            continue
        
        injuries = matchup_data.get("injuries", {})
        
        for side in ["home", "visitor"]:
            team_key = matchup_data.get(side, {})
            team_abbr = team_key.get("abbreviation", "")
            team_name = TEAM_ABBR_TO_NAME.get(team_abbr, team_abbr)
            
            if team_abbr not in by_team:
                by_team[team_abbr] = {
                    "abbr": team_abbr,
                    "team": team_name,
                    "jogadores": []
                }
            
            for inj in injuries.get(side, []):
                player_name = inj.get("name", "")
                status_raw = inj.get("status", "")
                normalized = _normalize_injury_status(status_raw)
                
                if normalized in ["OUT", "DOUBTFUL", "QUESTIONABLE", "PROBABLE"]:
                    by_team[team_abbr]["jogadores"].append({
                        "nome": player_name,
                        "status": normalized
                    })
    
    return {
        "relatorio_lesoes": {
            "data": date,
            "times": list(by_team.values())
        }
    }


def fetch_and_save_gameread_data(date: str, season: int = 2025) -> tuple[List[Dict], Dict]:
    games = fetch_games_from_gameread(date, season)
    injuries = fetch_injuries_from_gameread(date, season)
    
    games_path = config.DATA_FILES["games"]
    injuries_path = config.DATA_FILES["injuries"]
    
    games_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(games_path, "w", encoding="utf-8") as f:
        json.dump(games, f, indent=2, ensure_ascii=False)
    
    with open(injuries_path, "w", encoding="utf-8") as f:
        json.dump(injuries, f, indent=2, ensure_ascii=False)
    
    return games, injuries
