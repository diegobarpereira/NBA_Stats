"""
Filtros avançados para análise de props NBA

Inclui:
- Trend detection (streak ascendente/descendente)
- Variance tracking (consistência do jogador)
- Rest days / Back-to-back detection
- Opponent pace analysis
- Home/away split
"""

import json
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

import config

ADVANCED_CACHE = config.DATA_DIR / "cache_advanced.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Pace e defensive ratings por time (NBA 2025-26 aproximado)
# Fonte: NBA.com/stats
TEAM_ADVANCED_STATS = {
    "ATL": {"pace": 101.2, "off_rtg": 117.8, "def_rtg": 115.2, "net_rtg": 2.6},
    "BOS": {"pace": 98.5, "off_rtg": 120.1, "def_rtg": 110.3, "net_rtg": 9.8},
    "BKN": {"pace": 99.8, "off_rtg": 114.5, "def_rtg": 116.8, "net_rtg": -2.3},
    "CHA": {"pace": 100.1, "off_rtg": 112.3, "def_rtg": 118.5, "net_rtg": -6.2},
    "CHI": {"pace": 98.9, "off_rtg": 113.7, "def_rtg": 115.9, "net_rtg": -2.2},
    "CLE": {"pace": 96.8, "off_rtg": 121.5, "def_rtg": 108.2, "net_rtg": 13.3},
    "DAL": {"pace": 99.2, "off_rtg": 118.9, "def_rtg": 113.4, "net_rtg": 5.5},
    "DEN": {"pace": 97.5, "off_rtg": 119.3, "def_rtg": 112.1, "net_rtg": 7.2},
    "DET": {"pace": 99.5, "off_rtg": 115.2, "def_rtg": 114.8, "net_rtg": 0.4},
    "GSW": {"pace": 100.3, "off_rtg": 117.2, "def_rtg": 113.5, "net_rtg": 3.7},
    "HOU": {"pace": 97.8, "off_rtg": 116.8, "def_rtg": 109.5, "net_rtg": 7.3},
    "IND": {"pace": 102.5, "off_rtg": 119.8, "def_rtg": 117.2, "net_rtg": 2.6},
    "LAC": {"pace": 98.2, "off_rtg": 115.5, "def_rtg": 111.8, "net_rtg": 3.7},
    "LAL": {"pace": 99.1, "off_rtg": 118.2, "def_rtg": 114.5, "net_rtg": 3.7},
    "MEM": {"pace": 100.8, "off_rtg": 116.5, "def_rtg": 112.8, "net_rtg": 3.7},
    "MIA": {"pace": 97.2, "off_rtg": 113.5, "def_rtg": 111.2, "net_rtg": 2.3},
    "MIL": {"pace": 99.5, "off_rtg": 117.8, "def_rtg": 113.2, "net_rtg": 4.6},
    "MIN": {"pace": 98.1, "off_rtg": 115.2, "def_rtg": 110.8, "net_rtg": 4.4},
    "NOP": {"pace": 99.8, "off_rtg": 114.2, "def_rtg": 116.5, "net_rtg": -2.3},
    "NYK": {"pace": 97.5, "off_rtg": 118.5, "def_rtg": 111.5, "net_rtg": 7.0},
    "OKC": {"pace": 98.8, "off_rtg": 121.2, "def_rtg": 107.5, "net_rtg": 13.7},
    "ORL": {"pace": 97.2, "off_rtg": 112.8, "def_rtg": 108.5, "net_rtg": 4.3},
    "PHI": {"pace": 98.5, "off_rtg": 116.2, "def_rtg": 113.8, "net_rtg": 2.4},
    "PHX": {"pace": 99.5, "off_rtg": 118.2, "def_rtg": 114.2, "net_rtg": 4.0},
    "POR": {"pace": 100.5, "off_rtg": 113.8, "def_rtg": 118.2, "net_rtg": -4.4},
    "SAC": {"pace": 101.2, "off_rtg": 117.5, "def_rtg": 115.8, "net_rtg": 1.7},
    "SAS": {"pace": 99.2, "off_rtg": 114.5, "def_rtg": 115.2, "net_rtg": -0.7},
    "TOR": {"pace": 99.8, "off_rtg": 113.2, "def_rtg": 116.8, "net_rtg": -3.6},
    "UTA": {"pace": 98.5, "off_rtg": 111.5, "def_rtg": 117.5, "net_rtg": -6.0},
    "WAS": {"pace": 100.2, "off_rtg": 112.5, "def_rtg": 119.2, "net_rtg": -6.7},
}


def calculate_trend(last5_games: List[float]) -> Tuple[str, float]:
    """
    Analisa a tendência dos últimos 5 jogos.
    
    Retorna:
        - trend: "up", "down", "stable"
        - strength: quão forte é a tendência (-1 a 1)
    """
    if len(last5_games) < 3:
        return "stable", 0.0
    
    # Regressão linear simples
    n = len(last5_games)
    x_mean = (n - 1) / 2
    y_mean = sum(last5_games) / n
    
    numerator = sum((i - x_mean) * (last5_games[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    
    if denominator == 0:
        return "stable", 0.0
    
    slope = numerator / denominator
    
    # Normalizar slope baseado na média
    if y_mean == 0:
        normalized_slope = 0
    else:
        normalized_slope = slope / y_mean
    
    # Classificar
    if normalized_slope > 0.05:
        trend = "up"
    elif normalized_slope < -0.05:
        trend = "down"
    else:
        trend = "stable"
    
    # Clamp strength entre -1 e 1
    strength = max(-1.0, min(1.0, normalized_slope * 5))
    
    return trend, strength


def calculate_variance(values: List[float]) -> Dict:
    """
    Calcula variância e desvio padrão de uma lista de valores.
    
    Retorna dict com:
        - std_dev: desvio padrão
        - cv: coeficiente de variação (std/mean)
        - consistency: quão consistente é o jogador (0-100)
        - min_val, max_val, range
    """
    if len(values) < 2:
        return {
            "std_dev": 0,
            "cv": 0,
            "consistency": 100,
            "min_val": values[0] if values else 0,
            "max_val": values[0] if values else 0,
            "range": 0,
        }
    
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    std_dev = math.sqrt(variance)
    
    cv = std_dev / mean if mean > 0 else 0
    
    # Consistência: 100 = perfeitamente consistente, 0 = muito volátil
    # CV de 0.5 = 50% de variação = consistência ~50
    consistency = max(0, min(100, (1 - cv) * 100))
    
    return {
        "std_dev": round(std_dev, 2),
        "cv": round(cv, 3),
        "consistency": round(consistency, 1),
        "min_val": min(values),
        "max_val": max(values),
        "range": round(max(values) - min(values), 1),
    }


def get_pace_factor(opponent_abbr: str) -> float:
    """
    Retorna fator de ajuste baseado no pace do oponente.
    Pace > 100 = mais posses = mais stats
    Pace < 98 = menos posses = menos stats
    """
    team_stats = TEAM_ADVANCED_STATS.get(opponent_abbr, {})
    pace = team_stats.get("pace", 99.0)
    
    # Normalizar: pace 99.0 = 1.0, cada ponto = ~1%
    return round(1.0 + (pace - 99.0) * 0.01, 3)


def get_defensive_factor(opponent_abbr: str, stat_type: str) -> float:
    """
    Retorna fator de ajuste baseado no defensive rating do oponente.
    Def rating baixo = boa defesa = fator < 1
    Def rating alto = ruim defesa = fator > 1
    """
    team_stats = TEAM_ADVANCED_STATS.get(opponent_abbr, {})
    def_rtg = team_stats.get("def_rtg", 113.0)
    
    # League average def rating ~113
    # Cada ponto acima/abaixo = ~0.5% de ajuste
    factor = 1.0 + (def_rtg - 113.0) * 0.005
    
    return round(max(0.85, min(1.15, factor)), 3)


def get_net_rating_factor(opponent_abbr: str) -> float:
    """
    Retorna fator baseado no net rating do oponente.
    Times com net rating negativo tendem a perder mais = blowout risk
    """
    team_stats = TEAM_ADVANCED_STATS.get(opponent_abbr, {})
    net_rtg = team_stats.get("net_rtg", 0)
    
    # Times muito ruins (net < -5) = blowout risk alto
    if net_rtg < -5:
        return 0.90  # Reduzir expectativa (blowout)
    elif net_rtg < -2:
        return 0.95
    elif net_rtg < 0:
        return 0.98
    elif net_rtg < 3:
        return 1.0
    elif net_rtg < 7:
        return 1.02
    else:
        return 1.05  # Times muito bons podem dar blowout


def calculate_advanced_metrics(
    player_stats: Dict,
    opponent_abbr: str,
    is_home: bool = True,
) -> Dict:
    """
    Calcula todos os filtros avançados para um jogador.
    
    Args:
        player_stats: Dados do jogador (deve ter season_avg e last5)
        opponent_abbr: Abreviação do time adversário
        is_home: Se o jogador está jogando em casa
    
    Returns:
        Dict com todos os filtros avançados
    """
    # Home/away factor based on actual player splits
    home_ppg = player_stats.get("home_ppg", 0)
    away_ppg = player_stats.get("away_ppg", 0)
    season_ppg = player_stats.get("avgPoints_season", 0)
    
    if is_home and home_ppg > 0:
        home_away_factor = home_ppg / season_ppg if season_ppg > 0 else 1.0
    elif not is_home and away_ppg > 0:
        home_away_factor = away_ppg / season_ppg if season_ppg > 0 else 1.0
    else:
        home_away_factor = 1.03 if is_home else 0.97
    
    result = {
        "pace_factor": get_pace_factor(opponent_abbr),
        "defensive_factor": get_defensive_factor(opponent_abbr, "points"),
        "net_rating_factor": get_net_rating_factor(opponent_abbr),
        "home_away_factor": round(home_away_factor, 3),
        "trend": "stable",
        "trend_strength": 0.0,
        "variance": {},
        "volatility_penalty": 0.0,
    }
    
    # Trend e variance para pontos
    last5_pts = player_stats.get("last5_points", [])
    if last5_pts and len(last5_pts) >= 3:
        trend, strength = calculate_trend(last5_pts)
        result["trend"] = trend
        result["trend_strength"] = round(strength, 3)
        
        variance = calculate_variance(last5_pts)
        result["variance"] = variance
        
        # Penalizar volatilidade alta
        if variance["consistency"] < 30:
            result["volatility_penalty"] = 0.10
        elif variance["consistency"] < 50:
            result["volatility_penalty"] = 0.05
    
    return result


def get_schedule_info(team_abbr: str) -> Dict:
    """
    Busca informações de schedule do time (últimos jogos, próximos jogos).
    Usa ESPN para obter dados de schedule.
    
    Retorna:
        - last_game_date: data do último jogo
        - days_rest: dias de descanso desde o último jogo
        - is_back_to_back: se jogou ontem
        - recent_games: lista dos últimos 5 jogos
    """
    try:
        abbr_map = {
            "ATL": "1", "BOS": "2", "BKN": "17", "CHA": "30", "CHI": "4",
            "CLE": "5", "DAL": "6", "DEN": "7", "DET": "8", "GSW": "9",
            "HOU": "10", "IND": "11", "LAC": "12", "LAL": "13", "MEM": "29",
            "MIA": "14", "MIL": "15", "MIN": "16", "NOP": "3", "NYK": "18",
            "OKC": "25", "ORL": "19", "PHI": "20", "PHX": "21", "POR": "22",
            "SAC": "23", "SAS": "24", "TOR": "28", "UTA": "26", "WAS": "27",
        }
        
        team_id = abbr_map.get(team_abbr)
        if not team_id:
            return {"days_rest": 3, "is_back_to_back": False}
        
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/schedule"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        
        if resp.status_code != 200:
            return {"days_rest": 3, "is_back_to_back": False}
        
        data = resp.json()
        events = data.get("events", [])
        
        if not events:
            return {"days_rest": 3, "is_back_to_back": False}
        
        # Encontrar último jogo completado
        last_game_date = None
        recent_games = []
        
        for event in events:
            status = event.get("status", {}).get("type", {}).get("state", "")
            if status == "STATUS_FINAL":
                date_str = event.get("date", "")
                if date_str:
                    game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    recent_games.append(game_date)
                    if last_game_date is None:
                        last_game_date = game_date
        
        if not last_game_date:
            return {"days_rest": 3, "is_back_to_back": False}
        
        now = datetime.now(game_date.tzinfo) if game_date.tzinfo else datetime.now()
        days_rest = (now - last_game_date).days
        
        # Verificar se é back-to-back (jogou ontem)
        is_b2b = days_rest <= 1
        
        # Verificar se tem jogo amanhã (próximo B2B potencial)
        next_games = []
        for event in events:
            status = event.get("status", {}).get("type", {}).get("state", "")
            if status == "STATUS_SCHEDULED":
                date_str = event.get("date", "")
                if date_str:
                    game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    next_games.append(game_date)
        
        return {
            "last_game_date": last_game_date.isoformat() if last_game_date else None,
            "days_rest": days_rest,
            "is_back_to_back": is_b2b,
            "recent_games_count": len(recent_games),
            "next_game_soon": len(next_games) > 0 and (next_games[0] - datetime.now()).days <= 1,
        }
        
    except Exception as e:
        print(f"Erro ao buscar schedule para {team_abbr}: {e}")
        return {"days_rest": 3, "is_back_to_back": False}


def apply_advanced_filters(
    prop: Dict,
    player_stats: Dict,
    opponent_abbr: str,
    is_home: bool = True,
) -> Dict:
    """
    Aplica todos os filtros avançados a um prop e retorna o prop ajustado.
    
    Args:
        prop: Prop original do sistema
        player_stats: Dados completos do jogador
        opponent_abbr: Time adversário
        is_home: Se está jogando em casa
    
    Returns:
        Prop com ajustes avançados
    """
    advanced = calculate_advanced_metrics(player_stats, opponent_abbr, is_home)
    
    # Fatores combinados
    combined_factor = 1.0
    combined_factor *= advanced["pace_factor"]
    combined_factor *= advanced["defensive_factor"]
    combined_factor *= advanced["net_rating_factor"]
    combined_factor *= advanced["home_away_factor"]
    
    # Ajustar linha baseada nos fatores
    original_line = prop.get("line", 0)
    adjusted_line = original_line * combined_factor
    
    # Penalizar volatilidade
    vol_penalty = advanced.get("volatility_penalty", 0)
    if vol_penalty > 0:
        adjusted_line *= (1 - vol_penalty)
    
    # Ajustar confidence baseado em trend e consistência
    original_confidence = prop.get("confidence", 5)
    confidence_adj = 0
    
    # Trend adjustment
    trend = advanced.get("trend", "stable")
    trend_strength = advanced.get("trend_strength", 0)
    
    if trend == "up" and trend_strength > 0.1:
        confidence_adj += min(2, trend_strength * 3)
    elif trend == "down" and trend_strength < -0.1:
        confidence_adj -= min(3, abs(trend_strength) * 4)
    
    # Consistency adjustment
    variance = advanced.get("variance", {})
    consistency = variance.get("consistency", 100)
    
    if consistency < 30:
        confidence_adj -= 2
    elif consistency < 50:
        confidence_adj -= 1
    elif consistency > 80:
        confidence_adj += 1
    
    new_confidence = max(1, min(10, original_confidence + confidence_adj))
    
    # Adicionar metadados ao prop
    prop["advanced_filters"] = {
        "pace_factor": advanced["pace_factor"],
        "defensive_factor": advanced["defensive_factor"],
        "net_rating_factor": advanced["net_rating_factor"],
        "home_away_factor": advanced["home_away_factor"],
        "combined_factor": round(combined_factor, 3),
        "trend": trend,
        "trend_strength": trend_strength,
        "consistency": consistency,
        "volatility_penalty": vol_penalty,
        "original_line": original_line,
        "adjusted_line": round(adjusted_line, 1),
        "original_confidence": original_confidence,
        "adjusted_confidence": round(new_confidence, 1),
    }
    
    # Atualizar linha e confidence com valores ajustados
    prop["line"] = round(adjusted_line, 1)
    prop["confidence"] = round(new_confidence, 1)
    
    return prop


def load_advanced_cache() -> Dict:
    """Carrega cache de dados avançados."""
    if ADVANCED_CACHE.exists():
        try:
            with open(ADVANCED_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_advanced_cache(data: Dict) -> None:
    """Salva cache de dados avançados."""
    with open(ADVANCED_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
