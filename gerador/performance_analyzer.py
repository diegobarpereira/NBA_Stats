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
                conf_int = int(conf) if conf else 0
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

    def get_player_history(self) -> Dict[str, Dict]:
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

    def get_summary(self) -> Dict:
        return {
            "type_accuracy": self.get_type_accuracy(),
            "confidence_accuracy": self.get_confidence_accuracy(),
            "over_under_accuracy": self.get_over_under_accuracy(),
            "recommendations": self.get_recommendations(),
            "suggested_weights": self.get_weight_adjustment(),
            "total_bets": sum(
                sum(entry.get("type_analysis", {}).get(t, {}).get("hit", 0) + entry.get("type_analysis", {}).get(t, {}).get("miss", 0) for t in entry.get("type_analysis", {}))
                for entry in self.data.get("performance_history", [])
            ),
        }


def get_performance_analyzer() -> PerformanceAnalyzer:
    return PerformanceAnalyzer()