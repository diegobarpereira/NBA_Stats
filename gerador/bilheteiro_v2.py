import json
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import config
from gerador.props_engine_v2 import PropsEngineV2
from scrapers.odds_scraper import ensure_odds_for_date, get_odds_for_player


class BilheteiroV2:
    def __init__(self, date: str = None):
        self.props_engine = PropsEngineV2()
        self.game_min_odds = config.ODDS_CONFIG["min_total_odds"]
        self.game_max_odds = config.ODDS_CONFIG["max_total_odds"]
        self.min_confidence = 7.0
        self.default_prop_odds = config.ODDS_CONFIG["default_prop_odds"]
        self.date = date or datetime.now().strftime("%Y-%m-%d")
        
        self._odds_cache = None
        self._odds_initialized = False

    def _get_market_gap(self, prop: Dict) -> Optional[float]:
        market_line = prop.get("market_line")
        model_line = prop.get("line")
        if market_line is None or model_line is None:
            return None
        return float(model_line) - float(market_line)

    def _refresh_prop_calibration(self, prop: Dict) -> None:
        market_gap = self._get_market_gap(prop)
        prop["market_gap"] = round(market_gap, 2) if market_gap is not None else None

        calibrated_prob = 0.5
        probability_components = {}
        analyzer = getattr(self.props_engine, "performance_analyzer", None)
        if analyzer is not None:
            calibrated_prob, probability_components = analyzer.estimate_hit_probability(prop)

        odds = prop.get("dynamic_odds", self.default_prop_odds) or self.default_prop_odds
        try:
            odds = float(odds)
        except (TypeError, ValueError):
            odds = self.default_prop_odds

        implied_prob = 1.0 / max(odds, 1.01)
        probability_edge = calibrated_prob - implied_prob
        expected_value = (calibrated_prob * odds) - 1.0

        prop["calibrated_hit_probability"] = round(calibrated_prob, 3)
        prop["probability_components"] = probability_components
        prop["implied_probability"] = round(implied_prob, 3)
        prop["probability_edge"] = round(probability_edge, 3)
        prop["expected_value_over"] = round(expected_value, 3)
        prop["fair_odds_over"] = round(1.0 / calibrated_prob, 2) if calibrated_prob > 0 else None

    def _is_prop_allowed_for_mode(self, prop: Dict, mode: str, min_confidence: float) -> bool:
        confidence = float(prop.get("confidence", 0))
        if confidence < min_confidence:
            return False

        calibrated_prob = float(prop.get("calibrated_hit_probability", 0.5))

        if mode == "aggressive":
            return True

        if prop.get("odds_source") not in {"api", "market_approx"} or prop.get("market_line") is None:
            return False

        market_gap = self._get_market_gap(prop)
        if market_gap is None:
            return False

        aggressiveness = float(prop.get("aggressiveness", 0))

        if mode == "conservative":
            return market_gap >= -0.25 and aggressiveness <= 0.22 and calibrated_prob >= 0.53

        if mode == "balanced":
            return market_gap >= -0.75 and aggressiveness <= 0.32 and calibrated_prob >= 0.50

        return True

    def _ensure_odds_cache(self) -> None:
        if self._odds_initialized:
            return
        try:
            ensure_odds_for_date(self.date)
        except Exception:
            pass
        self._odds_initialized = True

    def _calculate_odds_fallback(self, prop: Dict) -> float:
        line = prop.get("line", 0)
        confidence = prop.get("confidence", 5)
        
        if line <= 0:
            return self.default_prop_odds

        type_config = {
            "points":   {"max": 35.0, "floor": 1.10, "ceiling": 2.10},
            "rebounds": {"max": 14.0, "floor": 1.10, "ceiling": 2.05},
            "assists":  {"max": 14.0, "floor": 1.10, "ceiling": 2.05},
            "3pt":      {"max": 6.0,  "floor": 1.15, "ceiling": 2.20},
        }
        cfg = type_config.get(prop.get("type", "points"), {"max": 15.0, "floor": 1.10, "ceiling": 2.05})

        norm = min(line, cfg["max"]) / cfg["max"]
        base = cfg["floor"] + (cfg["ceiling"] - cfg["floor"]) * norm

        if confidence >= 8:
            base = min(cfg["ceiling"], base + 0.05)
        elif confidence <= 4:
            base = min(cfg["ceiling"], base + 0.08)

        return round(max(1.10, min(2.10, base)), 2)

    def calculate_prop_odds(self, prop: Dict) -> float:
        self._ensure_odds_cache()

        prop_type = prop.get("type", "points")
        line = prop.get("line", 0)

        api_odds = get_odds_for_player(
            prop.get("player", ""),
            prop_type,
            line,
            self.date
        )

        if api_odds and api_odds.get("source") in {"api", "market_approx"}:
            prop["odds_source"] = api_odds.get("source")
            prop["bookmaker"] = api_odds.get("bookmaker", "")
            prop["market_line"] = api_odds.get("reference_line", api_odds.get("line"))
            prop["market_target_line"] = api_odds.get("line")
            prop["market_reference_lines"] = api_odds.get("reference_lines", [prop["market_line"]] if prop.get("market_line") is not None else [])
            prop["market_odds_over"] = api_odds.get("odds_over", self.default_prop_odds)
            return float(api_odds.get("odds_over", self.default_prop_odds))
        
        prop["odds_source"] = "calculated"
        prop["market_line"] = None
        prop["market_target_line"] = None
        prop["market_reference_lines"] = []
        prop["market_odds_over"] = None
        return self._calculate_odds_fallback(prop)

    def calculate_total_odds(self, props: List[Dict]) -> float:
        if not props:
            return 0.0
        total = 1.0
        for prop in props:
            odds = prop.get("dynamic_odds", prop.get("odds_over"))
            if odds is None:
                odds = self.default_prop_odds
            try:
                odds = float(odds)
            except (TypeError, ValueError):
                odds = self.default_prop_odds
            total *= odds
        return round(total, 2)

    def assign_all_odds(self, props: List[Dict]) -> List[Dict]:
        result = []
        for p in props:
            p = dict(p)
            p["dynamic_odds"] = self.calculate_prop_odds(p)
            self._refresh_prop_calibration(p)
            result.append(p)
        return result

    def calculate_quality_score(self, combo: List[Dict]) -> float:
        if not combo:
            return 0.0
        
        avg_conf = sum(p.get("confidence", 5) for p in combo) / len(combo)
        avg_calibrated_prob = sum(p.get("calibrated_hit_probability", 0.5) for p in combo) / len(combo)
        avg_prob_edge = sum(p.get("probability_edge", 0.0) for p in combo) / len(combo)
        avg_expected_value = sum(p.get("expected_value_over", 0.0) for p in combo) / len(combo)
        
        avg_aggr = sum(p.get("aggressiveness", 0.3) for p in combo) / len(combo)

        market_alignment = []
        for prop in combo:
            market_line = prop.get("market_line")
            model_line = prop.get("line", 0)
            if market_line is None:
                market_alignment.append(0.0)
                continue

            # Positive when the market line is at or below the model line.
            gap = max(-2.5, min(2.5, model_line - float(market_line)))
            market_alignment.append(gap)

        avg_market_alignment = sum(market_alignment) / len(market_alignment) if market_alignment else 0.0
        
        types = [p.get("type") for p in combo]
        unique_types = len(set(types))
        type_bonus = min(unique_types * 0.5, 1.5)
        
        players = [p.get("player") for p in combo]
        unique_players = len(set(players))
        player_bonus = min(unique_players * 0.3, 0.9)

        # Prefer combinations that fit the odds target with more athletes,
        # as long as quality and market alignment remain acceptable.
        size_bonus = max(0, len(combo) - 2) * 0.45
        
        score = (
            avg_conf * 0.65 +
            avg_calibrated_prob * 6.5 +
            avg_prob_edge * 10.0 +
            avg_expected_value * 2.0 +
            (1 - avg_aggr) * 1.4 +
            type_bonus +
            player_bonus +
            (avg_market_alignment * 1.1) +
            size_bonus
        )
        
        return round(score, 2)

    def _is_valid_combo(self, combo: List[Dict]) -> bool:
        player_type_keys = {(p.get("player"), p.get("type")) for p in combo}
        if len(player_type_keys) != len(combo):
            return False

        players = [p.get("player") for p in combo]
        return len(set(players)) == len(players)

    def _build_combo_entry(self, game_id: str, combo: List[Dict], min_odds: float, max_odds: float) -> Dict:
        total_odds = self.calculate_total_odds(combo)
        within_target = min_odds <= total_odds <= max_odds

        distance = 0.0
        if total_odds < min_odds:
            distance = min_odds - total_odds
        elif total_odds > max_odds:
            distance = total_odds - max_odds

        quality_score = self.calculate_quality_score(combo)

        return {
            "game_id": game_id,
            "props": combo,
            "num_props": len(combo),
            "odds": total_odds,
            "quality_score": quality_score,
            "avg_calibrated_probability": round(sum(p.get("calibrated_hit_probability", 0.5) for p in combo) / len(combo), 3),
            "avg_probability_edge": round(sum(p.get("probability_edge", 0.0) for p in combo) / len(combo), 3),
            "within_target_odds": within_target,
            "selection_score": round(quality_score - (distance * 1.5) + (len(combo) * 0.2), 2),
        }

    def _get_best_effort_candidate(
        self,
        game_id: str,
        qualified: List[Dict],
        min_odds: float,
        max_odds: float,
    ) -> Optional[Dict]:
        size_limits = {6: 8, 5: 10, 4: 12, 3: 15, 2: 18}
        best_candidate = None

        for combo_size in (6, 5, 4, 3, 2):
            limited_props = qualified[:size_limits[combo_size]]
            if len(limited_props) < combo_size:
                continue

            for combo_tuple in combinations(limited_props, combo_size):
                combo = list(combo_tuple)
                if not self._is_valid_combo(combo):
                    continue

                candidate = self._build_combo_entry(game_id, combo, min_odds, max_odds)
                if (
                    best_candidate is None
                    or candidate["selection_score"] > best_candidate["selection_score"]
                    or (
                        candidate["selection_score"] == best_candidate["selection_score"]
                        and candidate["quality_score"] > best_candidate["quality_score"]
                    )
                ):
                    best_candidate = candidate

        return best_candidate

    def generate_combo_candidates(
        self,
        props_by_game: Dict[str, List[Dict]],
        min_odds: float = 7.0,
        max_odds: float = 10.0,
        min_confidence: float = 7.0,
        mode: str = "balanced",
    ) -> List[Dict]:
        candidates = []
        size_limits = {2: 18, 3: 15, 4: 12, 5: 10, 6: 8}
        
        for game_id, game_props in props_by_game.items():
            game_props_with_odds = self.assign_all_odds(game_props)
            
            qualified = [
                p for p in game_props_with_odds
                if self._is_prop_allowed_for_mode(p, mode, min_confidence)
            ]
            
            qualified.sort(
                key=lambda p: (
                    p.get("calibrated_hit_probability", 0.5),
                    p.get("probability_edge", 0.0),
                    p.get("confidence", 5),
                ),
                reverse=True,
            )

            game_candidates = []

            for combo_size in (6, 5, 4, 3, 2):
                limited_props = qualified[:size_limits[combo_size]]
                if len(limited_props) < combo_size:
                    continue

                for combo_tuple in combinations(limited_props, combo_size):
                    combo = list(combo_tuple)
                    if not self._is_valid_combo(combo):
                        continue

                    candidate = self._build_combo_entry(game_id, combo, min_odds, max_odds)
                    if candidate["within_target_odds"]:
                        game_candidates.append(candidate)

            if not game_candidates:
                fallback_candidate = self._get_best_effort_candidate(game_id, qualified, min_odds, max_odds)
                if fallback_candidate and mode == "aggressive":
                    game_candidates.append(fallback_candidate)

            candidates.extend(game_candidates)
        
        candidates.sort(
            key=lambda c: (c["within_target_odds"], c["quality_score"], c["selection_score"]),
            reverse=True,
        )
        return candidates

    def generate_multi_ticket_options(
        self,
        all_props: List[Dict],
        games: List[Dict],
        mode: str = "balanced",
    ) -> Dict[str, List[Dict]]:
        props_by_game = {}
        
        for game in games:
            game_id = game.get("id", "")
            props_by_game[game_id] = [
                p for p in all_props
                if p.get("game_id") == game_id
            ]
        
        min_confidence = {"conservative": 8.0, "balanced": 7.0, "aggressive": 6.0}.get(mode, 7.0)
        min_odds = self.game_min_odds
        max_odds = self.game_max_odds
        
        candidates = self.generate_combo_candidates(
            props_by_game, min_odds, max_odds, min_confidence, mode
        )
        
        by_game = {}
        for c in candidates:
            gid = c["game_id"]
            if gid not in by_game:
                by_game[gid] = []
            by_game[gid].append(c)
        
        for gid in by_game:
            by_game[gid].sort(
                key=lambda c: (c["within_target_odds"], c.get("num_props", len(c.get("props", []))), c["quality_score"], c["selection_score"]),
                reverse=True,
            )
            by_game[gid] = by_game[gid][:5]
        
        return by_game

    def generate_tickets_for_games(
        self,
        all_props: List[Dict],
        games: List[Dict],
    ) -> List[Dict]:
        multi_options = self.generate_multi_ticket_options(all_props, games, "balanced")
        
        tickets = []
        
        for game in games:
            game_id = game.get("id", "")
            if game_id not in multi_options:
                continue
            
            options = multi_options[game_id]
            
            for opt in options[:3]:
                ticket = {
                    "id": f"{game_id}_{len(tickets)}",
                    "game_id": game_id,
                    "game_home": game.get("home", ""),
                    "game_away": game.get("away", ""),
                    "props": opt["props"],
                    "total_odds": opt["odds"],
                    "quality_score": opt["quality_score"],
                    "mode": "balanced",
                }
                tickets.append(ticket)
        
        return tickets

    def generate_conservative_ticket(self, all_props: List[Dict], games: List[Dict]) -> List[Dict]:
        return self._generate_ticket_by_mode(all_props, games, "conservative")

    def generate_balanced_ticket(self, all_props: List[Dict], games: List[Dict]) -> List[Dict]:
        return self._generate_ticket_by_mode(all_props, games, "balanced")

    def generate_aggressive_ticket(self, all_props: List[Dict], games: List[Dict]) -> List[Dict]:
        return self._generate_ticket_by_mode(all_props, games, "aggressive")

    def _generate_ticket_by_mode(
        self,
        all_props: List[Dict],
        games: List[Dict],
        mode: str,
    ) -> List[Dict]:
        multi_options = self.generate_multi_ticket_options(all_props, games, mode)
        
        tickets = []
        
        for game in games:
            game_id = game.get("id", "")
            if game_id not in multi_options:
                continue
            
            options = multi_options[game_id]
            
            if options:
                opt = options[0]
                ticket = {
                    "id": f"{game_id}_{mode}",
                    "game_id": game_id,
                    "home": game.get("home", ""),
                    "away": game.get("away", ""),
                    "props": opt["props"],
                    "num_props": opt.get("num_props", len(opt.get("props", []))),
                    "odds": opt["odds"],
                    "quality": opt["quality_score"],
                    "mode": mode,
                }
                tickets.append(ticket)
        
        return tickets

    def save_all_tickets(
        self,
        tickets: List[Dict],
        filename: Optional[str] = None,
        mode: Optional[str] = None,
        options_by_game: Optional[Dict[str, List[Dict]]] = None,
    ) -> Path:
        if filename is None:
            date_str = self.date or datetime.now().strftime("%Y-%m-%d")
            time_str = datetime.now().strftime("%H%M%S")
            suffix = f"_{mode}" if mode else ""
            filename = f"bilhetes_{date_str}{suffix}_v2_{time_str}.json"

        output_path = config.OUTPUT_DIR / filename
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        output = {
            "created_at": datetime.now().isoformat(),
            "version": "v2",
            "mode": mode,
            "num_tickets": len(tickets),
            "tickets": tickets,
        }

        if tickets:
            total_odds = 1.0
            for ticket in tickets:
                total_odds *= ticket.get("odds", 1.0)
            output["total_combined_odds"] = round(total_odds, 2)

        if options_by_game is not None:
            output["options_by_game"] = options_by_game

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        return output_path