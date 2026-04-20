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
                
                key = _normalize_player_name(player)
                
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
                    if over and not result[key].get("over"):
                        result[key]["over"] = over
                    if under and not result[key].get("under"):
                        result[key]["under"] = under
    
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
    
    for prop in props:
        if prop.get("prop_type") != prop_type:
            continue
        
        prop_player = prop.get("player", "")
        if _normalize_player_name(prop_player) == normalize_name:
            line_match = abs(prop.get("line", 0) - line) < 0.5
            if line_match or line == 0:
                return {
                    "player": prop.get("player"),
                    "type": prop.get("prop_type"),
                    "line": prop.get("line", 0),
                    "odds_over": prop.get("over"),
                    "odds_under": prop.get("under"),
                    "bookmaker": prop.get("bookmaker", "Bet365"),
                    "source": "api",
                }
    
    return None


def ensure_odds_for_date(date: str) -> Dict:
    if not config.THE_ODDS_API_KEY:
        return {"date": date, "events": {}, "player_props": []}
    
    return fetch_and_cache_odds(date)