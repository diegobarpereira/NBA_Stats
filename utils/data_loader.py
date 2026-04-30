import json
import re
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
import time
import requests

import config
from utils.game_schedule_validation import validate_games_against_espn


def _sync_cache_from_github() -> bool:
    """
    Tenta sincronizar o cache do GitHub automaticamente.
    """
    CACHE_FILE = config.DATA_DIR / "cache_stats.json"
    GITHUB_RAW_URL = "https://raw.githubusercontent.com/diegobarpereira/NBA_Stats/main/data/cache_stats.json"
    MAX_CACHE_AGE_HOURS = 24
    
    # Verifica se está no Streamlit Cloud
    is_cloud = os.environ.get("STREAMLIT_SHARING_MODE") is not None
    
    if not is_cloud and not CACHE_FILE.exists():
        return False
    
    if not is_cloud:
        return False
    
    print("Verificando cache do GitHub...")
    
    # Verifica se precisa atualizar
    needs_update = True
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r") as f:
                local_cache = json.load(f)
            
            sample_player = list(local_cache.keys())[0] if local_cache else None
            if sample_player:
                has_home_ppg = "home_ppg" in local_cache[sample_player]
                has_last5 = "last5_game_1_pts" in local_cache[sample_player]
                
                if has_home_ppg and has_last5:
                    needs_update = False
                    print("Cache local já tem dados avançados - usando local")
        except:
            needs_update = True
    
    if not needs_update:
        return False
    
    # Tenta baixar do GitHub
    try:
        for attempt in range(3):
            try:
                response = requests.get(GITHUB_RAW_URL, timeout=30)
                if response.status_code == 200:
                    github_cache = response.json()
                    
                    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                    with open(CACHE_FILE, "w", encoding="utf-8") as f:
                        json.dump(github_cache, f, ensure_ascii=False, indent=2)
                    
                    print(f"Cache sincronizado: {len(github_cache)} jogadores")
                    return True
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    print(f"Erro ao baixar cache: {e}")
    except Exception as e:
        print(f"Cache sync error: {e}")
    
    return False


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


def _names_match(injury_name: str, player_name: str) -> bool:
    n1 = _normalize_name(injury_name)
    n2 = _normalize_name(player_name)
    if n1 == n2:
        return True
    if n1 in n2 or n2 in n1:
        return True
    return False


_STATUS_MAP = {
    "out": "OUT",
    "doubtful": "DOUBTFUL",
    "questionable": "QUESTIONABLE",
    "probable": "PROBABLE",
    "active": "ACTIVE",
    "suspended": "OUT",
}


def _normalize_status(raw: str) -> str:
    return _STATUS_MAP.get(raw.lower().strip(), "OUT")


class DataLoader:
    def __init__(self):
        self.teams_data: List[Dict] = []
        self.games_data: List[Dict] = []
        self.injuries_data: List[Dict] = []
        self.stats_cache: Dict[str, Dict] = {}
        self._injury_index: Dict[str, Dict] = {}
        
        _sync_cache_from_github()
    
    def load_all(self) -> None:
        self.load_teams()
        self.load_games()
        self.load_injuries()
        self.load_stats_cache()

    def load_teams(self) -> List[Dict]:
        path = config.DATA_FILES["teams"]
        if not path.exists():
            raise FileNotFoundError(f"Arquivo nao encontrado: {path}")
        with open(path, "r", encoding="utf-8") as f:
            self.teams_data = json.load(f)
        return self.teams_data

    def load_games(self) -> List[Dict]:
        path = config.DATA_FILES["games"]
        if not path.exists():
            raise FileNotFoundError(f"Arquivo nao encontrado: {path}")
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            self.games_data = raw
        else:
            self.games_data = raw.get("jogos", [])
        self.games_data, _ = validate_games_against_espn(self.games_data)
        self._validate_games()
        return self.games_data

    def load_injuries(self) -> List[Dict]:
        path = config.DATA_FILES["injuries"]
        if not path.exists():
            raise FileNotFoundError(f"Arquivo nao encontrado: {path}")
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self.injuries_data = self._parse_injuries(raw)
        self._build_injury_index()
        return self.injuries_data

    def _parse_injuries(self, raw) -> List[Dict]:
        entries = []
        if isinstance(raw, list):
            data = raw
        elif isinstance(raw, dict):
            data = raw.get("relatorio_lesoes", {}).get("times", [])
        else:
            return []

        if isinstance(data, list) and data and isinstance(data[0], dict) and "times" in data[0]:
            data = data[0]["times"]

        for team_entry in data:
            team_name = team_entry.get("team", "")
            jogadores = team_entry.get("jogadores", [])
            for j in jogadores:
                entries.append({
                    "player": j["nome"],
                    "team": team_name,
                    "status": _normalize_status(j["status"]),
                })
        return entries

    def _build_injury_index(self) -> None:
        self._injury_index = {}
        for entry in self.injuries_data:
            norm = _normalize_name(entry["player"])
            if norm not in self._injury_index:
                self._injury_index[norm] = entry

    def load_stats_cache(self) -> Dict[str, Dict]:
        path = config.CACHE_FILE
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                self.stats_cache = json.load(f)
        return self.stats_cache

    def save_stats_cache(self, stats: Dict[str, Dict]) -> None:
        with open(config.CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
        self.stats_cache = stats

    def _validate_games(self) -> None:
        required = ["id", "home", "away", "datetime"]
        for game in self.games_data:
            for field in required:
                if field not in game:
                    raise ValueError(f"Jogo faltando '{field}': {game}")

    def get_players_by_team(self, team_name: str) -> List[Dict]:
        for team in self.teams_data:
            if team["team"] == team_name:
                return team["players"]
        return []

    def get_player_stats(self, player_name: str) -> Optional[Dict]:
        return self.stats_cache.get(player_name)

    def _find_injury(self, player_name: str) -> Optional[Dict]:
        norm = _normalize_name(player_name)
        if norm in self._injury_index:
            return self._injury_index[norm]
        for key, entry in self._injury_index.items():
            if _names_match(player_name, entry["player"]):
                return entry
        return None

    def get_injured_players(self) -> Dict[str, str]:
        injured = {}
        for entry in self.injuries_data:
            if entry["status"] in ["OUT", "DOUBTFUL"]:
                injured[entry["player"]] = entry["status"]
        return injured

    def get_questionable_players(self) -> Dict[str, str]:
        questionable = {}
        for entry in self.injuries_data:
            if entry["status"] == "QUESTIONABLE":
                questionable[entry["player"]] = entry["status"]
        return questionable

    def get_all_players_from_games(self) -> List[Dict]:
        players = []
        seen = set()
        for game in self.games_data:
            home = self.get_players_by_team(game["home"])
            away = self.get_players_by_team(game["away"])
            for p in home + away:
                if p["name"] not in seen:
                    seen.add(p["name"])
                    players.append(p)
        return players

    def print_summary(self) -> None:
        print("\n" + "=" * 50)
        print("RESUMO DOS DADOS CARREGADOS")
        print("=" * 50)
        print(f"Times carregados: {len(self.teams_data)}")
        print(f"Jogos do dia: {len(self.games_data)}")
        print(f"Relatorios de lesao: {len(self.injuries_data)}")
        print(f"Jogadores em cache: {len(self.stats_cache)}")

        injured = self.get_injured_players()
        questionable = self.get_questionable_players()
        if injured:
            print(f"\nJogadores OUT/DOUBTFUL ({len(injured)}):")
            for name, status in injured.items():
                print(f"  - {name} ({status})")
        if questionable:
            print(f"\nJogadores QUESTIONABLE ({len(questionable)}):")
            for name, status in questionable.items():
                print(f"  - {name} ({status})")

        print("\nJogos do dia:")
        for game in self.games_data:
            dt = datetime.fromisoformat(game["datetime"])
            print(f"  {dt.strftime('%d/%m %H:%M')} - {game['away']} @ {game['home']}")

        print("=" * 50 + "\n")
