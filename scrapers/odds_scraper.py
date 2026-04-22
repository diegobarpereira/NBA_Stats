import json
import requests
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path

import config

MARKET_KEY_TO_TYPE = {
    "player_points": "points",
    "player_rebounds": "rebounds",
    "player_assists": "assists",
    "player_threes": "3pt",
}

BET365_NBA_MARKETS = {
    "Points O/U": "points",
    "Rebounds O/U": "rebounds",
    "Assists O/U": "assists",
    "Threes Made O/U": "3pt",
}


def _normalize_player_name(name: str) -> str:
    name = re.sub(r"[^a-z\s]", "", name.lower().replace("'", "").replace("-", " "))
    name = re.sub(r"\s+", " ", name).strip()
    return name


def clean_player_label(label: str) -> str:
    parsed = str(label or "").strip()
    if not parsed:
        return "-"
    while True:
        updated = re.sub(r"\s+\((?:\d+(?:\.\d+)?)\)$", "", parsed).strip()
        if updated == parsed:
            break
        parsed = updated
    return parsed or "-"


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _decimal_to_probability(odds: float) -> float:
    odds = max(_to_float(odds, 2.0), 1.01)
    return 1.0 / odds


def _probability_to_decimal(probability: float) -> float:
    probability = max(0.05, min(probability, 0.95))
    return round(1.0 / probability, 2)


def _get_probability_slope(prop_type: str) -> float:
    return {
        "points": 0.055,
        "rebounds": 0.085,
        "assists": 0.09,
        "3pt": 0.11,
    }.get(prop_type, 0.07)


def _approximate_probability_from_market_lines(prop_type: str, target_line: float, market_lines: List[Dict]) -> Optional[Dict]:
    usable = []
    for market in market_lines:
        line = _to_float(market.get("line"), -1)
        over = _to_float(market.get("over"), 0)
        if line < 0 or over <= 1.01:
            continue
        usable.append({
            "line": line,
            "over": over,
            "probability": _decimal_to_probability(over),
            "player": market.get("player", ""),
            "bookmaker": market.get("bookmaker", "Bet365"),
        })

    usable.sort(key=lambda item: item["line"])
    if not usable:
        return None

    exact_match = next((item for item in usable if abs(item["line"] - target_line) <= 0.26), None)
    if exact_match is not None:
        return {
            "player": exact_match["player"],
            "type": prop_type,
            "line": exact_match["line"],
            "reference_line": exact_match["line"],
            "odds_over": exact_match["over"],
            "bookmaker": exact_match["bookmaker"],
            "source": "api",
        }

    lower = None
    upper = None
    for item in usable:
        if item["line"] <= target_line:
            lower = item
        if item["line"] >= target_line and upper is None:
            upper = item

    if lower and upper and lower["line"] != upper["line"]:
        ratio = (target_line - lower["line"]) / (upper["line"] - lower["line"])
        probability = lower["probability"] + (upper["probability"] - lower["probability"]) * ratio
        nearest = lower if abs(target_line - lower["line"]) <= abs(target_line - upper["line"]) else upper
        return {
            "player": nearest["player"],
            "type": prop_type,
            "line": round(target_line, 1),
            "reference_line": nearest["line"],
            "reference_lines": [lower["line"], upper["line"]],
            "odds_over": _probability_to_decimal(probability),
            "bookmaker": nearest["bookmaker"],
            "source": "market_approx",
        }

    nearest = min(usable, key=lambda item: abs(item["line"] - target_line))
    delta = target_line - nearest["line"]
    probability = nearest["probability"] - (delta * _get_probability_slope(prop_type))
    return {
        "player": nearest["player"],
        "type": prop_type,
        "line": round(target_line, 1),
        "reference_line": nearest["line"],
        "reference_lines": [nearest["line"]],
        "odds_over": _probability_to_decimal(probability),
        "bookmaker": nearest["bookmaker"],
        "source": "market_approx",
    }


def fetch_nba_events_for_date(date: str, api_key: str = None) -> List[Dict]:
    if api_key is None:
        api_key = config.THE_ODDS_API_KEY
    
    url = "https://api.odds-api.io/v3/events"
    params = {
        "apiKey": api_key,
        "sport": "basketball",
        "league": "usa-nba",
        "status": "pending",
        "limit": 12,
    }
    
    response = requests.get(url, params=params, timeout=60)
    response.raise_for_status()
    events = response.json()
    
    target_date = datetime.strptime(date, "%Y-%m-%d").date()
    next_date = target_date + timedelta(days=1)
    
    filtered = []
    for event in events:
        away = event.get("away") or "-"
        home = event.get("home") or "-"
        commence = event.get("date") or ""
        if not commence:
            continue
        
        try:
            event_date = datetime.fromisoformat(commence.replace("Z", "+00:00")).date()
        except:
            continue
        
        if event_date == target_date or event_date == next_date:
            filtered.append({
                "event_id": str(event.get("id", "")),
                "home_team": home,
                "away_team": away,
                "commence_time": commence,
            })
    
    return filtered


def fetch_player_props_for_event(event_id: str, api_key: str = None) -> Dict:
    if api_key is None:
        api_key = config.THE_ODDS_API_KEY
    
    params = [
        ("apiKey", api_key),
        ("eventId", event_id),
        ("bookmakers", "Bet365"),
    ]
    
    for market in BET365_NBA_MARKETS.keys():
        params.append(("markets", market))
    
    url = "https://api.odds-api.io/v3/odds"
    response = requests.get(url, params=params, timeout=60)
    
    if response.status_code != 200:
        return {}
    
    data = response.json()
    result = {}
    
    bookmakers_raw = data.get("bookmakers") or {}
    for bm_name, markets in bookmakers_raw.items():
        if bm_name != "Bet365":
            continue
        
        for market in markets:
            market_name = market.get("name", "")
            prop_type = BET365_NBA_MARKETS.get(market_name)
            if not prop_type:
                continue
            
            for odd in market.get("odds") or []:
                player = clean_player_label(odd.get("label") or odd.get("name"))
                over = odd.get("over")
                under = odd.get("under")
                line = odd.get("hdp")
                
                if not player or player == "-":
                    continue
                
                line_key = "-" if line is None else str(line)
                key = f"{_normalize_player_name(player)}::{prop_type}::{line_key}"
                
                if key not in result:
                    result[key] = {
                        "player": player,
                        "prop_type": prop_type,
                        "line": line,
                        "over": over,
                        "under": under,
                        "bookmaker": "Bet365",
                    }
                else:
                    if over is not None:
                        result[key]["over"] = over
                    if under is not None:
                        result[key]["under"] = under
                    if line is not None:
                        result[key]["line"] = line
    
    return result


def save_odds_cache(date: str, data: Dict) -> None:
    cache_path = config.DATA_DIR / f"odds_cache_{date}.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_cached_odds(date: str) -> Optional[Dict]:
    import time
    cache_path = config.DATA_DIR / f"odds_cache_{date}.json"
    if not cache_path.exists():
        return None
    
    cache_age = time.time() - cache_path.stat().st_mtime
    if cache_age > 21600:
        return None
    
    with open(cache_path, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_and_cache_odds(date: str, api_key: str = None) -> Dict:
    if api_key is None:
        api_key = config.THE_ODDS_API_KEY
    
    cached = load_cached_odds(date)
    if cached:
        return cached
    
    events = fetch_nba_events_for_date(date, api_key)
    if not events:
        return {"date": date, "events": {}, "player_props": []}
    
    all_odds = {}
    event_data = {}
    
    for event in events:
        event_id = event["event_id"]
        home = event["home_team"]
        away = event["away_team"]
        
        event_data[event_id] = {
            "home": home,
            "away": away,
            "commence_time": event.get("commence_time", ""),
        }
        
        props = fetch_player_props_for_event(event_id, api_key)
        for key, prop in props.items():
            if key not in all_odds:
                all_odds[key] = {
                    **prop,
                    "event_id": event_id,
                    "source": "api",
                }
    
    result = {
        "date": date,
        "events": event_data,
        "player_props": list(all_odds.values()),
    }
    
    save_odds_cache(date, result)
    return result


def get_odds_for_player(player_name: str, prop_type: str, line: float, date: str) -> Optional[Dict]:
    cached = load_cached_odds(date)
    if not cached:
        return None
    
    props = cached.get("player_props", [])
    normalize_name = _normalize_player_name(player_name)
    
    matching_lines = []
    
    for prop in props:
        if prop.get("prop_type") != prop_type:
            continue
        
        prop_player = prop.get("player", "")
        if _normalize_player_name(prop_player) == normalize_name:
            matching_lines.append(prop)

    if not matching_lines:
        return None

    approximated = _approximate_probability_from_market_lines(prop_type, _to_float(line, 0.0), matching_lines)
    if approximated is None:
        return None

    exact_line = next(
        (
            item for item in matching_lines
            if abs(_to_float(item.get("line"), -99) - _to_float(line, 0.0)) <= 0.26
        ),
        None,
    )
    if exact_line is not None:
        return {
            "player": exact_line.get("player"),
            "type": exact_line.get("prop_type"),
            "line": exact_line.get("line", 0),
            "reference_line": exact_line.get("line", 0),
            "odds_over": exact_line.get("over"),
            "odds_under": exact_line.get("under"),
            "bookmaker": exact_line.get("bookmaker", "Bet365"),
            "source": "api",
        }

    return approximated


def ensure_odds_for_date(date: str) -> Dict:
    if not config.THE_ODDS_API_KEY:
        return {"date": date, "events": {}, "player_props": []}
    
    return fetch_and_cache_odds(date)