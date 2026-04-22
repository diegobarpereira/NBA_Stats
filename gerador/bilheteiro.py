import json
import math
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
        self.game_min_odds = 7.0
        self.game_max_odds = 10.0
        self.min_confidence = 8.0
        self.default_prop_odds = config.ODDS_CONFIG["default_prop_odds"]
        self.date = date or datetime.now().strftime("%Y-%m-%d")
        
        self._odds_cache = None

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

    def calculate_prop_odds(self, prop: Dict) -> float:
        confidence = self.props_engine.get_confidence_score(prop)
        
        if confidence >= 7:
            api_odds = get_odds_for_player(
                prop.get("player", ""),
                prop["type"],
                prop.get("line", 0),
                self.date
            )
            
            if api_odds and api_odds.get("source") == "api":
                prop["odds_source"] = "api"
                prop["bookmaker"] = api_odds.get("bookmaker", "")
                return api_odds.get("odds_over", self.default_prop_odds)
        
        prop["odds_source"] = "calculated"
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

    def _assign_dynamic_odds(self, props: List[Dict]) -> List[Dict]:
        result = []
        for p in props:
            p = dict(p)
            p["dynamic_odds"] = self.calculate_prop_odds(p)
            result.append(p)
        return result

    def _prop_diversity_bonus(self, combo: List[Dict]) -> float:
        types = {p["type"] for p in combo}
        non_pts = sum(1 for t in types if t != "points")
        return non_pts * 0.5

    def _find_best_combination(
        self, props: List[Dict], min_odds: float, max_odds: float
    ) -> List[Dict]:
        if len(props) < 2:
            return []

        scored = [
            p for p in props
            if self.props_engine.get_confidence_score(p) >= self.min_confidence
        ]
        
        if len(scored) < 2:
            return []

        scored.sort(key=lambda p: -self.props_engine.get_confidence_score(p))

        best_combo = []
        best_score = -1.0
        best_odds = 0.0

        n4 = min(len(scored), 25)
        for i in range(n4):
            for j in range(i + 1, n4):
                keys_ij = {(scored[i]["player"], scored[i]["type"]), (scored[j]["player"], scored[j]["type"])}
                if len(keys_ij) != 2:
                    continue
                for k in range(j + 1, n4):
                    p_k = scored[k]
                    if (p_k["player"], p_k["type"]) in keys_ij:
                        continue
                    keys_ijk = keys_ij | {(p_k["player"], p_k["type"])}
                    for l in range(k + 1, n4):
                        p_l = scored[l]
                        if (p_l["player"], p_l["type"]) in keys_ijk:
                            continue
                        combo = [scored[i], scored[j], scored[k], scored[l]]
                        odds = self.calculate_total_odds(combo)
                        if not (min_odds <= odds <= max_odds):
                            continue
                        base_score = sum(self.props_engine.get_confidence_score(p) for p in combo) / 4
                        score = base_score + self._prop_diversity_bonus(combo)
                        if score > best_score or (score == best_score and odds > best_odds):
                            best_score = score
                            best_odds = odds
                            best_combo = list(combo)

        if not best_combo:
            n3 = min(len(scored), 35)
            for i in range(n3):
                for j in range(i + 1, n3):
                    keys_ij = {(scored[i]["player"], scored[i]["type"]), (scored[j]["player"], scored[j]["type"])}
                    if len(keys_ij) != 2:
                        continue
                    for k in range(j + 1, n3):
                        p_k = scored[k]
                        if (p_k["player"], p_k["type"]) in keys_ij:
                            continue
                        combo = [scored[i], scored[j], scored[k]]
                        odds = self.calculate_total_odds(combo)
                        if not (min_odds <= odds <= max_odds):
                            continue
                        base_score = sum(self.props_engine.get_confidence_score(p) for p in combo) / 3
                        score = base_score + self._prop_diversity_bonus(combo)
                        if score > best_score or (score == best_score and odds > best_odds):
                            best_score = score
                            best_odds = odds
                            best_combo = list(combo)

        if not best_combo:
            n5 = min(len(scored), 20)
            for i in range(n5):
                for j in range(i + 1, n5):
                    keys_ij = {(scored[i]["player"], scored[i]["type"]), (scored[j]["player"], scored[j]["type"])}
                    if len(keys_ij) != 2:
                        continue
                    for k in range(j + 1, n5):
                        p_k = scored[k]
                        if (p_k["player"], p_k["type"]) in keys_ij:
                            continue
                        keys_ijk = keys_ij | {(p_k["player"], p_k["type"])}
                        for l in range(k + 1, n5):
                            p_l = scored[l]
                            if (p_l["player"], p_l["type"]) in keys_ijk:
                                continue
                            keys_ijkl = keys_ijk | {(p_l["player"], p_l["type"])}
                            for m in range(l + 1, n5):
                                p_m = scored[m]
                                if (p_m["player"], p_m["type"]) in keys_ijkl:
                                    continue
                                combo = [scored[i], scored[j], scored[k], scored[l], scored[m]]
                                odds = self.calculate_total_odds(combo)
                                if not (min_odds <= odds <= max_odds):
                                    continue
                                base_score = sum(self.props_engine.get_confidence_score(p) for p in combo) / 5
                                score = base_score + self._prop_diversity_bonus(combo)
                                if score > best_score or (score == best_score and odds > best_odds):
                                    best_score = score
                                    best_odds = odds
                                    best_combo = list(combo)

        if not best_combo:
            n6 = min(len(scored), 18)
            for i in range(n6):
                for j in range(i + 1, n6):
                    keys_ij = {(scored[i]["player"], scored[i]["type"]), (scored[j]["player"], scored[j]["type"])}
                    if len(keys_ij) != 2:
                        continue
                    for k in range(j + 1, n6):
                        p_k = scored[k]
                        if (p_k["player"], p_k["type"]) in keys_ij:
                            continue
                        keys_ijk = keys_ij | {(p_k["player"], p_k["type"])}
                        for l in range(k + 1, n6):
                            p_l = scored[l]
                            if (p_l["player"], p_l["type"]) in keys_ijk:
                                continue
                            keys_ijkl = keys_ijk | {(p_l["player"], p_l["type"])}
                            for m in range(l + 1, n6):
                                p_m = scored[m]
                                if (p_m["player"], p_m["type"]) in keys_ijkl:
                                    continue
                                keys_ijklm = keys_ijkl | {(p_m["player"], p_m["type"])}
                                for n in range(m + 1, n6):
                                    p_n = scored[n]
                                    if (p_n["player"], p_n["type"]) in keys_ijklm:
                                        continue
                                    combo = [scored[i], scored[j], scored[k], scored[l], scored[m], scored[n]]
                                    odds = self.calculate_total_odds(combo)
                                    if not (min_odds <= odds <= max_odds):
                                        continue
                                    base_score = sum(self.props_engine.get_confidence_score(p) for p in combo) / 6
                                    score = base_score + self._prop_diversity_bonus(combo)
                                    if score > best_score or (score == best_score and odds > best_odds):
                                        best_score = score
                                        best_odds = odds
                                        best_combo = list(combo)

        return best_combo if best_combo else scored[:3]

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
                and self.props_engine.get_confidence_score(p) >= self.min_confidence
            ]
            game_props = self._assign_dynamic_odds(game_props)

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
            self.props_engine.get_confidence_score(p) for p in props
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
            "line": line_int,
            "odds": prop.get("dynamic_odds", prop.get("odds_over", self.default_prop_odds)),
            "confidence": self.props_engine.get_confidence_score(prop),
            "season_avg": prop.get("season_avg", 0),
            "last5_avg": prop.get("last5_avg", 0),
            "injury_status": prop.get("injury_status"),
            "fallback": prop.get("fallback", False),
            "matchup_mult": prop.get("matchup_mult", 1.0),
            "blowout_mult": prop.get("blowout_mult", 1.0),
            "is_starter": prop.get("is_starter", True),
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
                    f"    • {prop['player']:22s} {prop['abbrev']:4s} +{prop['line']:5} "
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

        output = {
            "created_at": datetime.now().isoformat(),
            "total_combined_odds": round(total_odds, 2),
            "num_tickets": len(tickets),
            "tickets": tickets,
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
