import copy
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import config
from gerador.props_engine import PropsEngine
from scrapers.odds_scraper import get_odds_for_player, ensure_odds_for_date


def _blowout_arrow(mult: float) -> str:
    if mult > 1.0:
        return f"+{mult:.2f}"
    elif mult < 1.0:
        return f"-{mult:.2f}"
    return "1.00"


class Bilheteiro:
    def __init__(self, date: str = None):
        self.props_engine = PropsEngine()
        self.game_min_odds = config.ODDS_CONFIG["min_total_odds"]
        self.game_max_odds = config.ODDS_CONFIG["max_total_odds"]
        self.min_confidence = 8.0
        self.default_prop_odds = config.ODDS_CONFIG["default_prop_odds"]
        self.date = date or datetime.now().strftime("%Y-%m-%d")
        
        self._odds_cache = None
        self._odds_initialized = False

    def _build_odds_snapshot(self, prop: Dict) -> Dict:
        return {
            "captured_at": datetime.now().isoformat(),
            "side": prop.get("over_under", "Over"),
            "selected_odds": prop.get("odds", prop.get("dynamic_odds", prop.get("selected_odds", prop.get("odds_over", self.default_prop_odds)))),
            "odds_source": prop.get("odds_source", "unknown"),
            "bookmaker": prop.get("bookmaker", ""),
            "market_line": prop.get("market_line"),
            "market_target_line": prop.get("market_target_line"),
            "market_odds_over": prop.get("market_odds_over"),
            "market_odds_under": prop.get("market_odds_under"),
            "reference_odds_over": prop.get("reference_odds_over"),
            "reference_odds_under": prop.get("reference_odds_under"),
            "reference_source": prop.get("reference_source"),
            "reference_bookmaker": prop.get("reference_bookmaker"),
            "reference_bookmakers": prop.get("reference_bookmakers", []),
            "price_delta_over": prop.get("price_delta_over"),
            "price_delta_under": prop.get("price_delta_under"),
        }

    def _annotate_tickets_for_save(self, tickets: List[Dict]) -> List[Dict]:
        annotated = copy.deepcopy(tickets)
        snapshot_time = datetime.now().isoformat()
        for ticket in annotated:
            ticket["odds_snapshot_time"] = snapshot_time
            for prop in ticket.get("props", []):
                prop["odds_snapshot"] = self._build_odds_snapshot(prop)
                prop.setdefault("picked_odds", prop.get("odds", self.default_prop_odds))
        return annotated

    def _get_prop_confidence(self, prop: Dict) -> float:
        return float(prop.get("confidence", self.props_engine.get_confidence_score(prop)))

    def _ensure_odds_cache(self) -> None:
        if self._odds_initialized:
            return
        try:
            ensure_odds_for_date(self.date)
        except Exception:
            pass
        self._odds_initialized = True

    def _side_confidence_bonus(self, prop: Dict, side: str) -> float:
        market_line = prop.get("market_line")
        model_line = prop.get("line")
        if market_line is None or model_line is None:
            return 0.0

        gap = float(model_line) - float(market_line)
        signed_gap = gap if side == "Over" else -gap
        if signed_gap >= 1.5:
            return 1.5
        if signed_gap >= 0.75:
            return 1.0
        if signed_gap >= 0.25:
            return 0.5
        if signed_gap <= -1.5:
            return -1.5
        if signed_gap <= -0.75:
            return -1.0
        if signed_gap <= -0.25:
            return -0.5
        return 0.0

    def _under_context_penalty(self, prop: Dict) -> float:
        season_avg = float(prop.get("season_avg") or 0.0)
        last5_avg = float(prop.get("last5_avg") or 0.0)
        avg_minutes = float(prop.get("avgMinutes_last5") or 0.0)
        injury_status = prop.get("injury_status")

        penalty = 0.0

        if season_avg > 0 and last5_avg > season_avg:
            trend_ratio = (last5_avg - season_avg) / season_avg
            if trend_ratio >= 0.30:
                penalty += 1.0
            elif trend_ratio >= 0.15:
                penalty += 0.5

        if avg_minutes >= 36:
            penalty += 0.5
        elif avg_minutes >= 32:
            penalty += 0.25

        if injury_status == "QUESTIONABLE":
            penalty = max(0.0, penalty - 0.25)

        return min(1.5, penalty)

    def _calculate_odds_fallback(self, prop: Dict) -> float:
        line = prop.get("line", 0)
        prop_type = prop["type"]
        confidence = self.props_engine.get_confidence_score(prop)
        injury_status = prop.get("injury_status")
        is_fallback = prop.get("fallback", False)
        season_avg = prop.get("season_avg", 0)

        if line <= 0:
            return self.default_prop_odds

        type_config = {
            "points":   {"max": 35.0, "floor": 1.10, "ceiling": 2.10, "scale": 1.0},
            "rebounds": {"max": 14.0, "floor": 1.10, "ceiling": 2.05, "scale": 1.0},
            "assists":  {"max": 14.0, "floor": 1.10, "ceiling": 2.05, "scale": 1.0},
            "3pt":      {"max": 6.0,  "floor": 1.15, "ceiling": 2.20, "scale": 1.2},
        }
        cfg = type_config.get(prop_type, {"max": 15.0, "floor": 1.10, "ceiling": 2.05, "scale": 1.0})

        norm = min(line, cfg["max"]) / cfg["max"]
        base = cfg["floor"] + (cfg["ceiling"] - cfg["floor"]) * norm

        if season_avg > 0:
            stretch = line / season_avg
            base += (stretch - 1.0) * cfg["scale"] * 0.10

        if is_fallback:
            base = max(cfg["floor"], base - 0.05)
        elif confidence >= 8:
            base = min(cfg["ceiling"], base + 0.06)
        elif confidence <= 3:
            base = min(cfg["ceiling"], base + 0.10)

        if injury_status == "QUESTIONABLE":
            base += 0.08

        return round(max(1.10, min(2.10, base)), 2)

    def calculate_prop_odds(self, prop: Dict) -> Dict:
        confidence = self.props_engine.get_confidence_score(prop)
        self._ensure_odds_cache()
        
        if confidence >= 7:
            api_odds = get_odds_for_player(
                prop.get("player", ""),
                prop["type"],
                prop.get("line", 0),
                self.date
            )
            
            if api_odds and api_odds.get("source") in {"api", "market_approx"}:
                market_line = api_odds.get("reference_line", api_odds.get("line"))
                return {
                    "odds_source": api_odds.get("source"),
                    "bookmaker": api_odds.get("bookmaker", ""),
                    "market_line": market_line,
                    "market_target_line": api_odds.get("line"),
                    "market_odds_over": api_odds.get("odds_over", self.default_prop_odds),
                    "market_odds_under": api_odds.get("odds_under", self.default_prop_odds),
                    "reference_odds_over": api_odds.get("reference_odds_over"),
                    "reference_odds_under": api_odds.get("reference_odds_under"),
                    "reference_source": api_odds.get("reference_source"),
                    "reference_bookmaker": api_odds.get("reference_bookmaker", ""),
                    "reference_bookmakers": api_odds.get("reference_bookmakers", []),
                    "price_delta_over": api_odds.get("price_delta_over"),
                    "price_delta_under": api_odds.get("price_delta_under"),
                }

        fallback_odds = self._calculate_odds_fallback(prop)
        return {
            "odds_source": "calculated",
            "bookmaker": "",
            "market_line": None,
            "market_target_line": None,
            "market_odds_over": None,
            "market_odds_under": None,
            "fallback_odds_over": fallback_odds,
            "fallback_odds_under": fallback_odds,
        }

    def calculate_total_odds(self, props: List[Dict]) -> float:
        if not props:
            return 0.0
        total = 1.0
        for prop in props:
            odds = prop.get("dynamic_odds", prop.get("selected_odds", prop.get("odds_over")))
            if odds is None:
                odds = self.default_prop_odds
            try:
                odds = float(odds)
            except (TypeError, ValueError):
                odds = self.default_prop_odds
            total *= odds
        return round(total, 2)

    def _assign_dynamic_odds(self, props: List[Dict]) -> List[Dict]:
        result = []
        for p in props:
            p = dict(p)
            odds_payload = self.calculate_prop_odds(p)
            p.update(odds_payload)

            free_projection = self._free_projection(p)

            over_odds = odds_payload.get("market_odds_over") or odds_payload.get("fallback_odds_over") or p.get("odds_over", self.default_prop_odds)
            under_odds = odds_payload.get("market_odds_under") or odds_payload.get("fallback_odds_under") or p.get("odds_under", self.default_prop_odds)
            base_confidence = self.props_engine.get_confidence_score(p)

            over_prop = dict(p)
            over_prop["over_under"] = "Over"
            over_prop["selected_odds"] = float(over_odds)
            over_prop["dynamic_odds"] = float(over_odds)
            over_prop["free_projection"] = free_projection
            over_prop["free_score"] = self._free_side_score(p, "Over")
            over_prop["confidence"] = max(0.0, min(10.0, base_confidence + self._side_confidence_bonus(p, "Over")))
            result.append(over_prop)

            under_prop = dict(p)
            under_prop["over_under"] = "Under"
            under_prop["selected_odds"] = float(under_odds)
            under_prop["dynamic_odds"] = float(under_odds)
            under_prop["free_projection"] = free_projection
            under_prop["free_score"] = self._free_side_score(p, "Under")
            under_confidence = base_confidence + self._side_confidence_bonus(p, "Under") - self._under_context_penalty(p)
            under_prop["confidence"] = max(0.0, min(10.0, under_confidence))
            result.append(under_prop)
        return result

    def _prop_diversity_bonus(self, combo: List[Dict]) -> float:
        types = {p["type"] for p in combo}
        non_pts = sum(1 for t in types if t != "points")
        return non_pts * 0.5

    def _free_projection(self, prop: Dict) -> float:
        season_avg = float(prop.get("season_avg") or 0.0)
        last5_avg = float(prop.get("last5_avg") or 0.0)
        matchup_mult = float(prop.get("matchup_mult") or 1.0)

        base_avg = season_avg
        if season_avg > 0 and last5_avg > 0:
            base_avg = (season_avg * 0.55) + (last5_avg * 0.45)
        elif last5_avg > 0:
            base_avg = last5_avg

        return round(base_avg * matchup_mult, 2)

    def _free_side_score(self, prop: Dict, side: str) -> float:
        projection = self._free_projection(prop)
        line = float(prop.get("line") or 0.0)
        season_avg = float(prop.get("season_avg") or 0.0)
        last5_avg = float(prop.get("last5_avg") or 0.0)

        gap = projection - line
        trend_delta = 0.0
        if season_avg > 0 and last5_avg > 0:
            trend_delta = (last5_avg - season_avg) / season_avg

        if side == "Under":
            gap = -gap
            trend_delta = -trend_delta

        return round(gap + (trend_delta * 1.35), 3)

    def _is_free_play_eligible(self, prop: Dict) -> bool:
        avg_minutes = float(prop.get("avgMinutes_last5") or 0.0)
        if avg_minutes < 18.0:
            return False

        if prop.get("odds_source") != "api":
            return False

        if prop.get("market_line") is None:
            return False

        return True

    def _target_prop_count(self, candidates: List[Dict]) -> int:
        very_strong = sum(1 for prop in candidates if prop.get("free_score", 0.0) >= 0.75)
        strong = sum(1 for prop in candidates if prop.get("free_score", 0.0) >= 0.35)
        playable = sum(1 for prop in candidates if prop.get("free_score", 0.0) >= 0.10)

        if very_strong >= 14:
            return min(12, len(candidates))
        if very_strong >= 10:
            return min(10, len(candidates))
        if very_strong >= 7:
            return min(8, len(candidates))
        if strong >= 8:
            return min(7, len(candidates))
        if strong >= 5:
            return min(6, len(candidates))
        if playable >= 4:
            return min(5, len(candidates))
        return min(4, len(candidates))

    def _find_best_combination(
        self, props: List[Dict], min_odds: float, max_odds: float
    ) -> List[Dict]:
        if len(props) < 2:
            return []

        best_by_prop = {}
        for prop in props:
            score = float(prop.get("free_score", 0.0))
            key = (prop.get("player"), prop.get("type"))
            current = best_by_prop.get(key)
            if current is None or score > float(current.get("free_score", 0.0)) or (
                score == float(current.get("free_score", 0.0))
                and self._get_prop_confidence(prop) > self._get_prop_confidence(current)
            ):
                best_by_prop[key] = prop

        candidates = sorted(
            best_by_prop.values(),
            key=lambda prop: (
                float(prop.get("free_score", 0.0)),
                self._get_prop_confidence(prop),
                float(prop.get("matchup_mult", 1.0)),
            ),
            reverse=True,
        )

        if not candidates:
            return []

        target_count = self._target_prop_count(candidates)
        top_score = float(candidates[0].get("free_score", 0.0))
        score_floor = max(0.15, top_score * 0.45)
        if sum(1 for prop in candidates if float(prop.get("free_score", 0.0)) >= score_floor) < 4:
            score_floor = max(0.05, top_score * 0.25)
        selected = []
        player_counts = Counter()
        type_counts = Counter()

        for prop in candidates:
            if len(selected) >= target_count:
                break
            if float(prop.get("free_score", 0.0)) < score_floor:
                continue
            if player_counts[prop["player"]] >= 2:
                continue
            if type_counts[prop["type"]] >= 4:
                continue
            selected.append(prop)
            player_counts[prop["player"]] += 1
            type_counts[prop["type"]] += 1

        if len(selected) < min(target_count, len(candidates)):
            selected_keys = {(prop["player"], prop["type"]) for prop in selected}
            for prop in candidates:
                if len(selected) >= target_count:
                    break
                if float(prop.get("free_score", 0.0)) < score_floor:
                    continue
                key = (prop["player"], prop["type"])
                if key in selected_keys:
                    continue
                selected.append(prop)
                selected_keys.add(key)

        return selected

    def generate_tickets_for_games(
        self,
        all_props: List[Dict],
        games: List[Dict],
    ) -> List[Dict]:
        tickets = []
        for game in games:
            gid = game["id"]
            game_props = [
                p for p in all_props
                if p.get("game_id") == gid
                and float(p.get("line") or 0.0) > 0.0
                and (float(p.get("season_avg") or 0.0) > 0.0 or float(p.get("last5_avg") or 0.0) > 0.0)
            ]
            game_props = self._assign_dynamic_odds(game_props)
            game_props = [p for p in game_props if self._is_free_play_eligible(p)]

            if len(game_props) < 2:
                continue

            selected = self._find_best_combination(
                game_props, self.game_min_odds, self.game_max_odds
            )

            if selected:
                ticket = self._build_game_ticket(game, selected)
                tickets.append(ticket)

        return tickets

    def _build_game_ticket(self, game: Dict, props: List[Dict]) -> Dict:
        game_odds = self.calculate_total_odds(props)
        total_confidence = sum(
            self._get_prop_confidence(p) for p in props
        )
        avg_confidence = total_confidence / len(props) if props else 0

        return {
            "created_at": datetime.now().isoformat(),
            "game_id": game["id"],
            "home": game["home"],
            "away": game["away"],
            "datetime": game["datetime"],
            "total_odds": game_odds,
            "num_props": len(props),
            "avg_confidence": round(avg_confidence, 1),
            "props": [self._format_prop(p) for p in props],
        }

    def _format_prop(self, prop: Dict) -> Dict:
        line = prop["line"]
        line_int = int(line) if line == int(line) else line

        return {
            "player": prop["player"],
            "team": prop["team"],
            "type": prop["type"],
            "abbrev": prop["abbrev"],
            "over_under": prop.get("over_under", "Over"),
            "line": line_int,
            "odds": prop.get("dynamic_odds", prop.get("selected_odds", prop.get("odds_over", self.default_prop_odds))),
            "confidence": round(self._get_prop_confidence(prop), 1),
            "season_avg": prop.get("season_avg", 0),
            "last5_avg": prop.get("last5_avg", 0),
            "injury_status": prop.get("injury_status"),
            "fallback": prop.get("fallback", False),
            "matchup_mult": prop.get("matchup_mult", 1.0),
            "blowout_mult": prop.get("blowout_mult", 1.0),
            "is_starter": prop.get("is_starter", True),
            "odds_source": prop.get("odds_source", "unknown"),
            "bookmaker": prop.get("bookmaker", ""),
            "market_line": prop.get("market_line"),
            "market_target_line": prop.get("market_target_line"),
            "market_odds_over": prop.get("market_odds_over"),
            "market_odds_under": prop.get("market_odds_under"),
            "reference_odds_over": prop.get("reference_odds_over"),
            "reference_odds_under": prop.get("reference_odds_under"),
            "reference_source": prop.get("reference_source"),
            "reference_bookmaker": prop.get("reference_bookmaker", ""),
            "reference_bookmakers": prop.get("reference_bookmakers", []),
            "price_delta_over": prop.get("price_delta_over"),
            "price_delta_under": prop.get("price_delta_under"),
            "free_projection": prop.get("free_projection"),
            "free_score": prop.get("free_score"),
        }

    def print_all_tickets(self, tickets: List[Dict]) -> None:
        print("\n" + "=" * 70)
        print("              BILHETES NBA - APOSTA POR JOGO")
        print("=" * 70)

        print(f"\n[*] Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        print(f"[>] {len(tickets)} bilhetes gerados (alvo: 7.0x - 10.0x por jogo)")
        print("-" * 70)

        for i, ticket in enumerate(tickets, 1):
            dt = datetime.fromisoformat(ticket["datetime"])
            print(f"\n[{i}] {ticket['away']} @ {ticket['home']} ({dt.strftime('%d/%m %H:%M')})")
            print(f"    Odd Total: {ticket['total_odds']:.2f}x | Props: {ticket['num_props']} | Conf Avg: {ticket['avg_confidence']:.1f}")
            for prop in ticket["props"]:
                injury_tag = f" [!{prop['injury_status']}]" if prop.get("injury_status") else ""
                fallback_tag = " [F]" if prop.get("fallback") else ""
                bench_tag = " [BENCH]" if not prop.get("is_starter") else ""
                bm = prop.get("blowout_mult", 1.0)
                blowout_tag = f" [B{_blowout_arrow(bm)}]" if abs(bm - 1.0) > 0.02 else ""
                mm = prop.get("matchup_mult", 1.0)
                matchup_tag = f" [M+{mm:.2f}]" if mm > 1.05 else (f" [M-{mm:.2f}]" if mm < 0.95 else "")
                conf_bar = "*" * int(prop["confidence"]) + "-" * (10 - int(prop["confidence"]))
                print(
                    f"    • {prop['player']:22s} {prop.get('over_under', 'Over')[:1]} {prop['abbrev']:4s} +{prop['line']:5} "
                    f"@{prop['odds']:.2f} ({prop['season_avg']:.1f} | {prop['last5_avg']:.1f}) "
                    f"{conf_bar[:5]}{matchup_tag}{blowout_tag}{injury_tag}{fallback_tag}{bench_tag}"
                )

        if tickets:
            total_odds = 1.0
            for t in tickets:
                total_odds *= t["total_odds"]
            print(f"\n{'=' * 70}")
            print(f"ODD COMBINADA (TODOS OS BILHETES): {total_odds:.2f}x")
            print(f"{'=' * 70}")

    def save_all_tickets(self, tickets: List[Dict], filename: Optional[str] = None, push_to_github: bool = True) -> Path:
        if filename is None:
            date_str = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            filename = f"bilhetes_{date_str}.json"

        output_path = config.OUTPUT_DIR / filename
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        total_odds = 1.0
        for t in tickets:
            total_odds *= t["total_odds"]

        annotated_tickets = self._annotate_tickets_for_save(tickets)

        output = {
            "created_at": datetime.now().isoformat(),
            "total_combined_odds": round(total_odds, 2),
            "num_tickets": len(annotated_tickets),
            "tickets": annotated_tickets,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        if push_to_github:
            try:
                from utils.github_sync import push_bilhetes_to_github
                push_bilhetes_to_github(output_path)
            except Exception:
                pass

        return output_path

    def generate_best_ticket(self, all_props: List[Dict], games: List[Dict]) -> Dict:
        tickets = self.generate_tickets_for_games(all_props, games)
        if tickets:
            return tickets[0]
        return {}

    def generate_multi_game_ticket(
        self, all_props: List[Dict], games: List[Dict]
    ) -> List[Dict]:
        return self.generate_tickets_for_games(all_props, games)
