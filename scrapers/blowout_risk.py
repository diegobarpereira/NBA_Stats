import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

import config


STANDINGS_CACHE = config.DATA_DIR / "cache_standings.json"
BLOWOUT_CACHE = config.DATA_DIR / "cache_blowout_risk.json"


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, */*",
    "Referer": "https://www.espn.com/",
}


_LEAGUE_AVG_PPG = 115.0
_LEAGUE_AVG_WIN_PCT = 0.500


_TEAM_ALIASES = {
    "LA Clippers": "Los Angeles Clippers",
    "Golden State Warriors": "Golden State Warriors",
}


def _normalize_team(team_name: str) -> str:
    return _TEAM_ALIASES.get(team_name, team_name)


def _calculate_team_strength_from_cache(
    team_name: str,
    stats_cache: Dict[str, Dict],
    injured: Dict[str, str],
    teams_data: List[Dict],
) -> Dict:
    normalized = _normalize_team(team_name)

    available_ppgs = []
    injured_ppgs = []
    all_ppgs = []

    for player_name, player_data in stats_cache.items():
        cache_team = _normalize_team(player_data.get("team", ""))
        if cache_team != normalized:
            continue

        ppg = player_data.get("avgPoints_season", 0)
        if ppg <= 0:
            ppg = player_data.get("avgPoints_last5", 0)

        if player_name in injured and injured[player_name] in ("OUT", "DOUBTFUL"):
            injured_ppgs.append(ppg)
        else:
            available_ppgs.append(ppg)
        all_ppgs.append(ppg)

    if not available_ppgs:
        injured_count = sum(
            1 for pn in injured
            if pn in injured and injured[pn] in ("OUT", "DOUBTFUL")
        )
        estimated_ppg = _LEAGUE_AVG_PPG * 0.85 * (1 - injured_count * 0.03)
        available_ppgs = [estimated_ppg]

    team_ppg = sum(available_ppgs) / max(len(available_ppgs), 1)

    top5_ppgs = sorted(available_ppgs, reverse=True)[:5]
    starter_ppg = sum(top5_ppgs) / max(len(top5_ppgs), 1)
    bench_ppgs_list = available_ppgs[5:]
    bench_ppg = sum(bench_ppgs_list) / max(len(bench_ppgs_list), 1) if bench_ppgs_list else 0

    total_available = sum(available_ppgs)
    total_all = sum(all_ppgs)
    injured_pct = (total_all - total_available) / total_all if total_all > 0 else 0

    strength = team_ppg / _LEAGUE_AVG_PPG
    adjusted_strength = strength * (1 - injured_pct * 0.8)

    return {
        "team_ppg": round(team_ppg, 1),
        "starter_ppg": round(starter_ppg, 1),
        "bench_ppg": round(bench_ppg, 1),
        "injured_pct": round(injured_pct, 3),
        "injured_ppg_lost": round(sum(injured_ppgs), 1),
        "available_players": len(available_ppgs),
        "total_players": len(all_ppgs),
        "strength": round(adjusted_strength, 3),
        "raw_strength": round(strength, 3),
    }


def calculate_blowout_risk(
    game: Dict,
    stats_cache: Dict[str, Dict],
    injured_players: Dict[str, str],
    all_teams: List[Dict],
) -> Dict:
    home_name = game["home"]
    away_name = game["away"]

    home_strength = _calculate_team_strength_from_cache(
        home_name, stats_cache, injured_players, all_teams
    )
    away_strength = _calculate_team_strength_from_cache(
        away_name, stats_cache, injured_players, all_teams
    )

    strength_gap = abs(home_strength["strength"] - away_strength["strength"])

    home_injured_pct = home_strength["injured_pct"]
    away_injured_pct = away_strength["injured_pct"]
    injury_impact = max(home_injured_pct, away_injured_pct)

    starter_gap = abs(
        home_strength["starter_ppg"] - away_strength["starter_ppg"]
    ) / _LEAGUE_AVG_PPG

    projected_margin = (
        abs(home_strength["team_ppg"] - away_strength["team_ppg"]) * 0.5
    )

    raw_risk = (
        strength_gap * 0.40
        + min(starter_gap, 0.8) * 0.25
        + min(projected_margin / 15, 1.0) * 0.20
        + injury_impact * 0.15
    )

    blowout_prob = min(max(raw_risk * 1.4, 0.05), 0.80)

    if home_strength["strength"] > away_strength["strength"]:
        favored = home_name
        underdog = away_name
    elif away_strength["strength"] > home_strength["strength"]:
        favored = away_name
        underdog = home_name
    else:
        favored = None
        underdog = None

    if blowout_prob > 0.45:
        direction = favored
        loser = underdog
    elif blowout_prob < 0.20:
        direction = "competitive"
        loser = None
    else:
        direction = favored if favored else "uncertain"
        loser = underdog if underdog else None

    min_mult = 1.0
    max_mult = 1.0

    if blowout_prob > 0.30:
        min_mult = max(0.60, 1.0 - blowout_prob * 0.55)
        max_mult = min(1.50, 1.0 + blowout_prob * 0.40)

    return {
        "game_id": game["id"],
        "home": home_name,
        "away": away_name,
        "blowout_prob": round(blowout_prob, 3),
        "direction": direction,
        "loser": loser,
        "projected_margin": round(projected_margin, 1),
        "strength_gap": round(strength_gap, 3),
        "injury_impact": round(injury_impact, 3),
        "home_strength": round(home_strength["strength"], 3),
        "away_strength": round(away_strength["strength"], 3),
        "home_ppg": home_strength["team_ppg"],
        "away_ppg": away_strength["team_ppg"],
        "home_starter_ppg": home_strength["starter_ppg"],
        "away_starter_ppg": away_strength["starter_ppg"],
        "home_injured_pct": home_injured_pct,
        "away_injured_pct": away_injured_pct,
        "minute_mult_min": round(min_mult, 3),
        "minute_mult_max": round(max_mult, 3),
        "risk_level": _risk_label(blowout_prob),
    }


def _risk_label(prob: float) -> str:
    if prob >= 0.55:
        return "high"
    elif prob >= 0.35:
        return "medium"
    elif prob >= 0.20:
        return "low"
    else:
        return "very_low"


def load_standings() -> Dict[str, Dict]:
    if STANDINGS_CACHE.exists():
        with open(STANDINGS_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_standings(data: Dict[str, Dict]) -> None:
    with open(STANDINGS_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def fetch_standings(force: bool = False) -> Dict[str, Dict]:
    if not force:
        cached = load_standings()
        if cached:
            return cached
    return {}


def analyze_games_blowout_risk(
    games: List[Dict],
    stats_cache: Dict[str, Dict],
    injured: Dict[str, str],
    all_teams: List[Dict],
) -> Dict[str, Dict]:
    results = {}
    for game in games:
        rid = calculate_blowout_risk(game, stats_cache, injured, all_teams)
        results[game["id"]] = rid
    return results


def print_blowout_summary(risk_data: Dict[str, Dict]) -> None:
    print("\n" + "=" * 70)
    print("               ANALISE DE RISCO DE BLOWOUT")
    print("=" * 70)

    sorted_games = sorted(
        risk_data.values(),
        key=lambda x: -x["blowout_prob"]
    )

    for rid in sorted_games:
        prob = rid["blowout_prob"]
        level = rid["risk_level"].upper()
        print(f"\n{rid['away']:22s} @ {rid['home']:22s}  [{level}] {prob:.0%}")
        print(
            f"  Forca: {rid['away']:15s} {rid['away_strength']:.3f} ({rid['away_ppg']:.0f} PPG) | "
            f"{rid['home']:15s} {rid['home_strength']:.3f} ({rid['home_ppg']:.0f} PPG)"
        )
        if rid['home_injured_pct'] > 0 or rid['away_injured_pct'] > 0:
            print(
                f"  Lesoes: {rid['away']:15s} {rid['away_injured_pct']:.0%} | "
                f"{rid['home']:15s} {rid['home_injured_pct']:.0%}"
            )
        print(f"  Gap forca: {rid['strength_gap']:.0%} | Proj. Margem: {rid['projected_margin']:+.1f}pts")
        if rid["direction"] and rid["direction"] != "competitive":
            print(f"  >> {rid['direction']} favorito (perdedor: {rid['loser']})")
            print(f"  Mult minutos starters no perdedor: {rid['minute_mult_min']:.0%} ~ {rid['minute_mult_max']:.0%}")

    print("\n" + "=" * 70)
