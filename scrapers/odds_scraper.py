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

PRIMARY_REFERENCE_BOOKMAKERS = ("FanDuel", "DraftKings")
TARGET_BOOKMAKER = "Bet365"
GENERIC_PLAYER_PROPS_MARKET = "Player Props"

BET365_NBA_MARKETS = {
    "Points O/U": "points",
    "Rebounds O/U": "rebounds",
    "Assists O/U": "assists",
    "Threes Made O/U": "3pt",
}


def _parse_generic_player_prop_label(label: str) -> tuple[str, str]:
    parsed = str(label or "").strip()
    match = re.match(r"^(.*?)\s+\((.*?)\)$", parsed)
    if not match:
        return parsed, ""

    player = match.group(1).strip()
    market_name = match.group(2).strip().lower()
    prop_type = {
        "points": "points",
        "rebounds": "rebounds",
        "assists": "assists",
        "threes made": "3pt",
        "3-pointers made": "3pt",
        "three pointers made": "3pt",
    }.get(market_name, "")
    return player, prop_type


def _normalize_bookmaker_name(name: str) -> str:
    normalized = str(name or "").strip()
    if normalized == "Bet365 (no latency)":
        return TARGET_BOOKMAKER
    return normalized


def _allowed_bookmakers_from_error(message: str) -> List[str]:
    match = re.search(r"Allowed:\s*([^\.]+)", str(message or ""), re.IGNORECASE)
    if not match:
        return []
    return [_normalize_bookmaker_name(item.strip()) for item in match.group(1).split(",") if item.strip()]


def _request_with_allowed_bookmakers(url: str, params_builder, requested_bookmakers: List[str], timeout: int = 60):
    response = requests.get(url, params=params_builder(requested_bookmakers), timeout=timeout)
    final_bookmakers = list(requested_bookmakers)
    if response.status_code == 403:
        allowed = _allowed_bookmakers_from_error(response.text)
        if allowed:
            fallback_bookmakers = [book for book in requested_bookmakers if book in allowed]
            extra_allowed = [book for book in allowed if book not in fallback_bookmakers]
            final_bookmakers = fallback_bookmakers + extra_allowed
            if final_bookmakers:
                response = requests.get(url, params=params_builder(final_bookmakers), timeout=timeout)
    return response, final_bookmakers


def _build_line_key(line) -> str:
    if line is None:
        return "-"
    try:
        return f"{float(line):.1f}"
    except (TypeError, ValueError):
        return str(line)


def _best_price_entry(prices: Dict, side: str, allowed_books: Optional[List[str]] = None) -> Optional[Dict]:
    best_book = None
    best_price = None
    for bookmaker, odds in (prices or {}).items():
        if allowed_books and bookmaker not in allowed_books:
            continue
        candidate = _to_float((odds or {}).get(side), 0)
        if candidate <= 1.01:
            continue
        if best_price is None or candidate > best_price:
            best_price = candidate
            best_book = bookmaker

    if best_book is None or best_price is None:
        return None

    return {
        "bookmaker": best_book,
        "odds": round(best_price, 2),
    }


def _extract_row_prices(row: Dict) -> Dict:
    prices = dict(row.get("prices") or {})
    bookmaker = _normalize_bookmaker_name(row.get("bookmaker", TARGET_BOOKMAKER))
    if bookmaker and bookmaker not in prices:
        over = _to_float(row.get("over"), 0)
        under = _to_float(row.get("under"), 0)
        if over > 1.01 or under > 1.01:
            prices[bookmaker] = {
                "over": over,
                "under": under,
            }
    return prices


def _cache_supports_crossbook_reference(cached: Optional[Dict]) -> bool:
    if not cached:
        return False
    if cached.get("schema_version", 1) >= 2:
        return True
    first_prop = next(iter(cached.get("player_props", [])), None)
    return bool(first_prop and first_prop.get("prices"))


def _market_lines_from_prices(player: str, prop_type: str, rows: List[Dict], allowed_books: Optional[List[str]] = None) -> List[Dict]:
    line_map = {}
    for row in rows:
        row_prices = _extract_row_prices(row)
        line = row.get("line")
        line_key = _build_line_key(line)
        line_entry = line_map.setdefault(
            line_key,
            {
                "player": player,
                "type": prop_type,
                "line": _to_float(line, None),
                "over": 0,
                "under": 0,
                "bookmaker": "",
                "over_bookmaker": "",
                "under_bookmaker": "",
            },
        )

        best_over = _best_price_entry(row_prices, "over", allowed_books)
        best_under = _best_price_entry(row_prices, "under", allowed_books)
        if best_over:
            line_entry["over"] = best_over["odds"]
            line_entry["over_bookmaker"] = best_over["bookmaker"]
        if best_under:
            line_entry["under"] = best_under["odds"]
            line_entry["under_bookmaker"] = best_under["bookmaker"]

        preferred_book = line_entry.get("over_bookmaker") or line_entry.get("under_bookmaker")
        if preferred_book:
            line_entry["bookmaker"] = preferred_book

    return [entry for entry in line_map.values() if entry.get("line") is not None]


def _attach_reference_context(selected_payload: Dict, reference_payload: Optional[Dict]) -> Dict:
    enriched = dict(selected_payload)
    if not reference_payload:
        enriched["reference_bookmakers"] = []
        return enriched

    reference_over = _to_float(reference_payload.get("odds_over"), 0)
    reference_under = _to_float(reference_payload.get("odds_under"), 0)
    selected_over = _to_float(enriched.get("odds_over"), 0)
    selected_under = _to_float(enriched.get("odds_under"), 0)

    enriched["reference_line"] = reference_payload.get("reference_line", reference_payload.get("line"))
    enriched["reference_lines"] = reference_payload.get("reference_lines", [reference_payload.get("reference_line", reference_payload.get("line"))])
    enriched["reference_odds_over"] = reference_over if reference_over > 1.01 else None
    enriched["reference_odds_under"] = reference_under if reference_under > 1.01 else None
    enriched["reference_source"] = reference_payload.get("source", "reference_market")
    enriched["reference_bookmaker"] = reference_payload.get("bookmaker", "")
    enriched["reference_bookmakers"] = reference_payload.get("reference_bookmakers", [])
    enriched["price_delta_over"] = round(selected_over - reference_over, 2) if selected_over > 1.01 and reference_over > 1.01 else None
    enriched["price_delta_under"] = round(selected_under - reference_under, 2) if selected_under > 1.01 and reference_under > 1.01 else None
    return enriched


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


def _get_under_probability(market: Dict, over_probability: float) -> float:
    under_odds = _to_float(market.get("under"), 0)
    if under_odds > 1.01:
        return _decimal_to_probability(under_odds)
    return max(0.05, min(0.95, 1.0 - over_probability))


def _approximate_probability_from_market_lines(prop_type: str, target_line: float, market_lines: List[Dict]) -> Optional[Dict]:
    usable = []
    for market in market_lines:
        line = _to_float(market.get("line"), -1)
        over = _to_float(market.get("over"), 0)
        if line < 0 or over <= 1.01:
            continue
        over_probability = _decimal_to_probability(over)
        under_probability = _get_under_probability(market, over_probability)
        usable.append({
            "line": line,
            "over": over,
            "under": _to_float(market.get("under"), 0),
            "probability": over_probability,
            "under_probability": under_probability,
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
            "reference_lines": [exact_match["line"]],
            "odds_over": exact_match["over"],
            "odds_under": exact_match["under"] if exact_match.get("under", 0) > 1.01 else _probability_to_decimal(exact_match["under_probability"]),
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
        under_probability = lower["under_probability"] + (upper["under_probability"] - lower["under_probability"]) * ratio
        nearest = lower if abs(target_line - lower["line"]) <= abs(target_line - upper["line"]) else upper
        return {
            "player": nearest["player"],
            "type": prop_type,
            "line": round(target_line, 1),
            "reference_line": nearest["line"],
            "reference_lines": [lower["line"], upper["line"]],
            "odds_over": _probability_to_decimal(probability),
            "odds_under": _probability_to_decimal(under_probability),
            "bookmaker": nearest["bookmaker"],
            "source": "market_approx",
        }

    nearest = min(usable, key=lambda item: abs(item["line"] - target_line))
    delta = target_line - nearest["line"]
    probability = nearest["probability"] - (delta * _get_probability_slope(prop_type))
    under_probability = max(0.05, min(0.95, 1.0 - probability))
    return {
        "player": nearest["player"],
        "type": prop_type,
        "line": round(target_line, 1),
        "reference_line": nearest["line"],
        "reference_lines": [nearest["line"]],
        "odds_over": _probability_to_decimal(probability),
        "odds_under": _probability_to_decimal(under_probability),
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


def fetch_player_props_for_event(event_id: str, reference_api_key: str = None, target_api_key: str = None) -> Dict:
    if reference_api_key is None:
        reference_api_key = config.THE_ODDS_API_REFERENCE_KEY
    if target_api_key is None:
        target_api_key = config.THE_ODDS_API_TARGET_KEY

    url = "https://api.odds-api.io/v3/odds"
    result = {}

    def build_params(api_key: str, bookmakers: List[str], markets: List[str]):
        params = [
            ("apiKey", api_key),
            ("eventId", event_id),
            ("bookmakers", ",".join(bookmakers)),
        ]
        for market in markets:
            params.append(("markets", market))
        return params

    if reference_api_key:
        requested_reference_books = list(PRIMARY_REFERENCE_BOOKMAKERS)
        response, used_reference_books = _request_with_allowed_bookmakers(
            url,
            lambda books: build_params(reference_api_key, books, [GENERIC_PLAYER_PROPS_MARKET]),
            requested_reference_books,
        )
        if response.status_code == 200:
            data = response.json()
            bookmakers_raw = data.get("bookmakers") or {}
            for bm_name, markets in bookmakers_raw.items():
                bookmaker_name = _normalize_bookmaker_name(bm_name)
                if bookmaker_name not in used_reference_books:
                    continue
                for market in markets:
                    if market.get("name", "") != GENERIC_PLAYER_PROPS_MARKET:
                        continue
                    for odd in market.get("odds") or []:
                        player, prop_type = _parse_generic_player_prop_label(odd.get("label") or odd.get("name"))
                        if not prop_type or not player or player == "-":
                            continue
                        line = odd.get("hdp")
                        line_key = "-" if line is None else str(line)
                        key = f"{_normalize_player_name(player)}::{prop_type}::{line_key}"
                        if key not in result:
                            result[key] = {
                                "player": player,
                                "prop_type": prop_type,
                                "line": line,
                                "bookmaker": TARGET_BOOKMAKER,
                                "prices": {},
                            }
                        result[key]["prices"][bookmaker_name] = {
                            "over": _to_float(odd.get("over"), 0),
                            "under": _to_float(odd.get("under"), 0),
                        }
                        if line is not None:
                            result[key]["line"] = line

    if target_api_key:
        requested_target_books = [TARGET_BOOKMAKER]
        response, used_target_books = _request_with_allowed_bookmakers(
            url,
            lambda books: build_params(target_api_key, books, list(BET365_NBA_MARKETS.keys())),
            requested_target_books,
        )
        if response.status_code == 200:
            data = response.json()
            bookmakers_raw = data.get("bookmakers") or {}
            for bm_name, markets in bookmakers_raw.items():
                bookmaker_name = _normalize_bookmaker_name(bm_name)
                if bookmaker_name not in used_target_books:
                    continue
                for market in markets:
                    market_name = market.get("name", "")
                    for odd in market.get("odds") or []:
                        prop_type = BET365_NBA_MARKETS.get(market_name, "")
                        player = clean_player_label(odd.get("label") or odd.get("name"))
                        if not prop_type or not player or player == "-":
                            continue
                        line = odd.get("hdp")
                        line_key = "-" if line is None else str(line)
                        key = f"{_normalize_player_name(player)}::{prop_type}::{line_key}"
                        if key not in result:
                            result[key] = {
                                "player": player,
                                "prop_type": prop_type,
                                "line": line,
                                "bookmaker": TARGET_BOOKMAKER,
                                "prices": {},
                            }
                        result[key]["prices"][bookmaker_name] = {
                            "over": _to_float(odd.get("over"), 0),
                            "under": _to_float(odd.get("under"), 0),
                        }
                        if line is not None:
                            result[key]["line"] = line

    for prop in result.values():
        bet365_prices = (prop.get("prices") or {}).get(TARGET_BOOKMAKER, {})
        reference_prices = {book: odds for book, odds in (prop.get("prices") or {}).items() if book != TARGET_BOOKMAKER}
        best_over = _best_price_entry(prop.get("prices", {}), "over")
        best_under = _best_price_entry(prop.get("prices", {}), "under")
        best_reference_over = _best_price_entry(reference_prices, "over")
        best_reference_under = _best_price_entry(reference_prices, "under")
        prop["over"] = _to_float(bet365_prices.get("over"), 0)
        prop["under"] = _to_float(bet365_prices.get("under"), 0)
        prop["best_over"] = best_over["odds"] if best_over else None
        prop["best_under"] = best_under["odds"] if best_under else None
        prop["best_over_bookmaker"] = best_over["bookmaker"] if best_over else ""
        prop["best_under_bookmaker"] = best_under["bookmaker"] if best_under else ""
        prop["reference_over"] = best_reference_over["odds"] if best_reference_over else None
        prop["reference_under"] = best_reference_under["odds"] if best_reference_under else None
        prop["reference_over_bookmaker"] = best_reference_over["bookmaker"] if best_reference_over else ""
        prop["reference_under_bookmaker"] = best_reference_under["bookmaker"] if best_reference_under else ""
        prop["reference_bookmakers"] = [book for book in prop.get("prices", {}) if book != TARGET_BOOKMAKER]
    
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
        api_key = config.THE_ODDS_API_TARGET_KEY or config.THE_ODDS_API_REFERENCE_KEY or config.THE_ODDS_API_KEY
    
    cached = load_cached_odds(date)
    if _cache_supports_crossbook_reference(cached):
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
        
        props = fetch_player_props_for_event(
            event_id,
            reference_api_key=config.THE_ODDS_API_REFERENCE_KEY,
            target_api_key=config.THE_ODDS_API_TARGET_KEY,
        )
        for key, prop in props.items():
            if key not in all_odds:
                all_odds[key] = {
                    **prop,
                    "event_id": event_id,
                    "source": "api",
                }
    
    result = {
        "date": date,
        "schema_version": 2,
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

    bet365_lines = _market_lines_from_prices(player_name, prop_type, matching_lines, [TARGET_BOOKMAKER])
    available_reference_books = sorted({book for row in matching_lines for book in _extract_row_prices(row).keys() if book != TARGET_BOOKMAKER})
    reference_lines = _market_lines_from_prices(player_name, prop_type, matching_lines, available_reference_books)

    if not bet365_lines:
        return None

    approximated = _approximate_probability_from_market_lines(prop_type, _to_float(line, 0.0), bet365_lines)
    if approximated is None:
        return None

    reference_payload = _approximate_probability_from_market_lines(prop_type, _to_float(line, 0.0), reference_lines) if reference_lines else None
    if reference_payload is not None:
        reference_payload["reference_bookmakers"] = available_reference_books

    exact_line = next(
        (
            item for item in matching_lines
            if abs(_to_float(item.get("line"), -99) - _to_float(line, 0.0)) <= 0.26 and _to_float(_extract_row_prices(item).get(TARGET_BOOKMAKER, {}).get("over"), 0) > 1.01
        ),
        None,
    )
    if exact_line is not None:
        exact_prices = _extract_row_prices(exact_line)
        exact_payload = {
            "player": exact_line.get("player"),
            "type": exact_line.get("prop_type"),
            "line": exact_line.get("line", 0),
            "reference_line": exact_line.get("line", 0),
            "reference_lines": [exact_line.get("line", 0)],
            "odds_over": exact_prices.get(TARGET_BOOKMAKER, {}).get("over"),
            "odds_under": exact_prices.get(TARGET_BOOKMAKER, {}).get("under"),
            "bookmaker": exact_line.get("bookmaker", TARGET_BOOKMAKER),
            "source": "api",
        }

        return _attach_reference_context(exact_payload, reference_payload)

    return _attach_reference_context(approximated, reference_payload)


def ensure_odds_for_date(date: str) -> Dict:
    if not config.THE_ODDS_API_KEY:
        return {"date": date, "events": {}, "player_props": []}
    
    return fetch_and_cache_odds(date)