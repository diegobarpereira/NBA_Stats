import json
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

import config


MATCHUP_CACHE = config.DATA_DIR / "cache_matchups.json"
BASE_URL = "https://hashtagbasketball.com/nba-defense-vs-position"


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://hashtagbasketball.com/",
}


_TEAM_ABBR_MAP = {
    "ATL": "Atlanta Hawks",
    "BKN": "Brooklyn Nets",
    "BOS": "Boston Celtics",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAS": "San Antonio Spurs",
    "SAC": "Sacramento Kings",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}

_TEAM_ABBR_ALT = {
    "GS": "GSW",
    "NO": "NOP",
    "NY": "NYK",
    "PHO": "PHX",
    "SA": "SAS",
    "LAC": "LAC",
}

_POSITION_MAP = {"PG": "G", "SG": "G", "SF": "F", "PF": "F", "C": "C"}

_LEAGUE_AVG = {
    "points": 22.5,
    "rebounds": 8.5,
    "assists": 5.0,
    "3pt": 2.5,
}


def _extract_team_abbr(cell_text: str) -> str:
    match = re.match(r"([A-Z]{2,3})", cell_text.strip())
    if match:
        abbr = match.group(1)
        if abbr in _TEAM_ABBR_ALT:
            return _TEAM_ABBR_ALT[abbr]
        return abbr
    return ""


def _parse_cell_value(cell_text: str) -> float:
    match = re.search(r"([\d.]+)", cell_text.strip())
    if match:
        return float(match.group(1))
    return 0.0


def _scrape_defense_vs_position(period: str = "season") -> Dict[str, Dict]:
    url = BASE_URL
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    rows = []
    tables = soup.find_all("table")
    for table in tables:
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) >= 10:
                row_texts = [c.get_text(strip=True) for c in cells]
                if row_texts[0] in ("PG", "SG", "SF", "PF", "C"):
                    rows.append(row_texts)

    if not rows:
        return {}

    matchup_data = {}

    for row in rows:
        position_raw = row[0]
        team_abbr = _extract_team_abbr(row[1])
        team_name = _TEAM_ABBR_MAP.get(team_abbr, team_abbr)
        pos_short = _POSITION_MAP.get(position_raw, position_raw)

        pts_raw = _parse_cell_value(row[2])
        reb_raw = _parse_cell_value(row[7])
        ast_raw = _parse_cell_value(row[8])
        three_raw = _parse_cell_value(row[6])

        key = f"{team_name}|{pos_short}"
        matchup_data[key] = {
            "team": team_name,
            "abbr": team_abbr,
            "position_raw": position_raw,
            "position": pos_short,
            "def_pts_vs_pos": pts_raw,
            "def_reb_vs_pos": reb_raw,
            "def_ast_vs_pos": ast_raw,
            "def_3pm_vs_pos": three_raw,
        }

    return matchup_data


def get_matchup_boost(
    team_name: str,
    player_position: str,
    prop_type: str,
    matchup_data: Dict[str, Dict],
) -> float:
    if not matchup_data or not team_name or not player_position:
        return 1.0

    key = f"{team_name}|{player_position}"
    if key not in matchup_data:
        key = f"{team_name}|" + {"G": "G", "F": "F", "C": "C"}.get(player_position, player_position)
    if key not in matchup_data:
        return 1.0

    m = matchup_data[key]

    stat_map = {
        "points": "def_pts_vs_pos",
        "rebounds": "def_reb_vs_pos",
        "assists": "def_ast_vs_pos",
        "3pt": "def_3pm_vs_pos",
    }

    stat_key = stat_map.get(prop_type)
    if not stat_key:
        return 1.0

    value = m.get(stat_key, 0)
    if value <= 0:
        return 1.0

    avg = _LEAGUE_AVG.get(prop_type, 22.5)
    ratio = value / avg

    if ratio >= 1.20:
        return 1.15
    elif ratio >= 1.10:
        return 1.08
    elif ratio >= 1.05:
        return 1.04
    elif ratio >= 0.95:
        return 1.0
    elif ratio >= 0.85:
        return 0.95
    elif ratio >= 0.75:
        return 0.90
    else:
        return 0.83


def _read_matchup_cache() -> Tuple[Dict[str, Dict], Optional[str]]:
    if not MATCHUP_CACHE.exists():
        return {}, None

    with open(MATCHUP_CACHE, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"], payload.get("updated_on")

    if isinstance(payload, dict):
        return payload, None

    return {}, None


def load_matchup_cache() -> Dict[str, Dict]:
    data, _ = _read_matchup_cache()
    return data


def save_matchup_cache(data: Dict[str, Dict]) -> None:
    with open(MATCHUP_CACHE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "updated_on": date.today().isoformat(),
                "data": data,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )


def fetch_and_cache_matchups(force: bool = False) -> Dict[str, Dict]:
    cached, updated_on = _read_matchup_cache()
    cache_is_fresh = updated_on == date.today().isoformat()

    if cached and cache_is_fresh and not force:
        return cached

    if cached and not cache_is_fresh and not force:
        print(f"Cache de matchup desatualizado ({updated_on or 'sem data'}); atualizando para {date.today().isoformat()}...")
    elif not cached and not force:
        print("Cache de matchup ausente; atualizando via scrape HTML...")

    print("Atualizando cache de matchups (defesa vs posicao) via scrape HTML...")
    data = _scrape_defense_vs_position()
    if data:
        save_matchup_cache(data)
        print(f"Dados de matchup salvos: {len(data)} entradas")
        return data

    if cached:
        print("Falha ao atualizar matchup; preservando cache existente.")
        return cached

    return {}


def print_matchup_summary(matchup_data: Dict[str, Dict]) -> None:
    print("\n" + "=" * 60)
    print("     RESUMO: TIMES PIORES DEFENSAS POR POSICAO")
    print("=" * 60)

    prop_labels = {
        "def_pts_vs_pos": "PTS cedidos",
        "def_reb_vs_pos": "REB cedidos",
        "def_ast_vs_pos": "AST cedidos",
        "def_3pm_vs_pos": "3PM cedidos",
    }

    for stat_key, label in prop_labels.items():
        entries = []
        for key, m in matchup_data.items():
            val = m.get(stat_key, 0)
            if val > 0:
                entries.append((m["team"], m["position_raw"], val))
        entries.sort(key=lambda x: -x[2])
        print(f"\n{label}:")
        for team, pos, val in entries[:5]:
            print(f"  {team:22s} vs {pos}: {val:.1f}")

    print("=" * 60)
