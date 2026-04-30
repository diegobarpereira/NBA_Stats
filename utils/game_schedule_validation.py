import logging
from datetime import datetime
from functools import lru_cache
from typing import Dict, List, Optional, Set, Tuple

import requests


logger = logging.getLogger(__name__)

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ABBR_ALIASES = {
    "GS": "GSW",
    "NO": "NOP",
    "NY": "NYK",
    "SA": "SAS",
    "WSH": "WAS",
}


def _normalize_schedule_date(value: str) -> Optional[str]:
    digits = "".join(char for char in str(value) if char.isdigit())
    return digits if len(digits) == 8 else None


def _extract_game_date(game: Dict) -> str:
    value = str(game.get("date") or "").strip()
    if value:
        return value[:10]

    game_id = str(game.get("id") or "")
    if "_" in game_id:
        suffix = game_id.rsplit("_", 1)[-1]
        if len(suffix) == 10:
            return suffix

    dt_value = str(game.get("datetime") or "").strip()
    if dt_value:
        try:
            return datetime.fromisoformat(dt_value).date().isoformat()
        except ValueError:
            return dt_value[:10]

    return ""


def matchup_key(home_abbr: str, away_abbr: str) -> Optional[Tuple[str, str]]:
    home = ABBR_ALIASES.get(str(home_abbr or "").upper().strip(), str(home_abbr or "").upper().strip())
    away = ABBR_ALIASES.get(str(away_abbr or "").upper().strip(), str(away_abbr or "").upper().strip())
    if not home or not away:
        return None
    return tuple(sorted((away, home)))


@lru_cache(maxsize=32)
def get_espn_matchups_for_date(date: str) -> Optional[Set[Tuple[str, str]]]:
    normalized_date = _normalize_schedule_date(date)
    if not normalized_date:
        logger.warning("Data invalida para validacao de agenda ESPN: %s", date)
        return None

    try:
        response = requests.get(
            ESPN_SCOREBOARD_URL,
            params={"dates": normalized_date},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Falha ao consultar agenda da ESPN para %s: %s", date, exc)
        return None

    try:
        data = response.json()
    except ValueError as exc:
        logger.warning("Resposta invalida da ESPN para %s: %s", date, exc)
        return None

    matchups: Set[Tuple[str, str]] = set()
    for event in data.get("events", []):
        competitors = event.get("competitions", [{}])[0].get("competitors", [])
        abbrs = [
            str(competitor.get("team", {}).get("abbreviation") or "").upper().strip()
            for competitor in competitors
            if competitor.get("team", {}).get("abbreviation")
        ]
        if len(abbrs) != 2:
            continue
        key = matchup_key(abbrs[0], abbrs[1])
        if key:
            matchups.add(key)

    return matchups


def validate_games_against_espn(games: List[Dict], date: Optional[str] = None) -> Tuple[List[Dict], List[Dict]]:
    if not games:
        return games, []

    schedule_date = date or _extract_game_date(games[0])
    if not schedule_date:
        return games, []

    espn_matchups = get_espn_matchups_for_date(schedule_date)
    if espn_matchups is None:
        return games, []

    if not espn_matchups:
        logger.warning(
            "ESPN retornou agenda vazia para %s; mantendo jogos do GameRead por seguranca",
            schedule_date,
        )
        return games, []

    validated_games: List[Dict] = []
    removed_games: List[Dict] = []

    for game in games:
        key = matchup_key(game.get("home_abbr", ""), game.get("away_abbr", ""))
        if key and key in espn_matchups:
            validated_games.append(game)
            continue

        removed_game = game.copy()
        removed_game["validation_reason"] = (
            f"nao consta no scoreboard da ESPN para {schedule_date}"
        )
        removed_games.append(removed_game)

    if not validated_games:
        logger.warning(
            "Validacao ESPN removeria todos os %s jogos de %s; mantendo GameRead por seguranca",
            len(games),
            schedule_date,
        )
        return games, []

    return validated_games, removed_games