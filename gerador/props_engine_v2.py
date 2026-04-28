from typing import Dict, List, Optional, Tuple
import copy
import config
from scrapers.matchup_scraper import get_matchup_boost
from scrapers.advanced_filters import apply_advanced_filters, get_schedule_info


class PropsEngineV2:
    def __init__(self, use_performance: bool = True):
        self.prop_types = config.PROP_TYPES
        self.prop_abbrev = config.PROP_ABBREV
        self.weights = config.WEIGHT_CONFIG
        self.odds_config = config.ODDS_CONFIG
        self.injury_adjustments = config.INJURY_ADJUSTMENTS
        self.performance_analyzer = None
        self.use_performance = use_performance
        if use_performance:
            try:
                from gerador.performance_analyzer import get_performance_analyzer
                self.performance_analyzer = get_performance_analyzer()
            except Exception:
                pass

    def _get_prop_stat_keys(self, prop_type: str) -> Tuple[str, str]:
        special_keys = {
            "3pt": ("avg3PT_season", "avg3PT_last5"),
        }
        return special_keys.get(
            prop_type,
            (f"avg{prop_type.capitalize()}_season", f"avg{prop_type.capitalize()}_last5"),
        )

    def _build_minute_profile(self, player_stats: Dict, prop_type: str, is_starter: bool) -> Dict:
        avg_minutes = float(player_stats.get("avgMinutes_last5", 0) or 0.0)
        early_minutes_avg = float(player_stats.get("early_minutes_avg", avg_minutes) or avg_minutes)
        recent_minutes_avg = float(player_stats.get("recent_minutes_avg", avg_minutes) or avg_minutes)
        minute_trend = float(player_stats.get("minute_trend", recent_minutes_avg - early_minutes_avg) or 0.0)
        minute_volatility = float(player_stats.get("minute_volatility", 0.0) or 0.0)

        last5_key = f"avg{prop_type.capitalize()}_last5"
        last5_avg = float(player_stats.get(last5_key, 0) or 0.0)
        production_per_minute = round(last5_avg / avg_minutes, 3) if avg_minutes > 0 else 0.0

        benchmark_by_type = {
            "points": 0.55,
            "rebounds": 0.18,
            "assists": 0.14,
            "3pt": 0.05,
        }
        benchmark = benchmark_by_type.get(prop_type, 0.0)

        confidence_delta = 0.0
        line_multiplier = 1.0
        opportunity_label = "stable"

        if avg_minutes >= 28:
            confidence_delta += 1.0
        elif avg_minutes >= 24:
            confidence_delta += 0.5
        elif avg_minutes < 14 and not is_starter:
            confidence_delta -= 1.5
            opportunity_label = "low_minutes"
        elif avg_minutes < 18 and not is_starter:
            confidence_delta -= 0.5
            opportunity_label = "thin_rotation"

        if minute_trend >= 3:
            confidence_delta += 1.0
            line_multiplier += 0.03
            opportunity_label = "minutes_up"
        elif minute_trend >= 1.5:
            confidence_delta += 0.5
            line_multiplier += 0.015
            opportunity_label = "minutes_up"
        elif minute_trend <= -3:
            confidence_delta -= 1.0
            line_multiplier -= 0.03
            opportunity_label = "minutes_down"
        elif minute_trend <= -1.5:
            confidence_delta -= 0.5
            line_multiplier -= 0.015
            opportunity_label = "minutes_down"

        if minute_volatility >= 0.32:
            confidence_delta -= 0.75
            line_multiplier -= 0.02
            opportunity_label = "volatile_minutes"
        elif minute_volatility >= 0.22:
            confidence_delta -= 0.35

        if (
            not is_starter
            and avg_minutes >= 18
            and recent_minutes_avg >= avg_minutes
            and minute_trend >= 1.5
            and production_per_minute >= benchmark
        ):
            confidence_delta += 1.5
            line_multiplier += 0.035
            opportunity_label = "bench_opportunity"

        line_multiplier = max(0.9, min(line_multiplier, 1.08))

        return {
            "avg_minutes": round(avg_minutes, 1),
            "early_minutes_avg": round(early_minutes_avg, 1),
            "recent_minutes_avg": round(recent_minutes_avg, 1),
            "minute_trend": round(minute_trend, 1),
            "minute_volatility": round(minute_volatility, 3),
            "production_per_minute": production_per_minute,
            "confidence_delta": confidence_delta,
            "line_multiplier": round(line_multiplier, 3),
            "opportunity_label": opportunity_label,
        }

    def calculate_adjusted_line(
        self,
        player_stats: Dict,
        prop_type: str,
        injury_status: Optional[str] = None,
        player_name: Optional[str] = None,
    ) -> float:
        season_key, last5_key = self._get_prop_stat_keys(prop_type)

        season_avg = player_stats.get(season_key, 0)
        last5_avg = player_stats.get(last5_key, 0)

        if last5_avg > 0:
            line = (
                season_avg * self.weights["season_weight"]
                + last5_avg * self.weights["last5_weight"]
            )
        else:
            line = season_avg

        if injury_status and injury_status in self.injury_adjustments:
            adjustment = self.injury_adjustments[injury_status]
            line *= adjustment

        if self.performance_analyzer and player_name:
            player_acc = self.performance_analyzer.get_player_confidence(player_name)
            type_mult = self.performance_analyzer.get_type_multipliers().get(prop_type, 1.0)

            if player_acc < 0.35:
                line *= 1.1
            elif player_acc > 0.7:
                line *= 0.95

            line *= type_mult

        return round(line, 1)

    def calculate_aggressiveness(
        self,
        line: float,
        season_avg: float,
        last5_avg: float,
    ) -> float:
        if season_avg == 0:
            return 0.5
        
        base = last5_avg if last5_avg > 0 else season_avg
        diff = abs(line - base) / base
        return min(1.0, max(0.0, diff))

    def get_confidence_score(self, prop: Dict) -> float:
        score = 0.0

        season_games = prop.get("season_games", 0)
        last5_games = prop.get("last5_games", 0)
        line = prop.get("line", 0)
        
        if season_games >= 50:
            score += 3
        elif season_games >= 30:
            score += 2
        elif season_games >= 10:
            score += 1

        if last5_games >= 3:
            score += 2
        elif last5_games >= 1:
            score += 1

        season_avg = prop.get("season_avg", 0)
        last5_avg = prop.get("last5_avg", 0)

        if last5_avg > 0 and season_avg > 0:
            trend = last5_avg / season_avg
            if 0.85 <= trend <= 1.15:
                score += 2
            elif 0.7 <= trend <= 1.3:
                score += 1

        if line >= 5:
            score += 1

        if prop.get("type") == "3pt" and line >= 1.5:
            score += 1

        if prop.get("fallback"):
            score = max(score, 5)
        else:
            score += 2

        if prop.get("injury_status"):
            score -= 1

        is_starter = prop.get("is_starter", False)
        if is_starter:
            score += 1

        minutes = prop.get("avgMinutes_last5", 0)
        if minutes >= 30:
            score += 2
        elif minutes >= 25:
            score += 1
        elif minutes < 15 and not is_starter:
            score -= 2
        elif minutes < 20 and not is_starter:
            score -= 1

        matchup_mult = prop.get("matchup_mult", 1.0)
        if matchup_mult > 1.05:
            score += 1
        elif matchup_mult < 0.95:
            score -= 1

        adv = prop.get("advanced_filters", {})
        if adv:
            trend = adv.get("trend", "stable")
            trend_strength = adv.get("trend_strength", 0)

            if trend == "up" and trend_strength > 0.1:
                score += min(2, trend_strength * 3)
            elif trend == "down" and trend_strength < -0.1:
                score -= min(3, abs(trend_strength) * 4)

            consistency = adv.get("consistency", 100)
            if consistency < 30:
                score -= 2
            elif consistency < 50:
                score -= 1
            elif consistency > 80:
                score += 1

            vol_penalty = adv.get("volatility_penalty", 0)
            if vol_penalty > 0:
                score -= vol_penalty * 5

            pace_factor = adv.get("pace_factor", 1.0)
            if pace_factor > 1.03:
                score += 1
            elif pace_factor < 0.97:
                score -= 1

            home_factor = adv.get("home_away_factor", 1.0)
            if home_factor > 1.0:
                score += 0.5

        if self.performance_analyzer:
            player_name = prop.get("player", "")
            prop_type = prop.get("type", "")
            adv = prop.get("advanced_filters", {})

            player_acc = self.performance_analyzer.get_player_confidence(player_name)
            type_mult = self.performance_analyzer.get_type_multipliers().get(prop_type, 1.0)
            conf_bucket = int(max(1, min(10, round(score))))
            conf_mult = self.performance_analyzer.get_confidence_multipliers().get(conf_bucket, 1.0)

            trend = adv.get("trend", "stable")
            trend_mult = self.performance_analyzer.get_trend_multipliers().get(trend, 1.0)

            consistency = adv.get("consistency", 50)
            if consistency >= 70:
                consistency_bucket = "high"
            elif consistency >= 40:
                consistency_bucket = "medium"
            else:
                consistency_bucket = "low"
            consistency_mult = self.performance_analyzer.get_consistency_multipliers().get(consistency_bucket, 1.0)

            matchup_mult = prop.get("matchup_mult", 1.0)
            if matchup_mult > 1.05:
                matchup_bucket = "good"
            elif matchup_mult < 0.95:
                matchup_bucket = "bad"
            else:
                matchup_bucket = "neutral"
            matchup_hist_mult = self.performance_analyzer.get_matchup_multipliers().get(matchup_bucket, 1.0)

            if player_acc < 0.3:
                score -= 2
            elif player_acc < 0.4:
                score -= 1
            elif player_acc > 0.7:
                score += 1

            history_mult = type_mult * conf_mult * trend_mult * consistency_mult * matchup_hist_mult
            history_mult = max(0.75, min(history_mult, 1.2))

            score *= history_mult
            prop["history_multiplier"] = round(history_mult, 3)
            prop["history_components"] = {
                "type_mult": round(type_mult, 3),
                "conf_mult": round(conf_mult, 3),
                "trend_mult": round(trend_mult, 3),
                "consistency_mult": round(consistency_mult, 3),
                "matchup_hist_mult": round(matchup_hist_mult, 3),
            }

        minute_confidence_delta = prop.get("minute_confidence_delta", 0.0)
        if minute_confidence_delta:
            score += minute_confidence_delta

        minute_profile = prop.get("minute_profile", "stable")
        if minute_profile == "bench_opportunity":
            score += 0.5
        elif minute_profile in {"minutes_down", "volatile_minutes", "low_minutes"}:
            score -= 0.5

        return max(0, min(score, 10))

    def generate_props_for_player(
        self,
        player_name: str,
        player_stats: Dict,
        injury_status: Optional[str] = None,
        opponent: Optional[str] = None,
        matchup_data: Optional[Dict] = None,
        blowout_risk: Optional[Dict] = None,
        is_starter: bool = True,
        is_home: bool = True,
    ) -> List[Dict]:
        props = []
        team = player_stats.get("team", "")
        position = player_stats.get("position", "-")

        if position in ["-", ""]:
            return []

        season_games = player_stats.get("games_season", 0)
        last5_games = player_stats.get("games_last5", 0)

        if season_games < 10 and last5_games < 3:
            return []

        schedule_info = {}
        opponent_abbr = ""
        if opponent:
            abbr_map = {v: k for k, v in config.TEAM_NAME_MAPPING.items()}
            opponent_abbr = abbr_map.get(opponent, opponent[:3].upper())

        last5_points = []
        last5_rebounds = []
        last5_assists = []
        for i in range(1, 6):
            pts_key = f"last5_game_{i}_pts"
            reb_key = f"last5_game_{i}_reb"
            ast_key = f"last5_game_{i}_ast"
            if pts_key in player_stats:
                last5_points.append(player_stats[pts_key])
            if reb_key in player_stats:
                last5_rebounds.append(player_stats[reb_key])
            if ast_key in player_stats:
                last5_assists.append(player_stats[ast_key])

        advanced_stats = {
            "last5_points": last5_points,
            "last5_rebounds": last5_rebounds,
            "last5_assists": last5_assists,
            "home_ppg": player_stats.get("home_ppg", 0),
            "away_ppg": player_stats.get("away_ppg", 0),
            "home_reb": player_stats.get("home_reb", 0),
            "away_reb": player_stats.get("away_reb", 0),
            "home_ast": player_stats.get("home_ast", 0),
            "away_ast": player_stats.get("away_ast", 0),
            "avgPoints_season": player_stats.get("avgPoints_season", 0),
            "avgRebounds_season": player_stats.get("avgRebounds_season", 0),
            "avgAssists_season": player_stats.get("avgAssists_season", 0),
        }

        schedule_info = {}

        for prop_type in self.prop_types:
            season_key, last5_key = self._get_prop_stat_keys(prop_type)

            season_avg = player_stats.get(season_key, 0)
            last5_avg = player_stats.get(last5_key, 0)

            if season_avg < 3.0:
                continue

            if prop_type == "3pt" and player_stats.get("avg3PT_season", 0) < 0.3:
                continue

            base_line = self.calculate_adjusted_line(
                player_stats, prop_type, injury_status, player_name
            )

            line = round(base_line * 0.9, 1)

            minute_profile = self._build_minute_profile(player_stats, prop_type, is_starter)
            line = round(line * minute_profile["line_multiplier"], 1)

            player_position = player_stats.get("position", "G")
            boost = get_matchup_boost(team, player_position, prop_type, matchup_data)
            if boost != 1.0:
                line = round(line * boost, 1)

            blowout_mult = 1.0
            if blowout_risk and blowout_risk.get("risk_level") == "high":
                blowout_mult = 0.95
                line = round(line * blowout_mult, 1)

            season_avg_val = season_avg
            last5_avg_val = last5_avg

            aggressiveness = self.calculate_aggressiveness(
                line, season_avg_val, last5_avg_val
            )

            confidence = self._calculate_confidence(
                season_games, last5_games, season_avg_val, last5_avg_val,
                is_starter, player_stats.get("avgMinutes_last5", 0)
            )

            prop = {
                "player": player_name,
                "team": team,
                "position": position,
                "type": prop_type,
                "abbrev": self.prop_abbrev[prop_type],
                "line": line,
                "season_avg": season_avg_val,
                "last5_avg": last5_avg_val,
                "season_games": season_games,
                "last5_games": last5_games,
                "is_starter": is_starter,
                "is_home": is_home,
                "avgMinutes_last5": player_stats.get("avgMinutes_last5", 0),
                "early_minutes_avg": minute_profile["early_minutes_avg"],
                "recent_minutes_avg": minute_profile["recent_minutes_avg"],
                "minute_trend": minute_profile["minute_trend"],
                "minute_volatility": minute_profile["minute_volatility"],
                "production_per_minute": minute_profile["production_per_minute"],
                "minute_confidence_delta": minute_profile["confidence_delta"],
                "minute_profile": minute_profile["opportunity_label"],
                "aggressiveness": aggressiveness,
                "confidence": confidence,
                "matchup_mult": boost,
                "blowout_mult": blowout_mult,
                "market_gap": None,
                "calibrated_hit_probability": 0.5,
                "implied_probability": None,
                "probability_edge": 0.0,
                "expected_value_over": 0.0,
                "fair_odds_over": None,
                "odds_over": self.odds_config["prop_over_odds"],
                "odds_under": self.odds_config["prop_under_odds"],
            }

            if injury_status:
                prop["injury_status"] = injury_status

            if player_stats.get("fallback"):
                prop["fallback"] = True

            if opponent_abbr:
                prop = apply_advanced_filters(prop, advanced_stats, opponent_abbr, is_home)

            prop["confidence"] = self.get_confidence_score(prop)

            props.append(prop)

        return props

    def _calculate_confidence(
        self,
        season_games: int,
        last5_games: int,
        season_avg: float,
        last5_avg: float,
        is_starter: bool,
        avg_minutes: float,
    ) -> float:
        score = 0.0

        if season_games >= 50:
            score += 3
        elif season_games >= 30:
            score += 2
        elif season_games >= 10:
            score += 1

        if last5_games >= 3:
            score += 2
        elif last5_games >= 1:
            score += 1

        if last5_avg > 0 and season_avg > 0:
            trend = last5_avg / season_avg
            if 0.85 <= trend <= 1.15:
                score += 2
            elif 0.7 <= trend <= 1.3:
                score += 1

        if is_starter:
            score += 1

        if avg_minutes >= 25:
            score += 2
        elif avg_minutes >= 20:
            score += 1
        elif avg_minutes < 15:
            score -= 1

        return score

    def generate_props_for_game(
        self,
        game: Dict,
        player_stats_cache: Dict[str, Dict],
        injured_players: Dict[str, str],
        questionable_players: Dict[str, str],
        teams_data: List[Dict],
        matchup_data: Optional[Dict[str, Dict]] = None,
        blowout_risk: Optional[Dict] = None,
    ) -> List[Dict]:
        all_props = []

        for player_name, player_stats in player_stats_cache.items():
            team = player_stats.get("team", "")
            if team not in [game["home"], game["away"]]:
                continue

            if player_name in injured_players:
                continue

            injury_status = questionable_players.get(player_name)
            opponent = game["away"] if team == game["home"] else game["home"]
            is_home = team == game["home"]

            season_games = player_stats.get("games_season", 0)
            avg_minutes = player_stats.get("avgMinutes_last5", 0.0)
            is_starter = player_stats.get("is_starter", season_games >= 30)

            props = self.generate_props_for_player(
                player_name, player_stats, injury_status, opponent,
                matchup_data, blowout_risk, is_starter, is_home
            )

            for prop in props:
                prop["avgMinutes_last5"] = avg_minutes

            for prop in props:
                prop["game_id"] = game["id"]
                prop["home"] = game["home"]
                prop["away"] = game["away"]
                prop["datetime"] = game["datetime"]
                prop["opponent"] = opponent
                prop["is_home"] = is_home
                all_props.append(prop)

        return all_props
