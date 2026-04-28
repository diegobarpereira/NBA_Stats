import copy
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

    def _build_odds_snapshot(self, prop: Dict) -> Dict:
        return {
            "captured_at": datetime.now().isoformat(),
            "side": prop.get("over_under", "Over"),
            "selected_odds": prop.get("dynamic_odds", prop.get("selected_odds", prop.get("odds_over", self.default_prop_odds))),
            "odds_source": prop.get("odds_source", "unknown"),
            "bookmaker": prop.get("bookmaker", ""),
            "market_line": prop.get("market_line"),
            "market_target_line": prop.get("market_target_line"),
            "market_reference_lines": prop.get("market_reference_lines", []),
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
                prop.setdefault("picked_odds", prop.get("dynamic_odds", prop.get("selected_odds", prop.get("odds_over", self.default_prop_odds))))
        return annotated

    def _pair_correlation_penalty(self, left: Dict, right: Dict) -> float:
        penalty = 0.0

        same_team = left.get("team") == right.get("team")
        same_game = left.get("game_id") == right.get("game_id")
        same_side = left.get("over_under", "Over") == right.get("over_under", "Over")
        left_type = left.get("type")
        right_type = right.get("type")
        type_pair = frozenset({left_type, right_type})

        if not same_game:
            return 0.0

        if same_team and same_side:
            penalty += 0.25

        if same_team and same_side and type_pair == frozenset({"points", "3pt"}):
            penalty += 0.45
        elif same_team and same_side and type_pair == frozenset({"points", "assists"}):
            penalty += 0.35
        elif same_team and same_side and type_pair == frozenset({"rebounds", "assists"}):
            penalty += 0.15
        elif same_team and left_type == right_type:
            penalty += 0.20

        if same_side and left_type == right_type:
            penalty += 0.10

        if left.get("over_under") != right.get("over_under") and same_team:
            penalty -= 0.08

        return max(0.0, round(penalty, 3))

    def _combo_correlation_penalty(self, combo: List[Dict]) -> float:
        if len(combo) < 2:
            return 0.0

        total_penalty = 0.0
        for idx, left in enumerate(combo):
            for right in combo[idx + 1:]:
                total_penalty += self._pair_correlation_penalty(left, right)

        return round(total_penalty, 3)

    def _selected_price_delta(self, prop: Dict) -> float:
        if prop.get("over_under", "Over") == "Under":
            return float(prop.get("price_delta_under") or 0.0)
        return float(prop.get("price_delta_over") or 0.0)

    def _get_market_gap(self, prop: Dict, side: str = "Over") -> Optional[float]:
        market_line = prop.get("market_line")
        model_line = prop.get("line")
        if market_line is None or model_line is None:
            return None
        raw_gap = float(model_line) - float(market_line)
        return raw_gap if side == "Over" else -raw_gap

    def _under_momentum_penalty(self, prop: Dict) -> float:
        season_avg = float(prop.get("season_avg") or 0.0)
        last5_avg = float(prop.get("last5_avg") or 0.0)
        minute_trend = float(prop.get("minute_trend") or 0.0)
        avg_minutes = float(prop.get("avgMinutes_last5") or prop.get("avg_minutes") or 0.0)
        minute_profile = str(prop.get("minute_profile") or "")

        penalty = 0.0

        if season_avg > 0 and last5_avg > season_avg:
            trend_ratio = (last5_avg - season_avg) / season_avg
            if trend_ratio >= 0.30:
                penalty += 0.08
            elif trend_ratio >= 0.15:
                penalty += 0.04

        if minute_trend >= 3.0:
            penalty += 0.06
        elif minute_trend >= 1.5:
            penalty += 0.03

        if avg_minutes >= 36:
            penalty += 0.03
        elif avg_minutes >= 32:
            penalty += 0.015

        if minute_profile in {"minutes_up", "bench_opportunity"}:
            penalty += 0.03

        return round(min(0.18, penalty), 3)

    def _refresh_prop_calibration(self, prop: Dict, side: str, odds: float) -> Dict:
        calibrated_prop = dict(prop)
        market_gap = self._get_market_gap(calibrated_prop, side)
        calibrated_prop["market_gap"] = round(market_gap, 2) if market_gap is not None else None
        calibrated_prop["over_under"] = side

        calibrated_prob = 0.5
        probability_components = {}
        analyzer = getattr(self.props_engine, "performance_analyzer", None)
        if analyzer is not None:
            calibrated_prob, probability_components = analyzer.estimate_hit_probability(calibrated_prop)

        under_momentum_penalty = self._under_momentum_penalty(calibrated_prop) if side == "Under" else 0.0
        calibrated_prop["under_momentum_penalty"] = under_momentum_penalty
        calibrated_prop["base_aggressiveness"] = float(calibrated_prop.get("aggressiveness", 0.0))
        if under_momentum_penalty > 0:
            calibrated_prob = max(0.15, calibrated_prob - under_momentum_penalty)
            probability_components = dict(probability_components)
            probability_components["under_momentum_penalty"] = round(-under_momentum_penalty, 3)
            calibrated_prop["aggressiveness"] = round(
                min(1.0, calibrated_prop["base_aggressiveness"] + under_momentum_penalty),
                3,
            )

        try:
            odds = float(odds)
        except (TypeError, ValueError):
            odds = self.default_prop_odds

        implied_prob = 1.0 / max(odds, 1.01)
        probability_edge = calibrated_prob - implied_prob
        expected_value = (calibrated_prob * odds) - 1.0

        calibrated_prop["calibrated_hit_probability"] = round(calibrated_prob, 3)
        calibrated_prop["probability_components"] = probability_components
        calibrated_prop["implied_probability"] = round(implied_prob, 3)
        calibrated_prop["probability_edge"] = round(probability_edge, 3)
        calibrated_prop["expected_value"] = round(expected_value, 3)
        calibrated_prop["fair_odds"] = round(1.0 / calibrated_prob, 2) if calibrated_prob > 0 else None
        calibrated_prop["expected_value_over"] = calibrated_prop["expected_value"]
        calibrated_prop["fair_odds_over"] = calibrated_prop["fair_odds"]
        calibrated_prop["selected_odds"] = odds

        return calibrated_prop

    def _is_prop_allowed_for_mode(self, prop: Dict, mode: str, min_confidence: float) -> bool:
        confidence = float(prop.get("confidence", 0))
        if confidence < min_confidence:
            return False

        calibrated_prob = float(prop.get("calibrated_hit_probability", 0.5))
        probability_edge = float(prop.get("probability_edge", 0.0))
        expected_value = float(prop.get("expected_value", prop.get("expected_value_over", 0.0)))

        if mode == "aggressive":
            return probability_edge >= -0.03 and expected_value >= -0.08

        if prop.get("odds_source") not in {"api", "market_approx"} or prop.get("market_line") is None:
            return False

        market_gap = self._get_market_gap(prop)
        if market_gap is None:
            return False

        aggressiveness = float(prop.get("aggressiveness", 0))
        under_momentum_penalty = float(prop.get("under_momentum_penalty", 0.0))

        if mode == "conservative":
            return (
                market_gap >= -0.25
                and aggressiveness <= 0.22
                and under_momentum_penalty <= 0.06
                and calibrated_prob >= 0.53
                and probability_edge >= 0.02
                and expected_value >= 0.0
            )

        if mode == "balanced":
            return (
                market_gap >= -0.75
                and aggressiveness <= 0.32
                and under_momentum_penalty <= 0.10
                and calibrated_prob >= 0.50
                and probability_edge >= 0.0
                and expected_value >= -0.02
            )

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

    def calculate_prop_odds(self, prop: Dict) -> Dict:
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
            market_line = api_odds.get("reference_line", api_odds.get("line"))
            return {
                "odds_source": api_odds.get("source"),
                "bookmaker": api_odds.get("bookmaker", ""),
                "market_line": market_line,
                "market_target_line": api_odds.get("line"),
                "market_reference_lines": api_odds.get("reference_lines", [market_line] if market_line is not None else []),
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
            "market_reference_lines": [],
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

    def assign_all_odds(self, props: List[Dict]) -> List[Dict]:
        result = []
        for p in props:
            p = dict(p)
            odds_payload = self.calculate_prop_odds(p)
            p.update(odds_payload)

            over_odds = odds_payload.get("market_odds_over") or odds_payload.get("fallback_odds_over") or p.get("odds_over", self.default_prop_odds)
            under_odds = odds_payload.get("market_odds_under") or odds_payload.get("fallback_odds_under") or p.get("odds_under", self.default_prop_odds)

            over_prop = self._refresh_prop_calibration(p, "Over", over_odds)
            over_prop["dynamic_odds"] = float(over_odds)
            over_prop["market_odds"] = odds_payload.get("market_odds_over")
            result.append(over_prop)

            under_prop = self._refresh_prop_calibration(p, "Under", under_odds)
            under_prop["dynamic_odds"] = float(under_odds)
            under_prop["market_odds"] = odds_payload.get("market_odds_under")
            result.append(under_prop)
        return result

    def calculate_quality_score(self, combo: List[Dict]) -> float:
        if not combo:
            return 0.0
        
        avg_conf = sum(p.get("confidence", 5) for p in combo) / len(combo)
        avg_calibrated_prob = sum(p.get("calibrated_hit_probability", 0.5) for p in combo) / len(combo)
        avg_prob_edge = sum(p.get("probability_edge", 0.0) for p in combo) / len(combo)
        avg_expected_value = sum(p.get("expected_value", p.get("expected_value_over", 0.0)) for p in combo) / len(combo)
        
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

        team_count = len({p.get("team") for p in combo if p.get("team")})
        team_bonus = min(team_count * 0.2, 0.6)

        correlation_penalty = self._combo_correlation_penalty(combo)
        avg_price_delta = sum(self._selected_price_delta(p) for p in combo) / len(combo)
        market_price_bonus = max(-0.2, min(0.2, avg_price_delta * 2.0))

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
            team_bonus +
            market_price_bonus +
            (avg_market_alignment * 1.1) +
            size_bonus -
            (correlation_penalty * 1.8)
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
        correlation_penalty = self._combo_correlation_penalty(combo)

        return {
            "game_id": game_id,
            "props": combo,
            "num_props": len(combo),
            "odds": total_odds,
            "quality_score": quality_score,
            "correlation_penalty": correlation_penalty,
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

        annotated_tickets = self._annotate_tickets_for_save(tickets)

        output = {
            "created_at": datetime.now().isoformat(),
            "version": "v2",
            "mode": mode,
            "num_tickets": len(annotated_tickets),
            "tickets": annotated_tickets,
        }

        if annotated_tickets:
            total_odds = 1.0
            for ticket in annotated_tickets:
                total_odds *= ticket.get("odds", 1.0)
            output["total_combined_odds"] = round(total_odds, 2)

        if options_by_game is not None:
            output["options_by_game"] = options_by_game

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        return output_path