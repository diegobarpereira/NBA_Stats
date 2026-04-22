import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import config


class PerformanceAnalyzer:
    def __init__(self):
        self.comparison_file = config.DATA_DIR / "comparison_history.json"
        self.performance_file = config.DATA_DIR / "performance_history.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict:
        data = {
            "comparison_history": [],
            "performance_history": [],
        }

        if self.comparison_file.exists():
            try:
                with open(self.comparison_file, "r", encoding="utf-8") as f:
                    data["comparison_history"] = json.load(f)
            except:
                pass

        if self.performance_file.exists():
            try:
                with open(self.performance_file, "r", encoding="utf-8") as f:
                    data["performance_history"] = json.load(f)
            except:
                pass

        return data

    def get_type_accuracy(self) -> Dict[str, float]:
        type_stats = {}
        type_counts = {}

        for entry in self.data.get("performance_history", []):
            analysis = entry.get("type_analysis", {})
            for prop_type, stats in analysis.items():
                if prop_type not in type_stats:
                    type_stats[prop_type] = {"hits": 0, "total": 0}
                type_stats[prop_type]["hits"] += stats.get("hit", 0)
                type_stats[prop_type]["total"] += stats.get("hit", 0) + stats.get("miss", 0)

        accuracy = {}
        for prop_type, stats in type_stats.items():
            if stats["total"] > 0:
                accuracy[prop_type] = stats["hits"] / stats["total"]
            else:
                accuracy[prop_type] = 0.5

        return accuracy

    def get_confidence_accuracy(self) -> Dict[int, float]:
        conf_stats = {}

        for entry in self.data.get("performance_history", []):
            analysis = entry.get("conf_analysis", {})
            for conf, stats in analysis.items():
                try:
                    conf_int = int(float(conf)) if conf is not None else 0
                except (TypeError, ValueError):
                    conf_int = 0
                if conf_int not in conf_stats:
                    conf_stats[conf_int] = {"hits": 0, "total": 0}
                conf_stats[conf_int]["hits"] += stats.get("hit", 0)
                conf_stats[conf_int]["total"] += stats.get("hit", 0) + stats.get("miss", 0)

        accuracy = {}
        for conf, stats in conf_stats.items():
            if stats["total"] > 0:
                accuracy[conf] = stats["hits"] / stats["total"]
            else:
                accuracy[conf] = 0.5

        return accuracy

    def get_player_history(self, *args, **kwargs) -> Dict[str, Dict]:
        player_stats = {}

        for entry in self.data.get("performance_history", []):
            results = entry.get("comparison_results", [])
            for r in results:
                player = r.get("player", "")
                if not player:
                    continue

                if player not in player_stats:
                    player_stats[player] = {"hits": 0, "misses": 0, "push": 0}

                result = r.get("result", "")
                if "ACERTOU" in result:
                    player_stats[player]["hits"] += 1
                elif "ERROU" in result:
                    player_stats[player]["misses"] += 1
                else:
                    player_stats[player]["push"] += 1

        for player, stats in player_stats.items():
            total = stats["hits"] + stats["misses"]
            stats["accuracy"] = stats["hits"] / total if total > 0 else 0.5
            stats["total_bets"] = total

        return player_stats

    def get_over_under_accuracy(self) -> Dict[str, float]:
        ou_stats = {"Over": {"hits": 0, "total": 0}, "Under": {"hits": 0, "total": 0}}

        for entry in self.data.get("performance_history", []):
            analysis = entry.get("line_analysis", {})
            for ou_type, stats in analysis.items():
                if ou_type in ou_stats:
                    ou_stats[ou_type]["hits"] += stats.get("hit", 0)
                    ou_stats[ou_type]["total"] += stats.get("hit", 0) + stats.get("miss", 0)

        accuracy = {}
        for ou_type, stats in ou_stats.items():
            if stats["total"] > 0:
                accuracy[ou_type] = stats["hits"] / stats["total"]
            else:
                accuracy[ou_type] = 0.5

        return accuracy

    def get_trend_accuracy(self) -> Dict[str, float]:
        trend_stats = {"up": {"hits": 0, "total": 0}, "down": {"hits": 0, "total": 0}, "stable": {"hits": 0, "total": 0}}

        for entry in self.data.get("performance_history", []):
            results = entry.get("comparison_results", [])
            for r in results:
                trend = r.get("trend", "stable")
                if trend not in trend_stats:
                    continue
                
                result = r.get("result", "")
                is_hit = "ACERTOU" in result
                
                if is_hit:
                    trend_stats[trend]["hits"] += 1
                trend_stats[trend]["total"] += 1

        accuracy = {}
        for trend, stats in trend_stats.items():
            if stats["total"] > 0:
                accuracy[trend] = stats["hits"] / stats["total"]
            else:
                accuracy[trend] = 0.5

        return accuracy

    def get_trend_multipliers(self) -> Dict[str, float]:
        trend_acc = self.get_trend_accuracy()
        multipliers = {}

        for trend in ["up", "down", "stable"]:
            acc = trend_acc.get(trend, 0.5)
            if acc < 0.35:
                multipliers[trend] = 0.9
            elif acc > 0.65:
                multipliers[trend] = 1.08
            else:
                multipliers[trend] = 1.0

        return multipliers

    def get_consistency_accuracy(self) -> Dict[str, float]:
        consistency_ranges = {
            "high": {"hits": 0, "total": 0},
            "medium": {"hits": 0, "total": 0},
            "low": {"hits": 0, "total": 0},
        }

        for entry in self.data.get("performance_history", []):
            results = entry.get("comparison_results", [])
            for r in results:
                consistency = r.get("consistency", 0)
                
                if consistency >= 70:
                    key = "high"
                elif consistency >= 40:
                    key = "medium"
                else:
                    key = "low"
                
                result = r.get("result", "")
                is_hit = "ACERTOU" in result
                
                if is_hit:
                    consistency_ranges[key]["hits"] += 1
                consistency_ranges[key]["total"] += 1

        accuracy = {}
        for key, stats in consistency_ranges.items():
            if stats["total"] > 0:
                accuracy[key] = stats["hits"] / stats["total"]
            else:
                accuracy[key] = 0.5

        return accuracy

    def get_consistency_multipliers(self) -> Dict[str, float]:
        consistency_acc = self.get_consistency_accuracy()
        multipliers = {}

        for level in ["high", "medium", "low"]:
            acc = consistency_acc.get(level, 0.5)
            if acc < 0.35:
                multipliers[level] = 0.88
            elif acc > 0.65:
                multipliers[level] = 1.08
            else:
                multipliers[level] = 1.0

        return multipliers

    def get_matchup_bucket_accuracy(self) -> Dict[str, float]:
        matchup_stats = {
            "good": {"hits": 0, "total": 0},
            "neutral": {"hits": 0, "total": 0},
            "bad": {"hits": 0, "total": 0},
        }

        for entry in self.data.get("performance_history", []):
            results = entry.get("comparison_results", [])
            for row in results:
                matchup_mult = row.get("matchup_mult", 1.0)
                if matchup_mult > 1.05:
                    bucket = "good"
                elif matchup_mult < 0.95:
                    bucket = "bad"
                else:
                    bucket = "neutral"

                result = row.get("result", "")
                is_hit = "ACERTOU" in result

                if is_hit:
                    matchup_stats[bucket]["hits"] += 1
                matchup_stats[bucket]["total"] += 1

        accuracy = {}
        for bucket, stats in matchup_stats.items():
            if stats["total"] > 0:
                accuracy[bucket] = stats["hits"] / stats["total"]
            else:
                accuracy[bucket] = 0.5

        return accuracy

    def get_matchup_multipliers(self) -> Dict[str, float]:
        matchup_acc = self.get_matchup_bucket_accuracy()
        multipliers = {}

        for bucket in ["good", "neutral", "bad"]:
            acc = matchup_acc.get(bucket, 0.5)
            if acc < 0.35:
                multipliers[bucket] = 0.88
            elif acc > 0.60:
                multipliers[bucket] = 1.06
            else:
                multipliers[bucket] = 1.0

        return multipliers

    def get_market_gap_accuracy(self) -> Dict[str, float]:
        gap_stats = {
            "model_above_market": {"hits": 0, "total": 0},
            "aligned": {"hits": 0, "total": 0},
            "market_above_model": {"hits": 0, "total": 0},
            "no_market": {"hits": 0, "total": 0},
        }

        for entry in self.data.get("performance_history", []):
            analysis = entry.get("market_gap_analysis", {})
            for gap_key, stats in analysis.items():
                if gap_key not in gap_stats:
                    gap_stats[gap_key] = {"hits": 0, "total": 0}
                gap_stats[gap_key]["hits"] += stats.get("hit", 0)
                gap_stats[gap_key]["total"] += stats.get("hit", 0) + stats.get("miss", 0)

        accuracy = {}
        for gap_key, stats in gap_stats.items():
            if stats["total"] > 0:
                accuracy[gap_key] = stats["hits"] / stats["total"]
            else:
                accuracy[gap_key] = 0.5

        return accuracy

    def get_odds_source_accuracy(self) -> Dict[str, float]:
        source_stats = {}

        for entry in self.data.get("performance_history", []):
            analysis = entry.get("odds_source_analysis", {})
            for source, stats in analysis.items():
                if source not in source_stats:
                    source_stats[source] = {"hits": 0, "total": 0}
                source_stats[source]["hits"] += stats.get("hit", 0)
                source_stats[source]["total"] += stats.get("hit", 0) + stats.get("miss", 0)

        accuracy = {}
        for source, stats in source_stats.items():
            if stats["total"] > 0:
                accuracy[source] = stats["hits"] / stats["total"]
            else:
                accuracy[source] = 0.5

        return accuracy

    def get_aggressiveness_accuracy(self) -> Dict[str, float]:
        aggr_stats = {"low": {"hits": 0, "total": 0}, "medium": {"hits": 0, "total": 0}, "high": {"hits": 0, "total": 0}}

        for entry in self.data.get("performance_history", []):
            analysis = entry.get("aggressiveness_analysis", {})
            for level, stats in analysis.items():
                if level not in aggr_stats:
                    aggr_stats[level] = {"hits": 0, "total": 0}
                aggr_stats[level]["hits"] += stats.get("hit", 0)
                aggr_stats[level]["total"] += stats.get("hit", 0) + stats.get("miss", 0)

        accuracy = {}
        for level, stats in aggr_stats.items():
            if stats["total"] > 0:
                accuracy[level] = stats["hits"] / stats["total"]
            else:
                accuracy[level] = 0.5

        return accuracy

    def get_home_away_accuracy(self) -> Dict[str, float]:
        ha_stats = {"home": {"hits": 0, "total": 0}, "away": {"hits": 0, "total": 0}}

        for entry in self.data.get("performance_history", []):
            results = entry.get("comparison_results", [])
            for r in results:
                is_home = r.get("is_home", True)
                key = "home" if is_home else "away"
                
                result = r.get("result", "")
                is_hit = "ACERTOU" in result
                
                if is_hit:
                    ha_stats[key]["hits"] += 1
                ha_stats[key]["total"] += 1

        accuracy = {}
        for key, stats in ha_stats.items():
            if stats["total"] > 0:
                accuracy[key] = stats["hits"] / stats["total"]
            else:
                accuracy[key] = 0.5

        return accuracy

    def get_recommendations(self) -> List[str]:
        recommendations = []

        type_acc = self.get_type_accuracy()
        for prop_type, acc in type_acc.items():
            if acc < 0.35:
                recommendations.append(f"⚠️ {prop_type}: Acurácia muito baixa ({acc:.0%}). Considere desabilitar ou aumentar linhas.")
            elif acc > 0.70:
                recommendations.append(f"✅ {prop_type}: Excelente acurácia ({acc:.0%}). Pode aumentar confiança.")

        conf_acc = self.get_confidence_accuracy()
        for conf in sorted(conf_acc.keys()):
            acc = conf_acc[conf]
            if conf >= 9 and acc < 0.40:
                recommendations.append(f"⚠️ Confiança {conf}: Acurácia muito baixa ({acc:.0%}). Revisar critérios.")
            elif conf <= 6 and acc > 0.65:
                recommendations.append(f"💡 Confiança {conf}: Acurácia boa ({acc:.0%}). Pode ser subestimada.")

        ou_acc = self.get_over_under_accuracy()
        for ou_type, acc in ou_acc.items():
            if acc < 0.30:
                recommendations.append(f"📉 {ou_type}: Acurácia muito baixa ({acc:.0%}). Revisar linhas.")
            elif acc > 0.75:
                recommendations.append(f"📈 {ou_type}: Acurácia muito alta ({acc:.0%}). Sistema favorece esse tipo.")

        trend_acc = self.get_trend_accuracy()
        for trend, acc in trend_acc.items():
            if trend != "stable" and acc > 0:
                if acc < 0.35:
                    recommendations.append(f"📉 Trend {trend}: Acurácia baixa ({acc:.0%}). Cuidado com essa tendência.")
                elif acc > 0.65:
                    recommendations.append(f"📈 Trend {trend}: Acurácia boa ({acc:.0%}). Favoreça jogadores nessa tendência.")

        consistency_acc = self.get_consistency_accuracy()
        for level, acc in consistency_acc.items():
            if acc > 0:
                if level == "low" and acc < 0.40:
                    recommendations.append(f"⚠️ Baixa consistência: Acurácia ruim ({acc:.0%}). Evite jogadores voláteis.")
                elif level == "high" and acc > 0.60:
                    recommendations.append(f"✅ Alta consistência: Acurácia boa ({acc:.0%}). Favoreça jogadores consistentes.")

        return recommendations

    def get_weight_adjustment(self) -> Tuple[float, float]:
        season_weight = config.WEIGHT_CONFIG.get("season_weight", 0.6)
        last5_weight = config.WEIGHT_CONFIG.get("last5_weight", 0.4)

        type_acc = self.get_type_accuracy()
        if not type_acc:
            return season_weight, last5_weight

        avg_acc = sum(type_acc.values()) / len(type_acc)
        
        if avg_acc < 0.40:
            last5_weight = min(last5_weight + 0.1, 0.6)
            season_weight = 1.0 - last5_weight
        elif avg_acc > 0.65:
            last5_weight = max(last5_weight - 0.05, 0.2)
            season_weight = 1.0 - last5_weight

        return season_weight, last5_weight

    def get_confidence_multipliers(self) -> Dict[int, float]:
        conf_acc = self.get_confidence_accuracy()
        multipliers = {}

        for conf in range(1, 11):
            acc = conf_acc.get(conf, 0.5)
            if acc < 0.30:
                multipliers[conf] = 0.7
            elif acc < 0.40:
                multipliers[conf] = 0.85
            elif acc > 0.70:
                multipliers[conf] = 1.15
            else:
                multipliers[conf] = 1.0

        return multipliers

    def get_type_multipliers(self) -> Dict[str, float]:
        type_acc = self.get_type_accuracy()
        multipliers = {}

        for prop_type in config.PROP_TYPES:
            acc = type_acc.get(prop_type, 0.5)
            if acc < 0.30:
                multipliers[prop_type] = 0.6
            elif acc < 0.40:
                multipliers[prop_type] = 0.8
            elif acc > 0.70:
                multipliers[prop_type] = 1.2
            else:
                multipliers[prop_type] = 1.0

        return multipliers

    def get_player_confidence(self, player_name: str) -> float:
        player_history = self.get_player_history()
        if player_name in player_history:
            return player_history[player_name].get("accuracy", 0.5)
        return 0.5

    def _row_qualifies_for_mode(self, row: Dict, mode: str) -> bool:
        confidence = float(row.get("conf", 0) or 0)
        aggressiveness = row.get("aggressiveness")
        aggressiveness = float(aggressiveness) if isinstance(aggressiveness, (int, float)) else None
        odds_source = row.get("odds_source", "unknown")
        market_gap = row.get("market_gap")

        calibrated_prob, _ = self.estimate_hit_probability({
            "player": row.get("player", ""),
            "type": row.get("type", "").lower(),
            "confidence": confidence,
            "aggressiveness": aggressiveness if aggressiveness is not None else 0.3,
            "market_gap": market_gap,
            "odds_source": odds_source,
            "matchup_mult": row.get("matchup_mult", 1.0),
            "advanced_filters": {
                "trend": row.get("trend", "stable"),
                "consistency": row.get("consistency", 0),
            },
        })

        if mode == "aggressive":
            return confidence >= 6.0

        if odds_source != "api" or market_gap is None or aggressiveness is None:
            return False

        if mode == "balanced":
            return confidence >= 7.0 and market_gap >= -0.75 and aggressiveness <= 0.32 and calibrated_prob >= 0.50

        if mode == "conservative":
            return confidence >= 8.0 and market_gap >= -0.25 and aggressiveness <= 0.22 and calibrated_prob >= 0.53

        return False

    def build_mode_backtest_summary(self) -> Dict:
        modes = ["conservative", "balanced", "aggressive"]
        daily = {}
        overall = {
            mode: {"hits": 0, "misses": 0, "pushes": 0, "qualified": 0, "settled": 0, "hit_rate": None}
            for mode in modes
        }

        for entry in self.data.get("performance_history", []):
            date_key = entry.get("date", "unknown")
            if date_key not in daily:
                daily[date_key] = {
                    mode: {"hits": 0, "misses": 0, "pushes": 0, "qualified": 0, "settled": 0, "hit_rate": None}
                    for mode in modes
                }

            for row in entry.get("comparison_results", []):
                result = row.get("result", "")
                for mode in modes:
                    if not self._row_qualifies_for_mode(row, mode):
                        continue

                    bucket = daily[date_key][mode]
                    bucket["qualified"] += 1
                    overall[mode]["qualified"] += 1

                    if "ACERTOU" in result:
                        bucket["hits"] += 1
                        bucket["settled"] += 1
                        overall[mode]["hits"] += 1
                        overall[mode]["settled"] += 1
                    elif "ERROU" in result:
                        bucket["misses"] += 1
                        bucket["settled"] += 1
                        overall[mode]["misses"] += 1
                        overall[mode]["settled"] += 1
                    else:
                        bucket["pushes"] += 1
                        overall[mode]["pushes"] += 1

        for mode in modes:
            settled = overall[mode]["settled"]
            overall[mode]["hit_rate"] = round(overall[mode]["hits"] / settled, 3) if settled else None

        for _, day_stats in daily.items():
            for mode in modes:
                settled = day_stats[mode]["settled"]
                day_stats[mode]["hit_rate"] = round(day_stats[mode]["hits"] / settled, 3) if settled else None

        return {
            "updated_at": datetime.now().isoformat(),
            "thresholds": {
                "conservative": {"min_confidence": 8.0, "max_aggressiveness": 0.22, "min_market_gap": -0.25, "min_probability": 0.53},
                "balanced": {"min_confidence": 7.0, "max_aggressiveness": 0.32, "min_market_gap": -0.75, "min_probability": 0.50},
                "aggressive": {"min_confidence": 6.0},
            },
            "overall": overall,
            "daily": dict(sorted(daily.items())),
        }

    def save_mode_backtest_summary(self) -> Path:
        backtest_file = config.DATA_DIR / "backtest_summary.json"
        backtest_file.parent.mkdir(parents=True, exist_ok=True)

        with open(backtest_file, "w", encoding="utf-8") as f:
            json.dump(self.build_mode_backtest_summary(), f, ensure_ascii=False, indent=2)

        return backtest_file

    def estimate_hit_probability(self, prop: Dict) -> Tuple[float, Dict[str, float]]:
        components = []
        component_values = {}

        player_name = prop.get("player", "")
        player_history = self.get_player_history().get(player_name, {})
        player_total = player_history.get("total_bets", 0)
        if player_total > 0:
            player_weight = min(0.22, 0.08 + (player_total * 0.02))
            player_acc = player_history.get("accuracy", 0.5)
            components.append((player_weight, player_acc))
            component_values["player_accuracy"] = round(player_acc, 3)

        prop_type = prop.get("type", "")
        type_acc = self.get_type_accuracy().get(prop_type, 0.5)
        components.append((0.20, type_acc))
        component_values["type_accuracy"] = round(type_acc, 3)

        conf_value = int(max(1, min(10, round(float(prop.get("confidence", 5))))))
        conf_acc = self.get_confidence_accuracy().get(conf_value, 0.5)
        components.append((0.18, conf_acc))
        component_values["confidence_accuracy"] = round(conf_acc, 3)

        adv = prop.get("advanced_filters", {})
        trend_key = adv.get("trend", "stable")
        trend_acc = self.get_trend_accuracy().get(trend_key, 0.5)
        components.append((0.10, trend_acc))
        component_values["trend_accuracy"] = round(trend_acc, 3)

        consistency = adv.get("consistency", 50)
        if consistency >= 70:
            consistency_key = "high"
        elif consistency >= 40:
            consistency_key = "medium"
        else:
            consistency_key = "low"
        consistency_acc = self.get_consistency_accuracy().get(consistency_key, 0.5)
        components.append((0.10, consistency_acc))
        component_values["consistency_accuracy"] = round(consistency_acc, 3)

        matchup_mult = float(prop.get("matchup_mult", 1.0))
        if matchup_mult > 1.05:
            matchup_key = "good"
        elif matchup_mult < 0.95:
            matchup_key = "bad"
        else:
            matchup_key = "neutral"
        matchup_acc = self.get_matchup_bucket_accuracy().get(matchup_key, 0.5)
        components.append((0.08, matchup_acc))
        component_values["matchup_accuracy"] = round(matchup_acc, 3)

        aggressiveness = float(prop.get("aggressiveness", 0.3))
        if aggressiveness <= 0.20:
            aggr_key = "low"
        elif aggressiveness <= 0.35:
            aggr_key = "medium"
        else:
            aggr_key = "high"
        aggr_acc = self.get_aggressiveness_accuracy().get(aggr_key, 0.5)
        components.append((0.07, aggr_acc))
        component_values["aggressiveness_accuracy"] = round(aggr_acc, 3)

        market_gap = prop.get("market_gap")
        if market_gap is None:
            gap_key = "no_market"
        elif market_gap >= 0.5:
            gap_key = "model_above_market"
        elif market_gap <= -0.5:
            gap_key = "market_above_model"
        else:
            gap_key = "aligned"
        gap_acc = self.get_market_gap_accuracy().get(gap_key, 0.5)
        components.append((0.03, gap_acc))
        component_values["market_gap_accuracy"] = round(gap_acc, 3)

        odds_source = prop.get("odds_source", "unknown")
        odds_source_acc = self.get_odds_source_accuracy().get(odds_source, 0.5)
        components.append((0.02, odds_source_acc))
        component_values["odds_source_accuracy"] = round(odds_source_acc, 3)

        total_weight = sum(weight for weight, _ in components)
        weighted_prob = sum(weight * value for weight, value in components) / total_weight if total_weight else 0.5

        prior_strength = max(0.12, 0.40 - min(player_total, 10) * 0.02)
        calibrated_prob = (weighted_prob * (1 - prior_strength)) + (0.52 * prior_strength)
        calibrated_prob = max(0.15, min(calibrated_prob, 0.85))

        component_values["weighted_probability"] = round(weighted_prob, 3)
        component_values["prior_strength"] = round(prior_strength, 3)
        component_values["calibrated_probability"] = round(calibrated_prob, 3)

        return calibrated_prob, component_values

    def get_summary(self) -> Dict:
        return {
            "type_accuracy": self.get_type_accuracy(),
            "confidence_accuracy": self.get_confidence_accuracy(),
            "over_under_accuracy": self.get_over_under_accuracy(),
            "trend_accuracy": self.get_trend_accuracy(),
            "consistency_accuracy": self.get_consistency_accuracy(),
            "matchup_accuracy": self.get_matchup_bucket_accuracy(),
            "market_gap_accuracy": self.get_market_gap_accuracy(),
            "odds_source_accuracy": self.get_odds_source_accuracy(),
            "aggressiveness_accuracy": self.get_aggressiveness_accuracy(),
            "home_away_accuracy": self.get_home_away_accuracy(),
            "recommendations": self.get_recommendations(),
            "suggested_weights": self.get_weight_adjustment(),
            "total_bets": sum(
                sum(entry.get("type_analysis", {}).get(t, {}).get("hit", 0) + entry.get("type_analysis", {}).get(t, {}).get("miss", 0) for t in entry.get("type_analysis", {}))
                for entry in self.data.get("performance_history", [])
            ),
        }

    def build_calibration_snapshot(self) -> Dict:
        return {
            "updated_at": datetime.now().isoformat(),
            "comparison_entries": len(self.data.get("comparison_history", [])),
            "performance_entries": len(self.data.get("performance_history", [])),
            "summary": self.get_summary(),
            "multipliers": {
                "type": self.get_type_multipliers(),
                "confidence": self.get_confidence_multipliers(),
                "trend": self.get_trend_multipliers(),
                "consistency": self.get_consistency_multipliers(),
                "matchup": self.get_matchup_multipliers(),
            },
        }

    def save_calibration_snapshot(self) -> Path:
        snapshot_file = config.DATA_DIR / "calibration_snapshot.json"
        snapshot_file.parent.mkdir(parents=True, exist_ok=True)

        with open(snapshot_file, "w", encoding="utf-8") as f:
            json.dump(self.build_calibration_snapshot(), f, ensure_ascii=False, indent=2)

        return snapshot_file


def get_performance_analyzer() -> PerformanceAnalyzer:
    return PerformanceAnalyzer()


def save_calibration_snapshot() -> Path:
    return get_performance_analyzer().save_calibration_snapshot()


def save_mode_backtest_summary() -> Path:
    return get_performance_analyzer().save_mode_backtest_summary()
