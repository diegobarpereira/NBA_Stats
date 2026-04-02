import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

import config


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
