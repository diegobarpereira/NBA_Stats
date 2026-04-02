import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
CACHE_FILE = DATA_DIR / "cache_stats.json"
ODDS_CACHE_FILE = DATA_DIR / "odds_cache_{date}.json"

THE_ODDS_API_KEY = "fdc16fc87bf1afd7f998ec2b82473e6b"

DATA_FILES = {
    "teams": BASE_DIR / "nba_por_equipe.json",
    "games": DATA_DIR / "jogos_do_dia.json",
    "injuries": DATA_DIR / "relatorio_lesoes.json",
}

ODDS_CONFIG = {
    "min_total_odds": 5.0,
    "max_total_odds": 8.0,
    "default_prop_odds": 1.35,
    "prop_over_odds": 1.35,
    "prop_under_odds": 1.38,
}

WEIGHT_CONFIG = {
    "season_weight": 0.6,
    "last5_weight": 0.4,
}

INJURY_ADJUSTMENTS = {
    "OUT": 0.0,
    "DOUBTFUL": 0.0,
    "QUESTIONABLE": 0.9,
    "PROBABLE": 1.0,
    "ACTIVE": 1.0,
}

PROP_TYPES = ["points", "rebounds", "assists", "3pt"]

PROP_ABBREV = {
    "points": "PTS",
    "rebounds": "REB",
    "assists": "AST",
    "3pt": "3PM",
}

SCRAPING_CONFIG = {
    "base_url": "https://www.basketball-reference.com",
    "cache_ttl_hours": 24,
    "request_delay_seconds": 2,
}

TEAM_NAME_MAPPING = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "LA Clippers": "LAC",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}

TEAM_NAME_REVERSE = {v: k for k, v in TEAM_NAME_MAPPING.items()}

ODDSJAM_URL = "https://www.oddsjam.com/nba/player-props"
