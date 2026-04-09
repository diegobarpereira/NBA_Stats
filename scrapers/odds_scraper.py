import json
import requests
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path

import config


MARKET_KEY_TO_TYPE = {
    "player_points": "points",
    "player_rebounds": "rebounds",
    "player_assists": "assists",
    "player_threes": "3pt",
}


def _normalize_player_name(name: str) -> str:
    name = re.sub(r"[^a-z\s]", "", name.lower().replace("'", "").replace("-", " "))
    name = re.sub(r"\s+", " ", name).strip()
    return name


def fetch_nba_events_for_date(date: str, api_key: str = None) -> List[Dict]:
    if api_key is None:
        api_key = config.THE_ODDS_API_KEY
    
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "decimal"
    }
    
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    events = response.json()
    
    target_date = datetime.strptime(date, "%Y-%m-%d").date()
    next_date = target_date + timedelta(days=1)
    
    filtered = []
    for event in events:
        commence = event.get("commence_time", "")
        if not commence:
            continue
        
        event_date = datetime.fromisoformat(commence.replace("Z", "+00:00")).date()
        
        # Include games on target_date AND next day (covers EST late games that become UTC next day)
        if event_date == target_date or event_date == next_date:
            filtered.append({
                "event_id": event["id"],
                "home_team": event["home_team"],
                "away_team": event["away_team"],
                "commence_time": commence,
            })
    
    return filtered


def fetch_player_props_for_event(event_id: str, api_key: str = None) -> Dict:
    if api_key is None:
        api_key = config.THE_ODDS_API_KEY
    
    url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds"
    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": "player_points,player_rebounds,player_assists,player_threes",
        "oddsFormat": "decimal"
    }
    
    response = requests.get(url, params=params, timeout=30)
    
    if response.status_code != 200:
        return {}
    
    data = response.json()
    bookmakers = data.get("bookmakers", [])
    
    result = {}
    
    for bookmaker in bookmakers:
        bm_name = bookmaker.get("title", "")
        markets = bookmaker.get("markets", [])
        
        for market in markets:
            market_key = market.get("key", "")
            prop_type = MARKET_KEY_TO_TYPE.get(market_key)
            if not prop_type:
                continue
            
            outcomes = market.get("outcomes", [])
            
            for outcome in outcomes:
                name = outcome.get("name", "")
                description = outcome.get("description", "")
                price = outcome.get("price", 0)
                point = outcome.get("point", 0)
                
                player_name = description if description else name
                if not player_name:
                    continue
                
                key = _normalize_player_name(player_name)
                
                if key not in result:
                    result[key] = {
                        "player_name": player_name,
                        "prop_type": prop_type,
                        "line": point,
                        "odds_over": price,
                        "odds_under": price,
                        "bookmakers": {},
                    }
                
                result[key]["bookmakers"][bm_name] = {
                    "over": price if name == "Over" else result[key]["bookmakers"].get(bm_name, {}).get("over", price),
                    "under": price if name == "Under" else result[key]["bookmakers"].get(bm_name, {}).get("under", price),
                    "line": point,
                }
                
                if name == "Over":
                    result[key]["odds_over"] = price
                    result[key]["line"] = point
                elif name == "Under":
                    result[key]["odds_under"] = price
    
    return result


def fetch_and_cache_odds(date: str, api_key: str = None) -> Dict:
    if api_key is None:
        api_key = config.THE_ODDS_API_KEY
    
    events = fetch_nba_events_for_date(date, api_key)
    
    all_odds = {
        "date": date,
        "fetched_at": datetime.now().isoformat(),
        "events": {},
        "player_props": {},
    }
    
    for event in events:
        event_id = event["event_id"]
        
        all_odds["events"][event_id] = {
            "home_team": event["home_team"],
            "away_team": event["away_team"],
            "commence_time": event["commence_time"],
        }
        
        props = fetch_player_props_for_event(event_id, api_key)
        
        for key, prop_data in props.items():
            if key not in all_odds["player_props"]:
                all_odds["player_props"][key] = prop_data
            else:
                existing = all_odds["player_props"][key]
                existing["bookmakers"].update(prop_data["bookmakers"])
                if prop_data.get("odds_over"):
                    existing["odds_over"] = prop_data["odds_over"]
                if prop_data.get("odds_under"):
                    existing["odds_under"] = prop_data["odds_under"]
    
    cache_path = config.DATA_DIR / f"odds_cache_{date}.json"
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(all_odds, f, indent=2, ensure_ascii=False)
    
    return all_odds


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


def get_odds_for_player(
    player_name: str,
    prop_type: str,
    line: float,
    date: str,
    preferred_bookmakers: List[str] = None,
) -> Optional[Dict]:
    if preferred_bookmakers is None:
        preferred_bookmakers = ["FanDuel", "DraftKings", "BetMGM", "BetRivers"]
    
    cached = load_cached_odds(date)
    if not cached:
        return None
    
    normalized = _normalize_player_name(player_name)
    player_props = cached.get("player_props", {})
    
    if normalized in player_props:
        prop_data = player_props[normalized]
        
        if prop_data.get("prop_type") != prop_type:
            return None
        
        prop_line = prop_data.get("line", 0)
        if abs(prop_line - line) > 1.0:
            return None
        
        for bm in preferred_bookmakers:
            if bm in prop_data.get("bookmakers", {}):
                bm_odds = prop_data["bookmakers"][bm]
                return {
                    "odds_over": bm_odds.get("over", prop_data.get("odds_over", 1.9)),
                    "odds_under": bm_odds.get("under", prop_data.get("odds_under", 1.9)),
                    "line": prop_line,
                    "bookmaker": bm,
                    "source": "api",
                }
        
        return {
            "odds_over": prop_data.get("odds_over", 1.9),
            "odds_under": prop_data.get("odds_under", 1.9),
            "line": prop_line,
            "bookmaker": list(prop_data.get("bookmakers", {}).keys())[0] if prop_data.get("bookmakers") else "Unknown",
            "source": "api",
        }
    
    for key, prop_data in player_props.items():
        if normalized in key or key in normalized:
            if prop_data.get("prop_type") != prop_type:
                continue
            
            prop_line = prop_data.get("line", 0)
            if abs(prop_line - line) > 1.0:
                continue
            
            for bm in preferred_bookmakers:
                if bm in prop_data.get("bookmakers", {}):
                    bm_odds = prop_data["bookmakers"][bm]
                    return {
                        "odds_over": bm_odds.get("over", prop_data.get("odds_over", 1.9)),
                        "odds_under": bm_odds.get("under", prop_data.get("odds_under", 1.9)),
                        "line": prop_line,
                        "bookmaker": bm,
                        "source": "api",
                    }
            
            return {
                "odds_over": prop_data.get("odds_over", 1.9),
                "odds_under": prop_data.get("odds_under", 1.9),
                "line": prop_line,
                "bookmaker": list(prop_data.get("bookmakers", {}).keys())[0] if prop_data.get("bookmakers") else "Unknown",
                "source": "api",
            }
    
    return None


def ensure_odds_for_date(date: str) -> Dict:
    cached = load_cached_odds(date)
    if cached:
        return cached
    
    return fetch_and_cache_odds(date)