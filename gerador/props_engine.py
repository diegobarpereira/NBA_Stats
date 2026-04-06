from typing import Dict, List, Optional, Tuple

import config
from scrapers.matchup_scraper import get_matchup_boost
from scrapers.advanced_filters import apply_advanced_filters, get_schedule_info


class PropsEngine:
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

    def calculate_adjusted_line(
        self,
        player_stats: Dict,
        prop_type: str,
        injury_status: Optional[str] = None,
        player_name: Optional[str] = None,
    ) -> float:
        season_key = f"avg{prop_type.capitalize()}_season"
        last5_key = f"avg{prop_type.capitalize()}_last5"

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

    def generate_props_for_player(
        self,
        player_name: str,
        player_stats: Dict,
        injury_status: Optional[str] = None,
        opponent: Optional[str] = None,
        matchup_data: Optional[Dict[str, Dict]] = None,
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

        # Advanced filters: schedule info
        schedule_info = {}
        opponent_abbr = ""
        if opponent:
            abbr_map = {v: k for k, v in config.TEAM_NAME_MAPPING.items()}
            opponent_abbr = abbr_map.get(opponent, opponent[:3].upper())

        # Get last5 game values for trend/variance analysis
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

        for prop_type in self.prop_types:
            if prop_type == "3pt" and player_stats.get("avg3PT_season", 0) < 0.3:
                continue

            base_line = self.calculate_adjusted_line(player_stats, prop_type, injury_status, player_name)

            matchup_mult = 1.0
            if opponent and matchup_data and position:
                matchup_mult = get_matchup_boost(opponent, position, prop_type, matchup_data)
                base_line = round(base_line * matchup_mult, 1)

            blowout_mult = 1.0
            if blowout_risk and blowout_risk.get("blowout_prob", 0) > 0.20:
                blowout_mult = self._apply_blowout_adjustment(
                    team, base_line, blowout_risk, is_starter
                )
                base_line = round(base_line * blowout_mult, 1)

            if base_line <= 0:
                continue

            prop = {
                "player": player_name,
                "team": team,
                "position": position,
                "type": prop_type,
                "abbrev": self.prop_abbrev[prop_type],
                "line": base_line,
                "season_avg": player_stats.get(f"avg{prop_type.capitalize()}_season", 0),
                "last5_avg": player_stats.get(f"avg{prop_type.capitalize()}_last5", 0),
                "season_games": season_games,
                "last5_games": last5_games,
                "odds_over": self.odds_config["prop_over_odds"],
                "odds_under": self.odds_config["prop_under_odds"],
                "matchup_mult": round(matchup_mult, 3),
                "blowout_mult": round(blowout_mult, 3),
                "is_starter": is_starter,
            }

            if injury_status:
                prop["injury_status"] = injury_status

            if player_stats.get("fallback"):
                prop["fallback"] = True

            # Apply advanced filters
            if opponent_abbr:
                prop = apply_advanced_filters(prop, advanced_stats, opponent_abbr, is_home)

            props.append(prop)

        return props

    def _apply_blowout_adjustment(
        self,
        team: str,
        base_line: float,
        blowout_risk: Dict,
        is_starter: bool,
    ) -> float:
        prob = blowout_risk.get("blowout_prob", 0)
        if prob <= 0.20:
            return 1.0

        loser = blowout_risk.get("loser")
        direction = blowout_risk.get("direction")

        if loser and team == loser:
            if is_starter:
                mult = 1.0 - (prob * 0.45)
            else:
                mult = 1.0 + (prob * 0.35)
        elif direction and direction != "competitive" and team != loser:
            if is_starter:
                mult = 1.0 - (prob * 0.15)
            else:
                mult = 1.0 + (prob * 0.25)
        else:
            mult = 1.0

        return max(0.5, min(mult, 1.5))

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

    def filter_top_props(self, props: List[Dict], max_per_type: int = 2) -> List[Dict]:
        by_player_type = {}
        for prop in props:
            key = (prop["player"], prop["type"])
            if key not in by_player_type:
                by_player_type[key] = prop

        filtered = list(by_player_type.values())

        filtered.sort(key=lambda p: (
            -p["season_games"],
            -p["last5_games"],
            -p["line"],
        ))

        return filtered

    def get_confidence_score(self, prop: Dict) -> float:
        score = 0.0

        season_games = prop.get("season_games", 0)
        last5_games = prop.get("last5_games", 0)
        line = prop.get("line", 0)
        season_avg = prop.get("season_avg", 0)
        last5_avg = prop.get("last5_avg", 0)

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

        avg_minutes = prop.get("avgMinutes_last5", 0)
        is_starter = prop.get("is_starter", True)
        
        if avg_minutes >= 30:
            score += 2
        elif avg_minutes >= 25:
            score += 1
        elif avg_minutes < 15 and not is_starter:
            score -= 2
        elif avg_minutes < 20 and not is_starter:
            score -= 1

        matchup_mult = prop.get("matchup_mult", 1.0)
        if matchup_mult > 1.05:
            score += 1
        elif matchup_mult < 0.95:
            score -= 1

        # Advanced filters adjustments
        adv = prop.get("advanced_filters", {})
        if adv:
            # Trend adjustment
            trend = adv.get("trend", "stable")
            trend_strength = adv.get("trend_strength", 0)
            
            if trend == "up" and trend_strength > 0.1:
                score += min(2, trend_strength * 3)
            elif trend == "down" and trend_strength < -0.1:
                score -= min(3, abs(trend_strength) * 4)
            
            # Consistency adjustment
            consistency = adv.get("consistency", 100)
            if consistency < 30:
                score -= 2
            elif consistency < 50:
                score -= 1
            elif consistency > 80:
                score += 1
            
            # Volatility penalty
            vol_penalty = adv.get("volatility_penalty", 0)
            if vol_penalty > 0:
                score -= vol_penalty * 5
            
            # Pace factor
            pace_factor = adv.get("pace_factor", 1.0)
            if pace_factor > 1.03:
                score += 1
            elif pace_factor < 0.97:
                score -= 1
            
            # Home/away factor
            home_factor = adv.get("home_away_factor", 1.0)
            if home_factor > 1.0:
                score += 0.5

        if self.performance_analyzer:
            player_name = prop.get("player", "")
            prop_type = prop.get("type", "")
            
            player_acc = self.performance_analyzer.get_player_confidence(player_name)
            type_mult = self.performance_analyzer.get_type_multipliers().get(prop_type, 1.0)
            
            if player_acc < 0.3:
                score -= 2
            elif player_acc < 0.4:
                score -= 1
            elif player_acc > 0.7:
                score += 1

            score *= type_mult
            score = max(0, min(score, 10))

        return max(0, min(score, 10))


def get_prop_display(prop: Dict) -> str:
    line = prop["line"]
    line_int = int(line) if line == int(line) else line
    return f"{prop['player']} - {prop['abbrev']} +{line_int}"
