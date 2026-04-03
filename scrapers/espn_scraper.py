import time
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

import config


class ESPNScraper:
    TEAM_URL = "https://www.espn.com/nba/team/stats/_/name/{abbr}/view/expanded"
    PLAYER_LOG_URL = "https://www.espn.com/nba/player/gamelog/_/id/{pid}/type/nba"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.delay = config.SCRAPING_CONFIG["request_delay_seconds"]

    def _abbr_to_espn(self, team_abbr: str) -> str:
        REVERSE_MAP = {
            "ATL": "atl", "BOS": "bos", "BKN": "bkn", "CHA": "cha", "CHI": "chi",
            "CLE": "cle", "DAL": "dal", "DEN": "den", "DET": "det", "GSW": "gs",
            "HOU": "hou", "IND": "ind", "LAC": "lac", "LAL": "lal", "MEM": "mem",
            "MIA": "mia", "MIL": "mil", "MIN": "min", "NOP": "no", "NYK": "ny",
            "OKC": "okc", "ORL": "orl", "PHI": "phi", "PHX": "phx", "POR": "por",
            "SAC": "sac", "SAS": "sa", "TOR": "tor", "UTA": "uth", "WAS": "wsh",
            "Los Angeles Clippers": "lac", "Los Angeles Lakers": "lal",
            "New York Knicks": "ny", "San Antonio Spurs": "sa",
            "New Orleans Pelicans": "no", "Golden State Warriors": "gs",
        }
        return REVERSE_MAP.get(team_abbr, team_abbr.lower())

    def get_team_stats(self, team_abbr: str) -> Optional[List[Dict]]:
        url = self.TEAM_URL.format(abbr=self._abbr_to_espn(team_abbr))
        try:
            time.sleep(self.delay)
            resp = self.session.get(url, timeout=15)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "lxml")
            tables = soup.find_all("table")
            if len(tables) < 4:
                return None

            name_table = tables[0]
            stats_table = tables[1]
            shooting_table = tables[3]

            name_rows = name_table.find_all("tr")
            stat_rows = stats_table.find_all("tr")
            shoot_rows = shooting_table.find_all("tr")

            if len(name_rows) < 2 or len(stat_rows) < 2:
                return None

            results = []
            num_players = min(len(name_rows), len(stat_rows), len(shoot_rows))

            for i in range(1, num_players):
                name_link = name_rows[i].find("a")
                if not name_link:
                    continue

                href = name_link.get("href", "")

                name_td = name_rows[i].find(["td", "th"])
                name_raw = name_td.get_text(strip=True) if name_td else name_link.get_text(strip=True)

                position = ""
                name = name_raw
                pos_match = re.search(r"(G|F|C)(?:-(G|F|C))?\*?\s*$", name_raw)
                if pos_match:
                    full = pos_match.group(0).strip().rstrip("*")
                    position = full
                    name = re.sub(r"(G|F|C)(?:-(G|F|C))?\*?\s*$", "", name_raw).strip()
                else:
                    name = name_raw

                pid_match = re.search(r"/id/(\d+)/", href)
                pid = pid_match.group(1) if pid_match else ""

                stat_cells = stat_rows[i].find_all(["td", "th"])
                shoot_cells = shoot_rows[i].find_all(["td", "th"])

                def get_val(cells, idx, default=0.0):
                    try:
                        text = cells[idx].get_text(strip=True) if idx < len(cells) else ""
                        return float(text) if text and text != "-" else default
                    except (ValueError, IndexError):
                        return default

                def get_str(cells, idx, default=""):
                    try:
                        text = cells[idx].get_text(strip=True) if idx < len(cells) else ""
                        return text if text else default
                    except IndexError:
                        return default

                pts = get_val(stat_cells, 3)
                reb = get_val(stat_cells, 6)
                ast = get_val(stat_cells, 7)
                fg3 = get_val(shoot_cells, 3)

                results.append({
                    "name": name,
                    "position": position or "G",
                    "pid": pid,
                    "gp": int(get_val(stat_cells, 0)),
                    "ppg": round(pts, 1),
                    "rpg": round(reb, 1),
                    "apg": round(ast, 1),
                    "tpg": round(fg3, 1),
                })

            return results
        except Exception as e:
            print(f"    Erro team {team_abbr}: {e}")
            return None

    def get_player_last5(self, pid: str, player_name: str, last_game_only: bool = False) -> Optional[Dict]:
        if not pid:
            return None

        try:
            current_month = datetime.now().month
            season_year = 2026 if current_month >= 10 or current_month <= 6 else 2025
            url = f"https://www.espn.com/nba/player/gamelog/_/id/{pid}/season/{season_year}"
            resp = self.session.get(url, timeout=20)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "lxml")

            all_games = []
            for table in soup.find_all("table"):
                table_text = table.get_text()
                if "DateOPPResultMIN" not in table_text:
                    continue
                if "Postseason" in table_text or "Preseason" in table_text or "Regular Season Stats" in table_text:
                    continue

                for row in table.find_all("tr"):
                    cells = row.find_all(["td"])
                    if len(cells) < 15:
                        continue
                    
                    date_text = cells[0].get_text(strip=True)
                    if not re.search(r'\d+/\d+', date_text):
                        continue

                    try:
                        pts_raw = cells[16].get_text(strip=True)
                        reb_raw = cells[10].get_text(strip=True)
                        ast_raw = cells[11].get_text(strip=True)
                        fg3_raw = cells[6].get_text(strip=True) if len(cells) > 6 else ""
                        min_raw = cells[3].get_text(strip=True) if len(cells) > 3 else "0"

                        pts = float(pts_raw) if pts_raw.replace(".", "").isdigit() else 0.0
                        reb = float(reb_raw) if reb_raw.replace(".", "").isdigit() else 0.0
                        ast = float(ast_raw) if ast_raw.replace(".", "").isdigit() else 0.0

                        fg3 = 0.0
                        if fg3_raw and "-" in fg3_raw:
                            try:
                                fg3 = float(fg3_raw.split("-")[0])
                            except ValueError:
                                fg3 = 0.0

                        minutes = 0.0
                        try:
                            minutes = float(min_raw) if min_raw.isdigit() else 0.0
                        except ValueError:
                            minutes = 0.0

                        if minutes > 0:
                            all_games.append({"pts": pts, "reb": reb, "ast": ast, "fg3": fg3, "min": minutes})
                    except (ValueError, IndexError, AttributeError):
                        continue

            if not all_games:
                return None

            if last_game_only:
                g = all_games[0]
                return {
                    "ppg": g["pts"],
                    "rpg": g["reb"],
                    "apg": g["ast"],
                    "tpg": g["fg3"],
                    "mpg": g["min"],
                    "games": 1,
                }

            last5 = all_games[:5]

            def avg(key):
                vals = [g[key] for g in last5]
                return round(sum(vals) / len(vals), 1) if vals else 0.0

            return {
                "ppg": avg("pts"),
                "rpg": avg("reb"),
                "apg": avg("ast"),
                "tpg": avg("fg3"),
                "mpg": avg("min"),
                "games": len(last5),
            }
        except Exception as e:
            print(f"Error in get_player_last5: {e}")
            return None

            soup = BeautifulSoup(resp.text, "lxml")

            table = soup.find("table", {"class": "mod-data"})
            if not table:
                tables = soup.find_all("table")
                table = next((t for t in tables if "PTS" in t.get_text()), None)

            if not table:
                return None

            rows = table.find_all("tr")
            data_rows = [
                r for r in rows
                if r.find("td") and ("player" not in (r.get("class") or []))
            ]

            game_rows = []
            for row in data_rows[:20]:
                cells = row.find_all(["td", "th"])
                if len(cells) < 16:
                    continue
                date_text = cells[0].get_text(strip=True)
                if not date_text or "/" not in date_text:
                    continue
                try:
                    pts = float(cells[16].get_text(strip=True)) if cells[16].get_text(strip=True) else 0
                    reb = float(cells[10].get_text(strip=True)) if cells[10].get_text(strip=True) else 0
                    ast = float(cells[11].get_text(strip=True)) if cells[11].get_text(strip=True) else 0
                    fg3_raw = cells[6].get_text(strip=True) if len(cells) > 6 else ""
                    fg3 = 0.0
                    if fg3_raw and "-" in fg3_raw:
                        fg3 = float(fg3_raw.split("-")[0])
                    elif fg3_raw:
                        try:
                            fg3 = float(fg3_raw)
                        except ValueError:
                            fg3 = 0.0
                    
                    minutes = 0.0
                    if len(cells) > 3:
                        min_raw = cells[3].get_text(strip=True) if cells[3].get_text(strip=True) else "0"
                        try:
                            minutes = float(min_raw)
                        except ValueError:
                            minutes = 0.0
                    
                    game_rows.append({"pts": pts, "reb": reb, "ast": ast, "fg3": fg3, "min": minutes})
                except (ValueError, IndexError):
                    continue

            if not game_rows:
                return None

            last5 = game_rows[:5]

            def avg(key):
                vals = [g[key] for g in last5]
                return round(sum(vals) / len(vals), 1) if vals else 0.0

            return {
                "ppg": avg("pts"),
                "rpg": avg("reb"),
                "apg": avg("ast"),
                "tpg": avg("fg3"),
                "mpg": avg("min"),
                "games": len(last5),
            }
        except Exception as e:
            print(f"Error in get_player_last5: {e}")
            return None

    def get_player_stats(self, player_name: str, team_abbr: str) -> Optional[Dict]:
        team_stats = self.get_team_stats(team_abbr)
        if not team_stats:
            return None

        norm_name = player_name.lower().replace("'", "").replace(".", "")
        best_match = None
        best_score = 0

        for p in team_stats:
            pname = p["name"].lower().replace("'", "").replace(".", "")
            if norm_name == pname:
                best_match = p
                best_score = 100
                break
            if norm_name in pname or pname in norm_name:
                score = min(len(norm_name), len(pname))
                if score > best_score:
                    best_match = p
                    best_score = score

        if not best_match:
            return None

        pid = best_match["pid"]

        last5 = None
        if pid:
            last5 = self.get_player_last5(pid, player_name)

        team_name = config.TEAM_NAME_REVERSE.get(team_abbr, team_abbr)

        position_raw = best_match.get("name", "")
        position = ""
        if "(" in position_raw:
            position = position_raw.split("(")[-1].replace(")", "").strip()
        else:
            position = "G" if team_stats and len(team_stats) > 0 else "G"

        result = {
            "name": player_name,
            "team": team_name,
            "position": position,
            "pid": pid,
            "avgPoints_season": best_match["ppg"],
            "avgRebounds_season": best_match["rpg"],
            "avgAssists_season": best_match["apg"],
            "avg3PT_season": best_match["tpg"],
            "games_season": best_match["gp"],
            "is_starter": True,
            "avgMinutes_last5": 0.0,
        }

        if last5:
            result["avgPoints_last5"] = last5["ppg"]
            result["avgRebounds_last5"] = last5["rpg"]
            result["avgAssists_last5"] = last5["apg"]
            result["avg3PT_last5"] = last5["tpg"]
            result["games_last5"] = last5["games"]
            result["avgMinutes_last5"] = last5.get("mpg", 0.0)
            result["is_starter"] = last5.get("mpg", 0) >= 20.0
        else:
            result["avgPoints_last5"] = result["avgPoints_season"]
            result["avgRebounds_last5"] = result["avgRebounds_season"]
            result["avgAssists_last5"] = result["avgAssists_season"]
            result["avg3PT_last5"] = result["avg3PT_season"]
            result["games_last5"] = 0
            result["avgMinutes_last5"] = 0.0

        return result

    def scrape_all_players_from_games(
        self, games_data: List[Dict], teams_data: List[Dict]
    ) -> Dict[str, Dict]:
        stats = {}

        players_by_team = {}
        for team in teams_data:
            abbr = config.TEAM_NAME_MAPPING.get(team["team"], team["team"])
            players_by_team[abbr] = team["players"]

        teams_needed = set()
        for game in games_data:
            home_abbr = config.TEAM_NAME_MAPPING.get(game["home"], game["home"])
            away_abbr = config.TEAM_NAME_MAPPING.get(game["away"], game["away"])
            teams_needed.add(home_abbr)
            teams_needed.add(away_abbr)

        total = sum(
            len(players_by_team.get(t, [])) for t in teams_needed
        )
        print(f"\nBuscando estatisticas de ~{total} jogadores em {len(teams_needed)} times...")

        team_stats_cache = {}

        for team_abbr in sorted(teams_needed):
            print(f"\n  Carregando time: {team_abbr}")
            for attempt in range(1, 4):
                try:
                    team_ts = self.get_team_stats(team_abbr)
                    if team_ts:
                        team_stats_cache[team_abbr] = team_ts
                        print(f"    OK: {len(team_ts)} jogadores")
                        break
                    print(f"    Tentativa {attempt} falhou, tentando novamente...")
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    print(f"    Timeout/Conexao na tentativa {attempt}: {e}")
                    if attempt < 3:
                        print(f"    Reiniciando...")
                    else:
                        print(f"    Time ignorado apos 3 tentativas.")

        for team_abbr, team_ts in team_stats_cache.items():
            team_name = config.TEAM_NAME_REVERSE.get(team_abbr, team_abbr)
            team_players = players_by_team.get(team_abbr, [])

            for player in team_players:
                name = player["name"]
                if name in stats:
                    continue

                safe_name = name.encode('ascii', 'replace').decode('ascii')
                print(f"    {safe_name}...", end=" ", flush=True)

                player_stats = self._match_player_from_cache(name, team_ts, team_abbr)
                if not player_stats:
                    try:
                        player_stats = self.get_player_stats(name, team_abbr)
                    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                        player_stats = self._match_player_from_cache(name, team_ts, team_abbr)

                if player_stats:
                    stats[name] = player_stats
                    l5 = player_stats.get("games_last5", 0)
                    src = "(L5)" if l5 > 0 else "(S)"
                    print(f"OK {src} PTS:{player_stats.get('avgPoints_season', '?')}")
                else:
                    print("SEM DADOS")

            for espn_p in team_ts:
                pname = espn_p["name"]
                if pname in stats:
                    continue
                if pname in players_by_team.get(team_abbr, []):
                    continue
                norm_espn = pname.lower().replace("'", "").replace(".", "")
                found_in_roster = any(
                    norm_espn == n.lower().replace("'", "").replace(".", "")
                    for n in players_by_team.get(team_abbr, [])
                )
                if found_in_roster:
                    continue
                print(f"    {pname}...", end=" ", flush=True)
                ps = self._match_player_from_cache(pname, team_ts, team_abbr)
                if ps:
                    stats[pname] = ps
                    print(f"OK (ESPN) PTS:{ps.get('avgPoints_season', '?')}")

        print(f"\nEstatisticas obtidas: {len(stats)}/{total}")
        return stats

    def _match_player_from_cache(
        self, player_name: str, team_stats: List[Dict], team_abbr: str = ""
    ) -> Optional[Dict]:
        if not team_stats:
            return None

        norm = player_name.lower().replace("'", "").replace(".", "")
        best = None
        best_score = 0

        for p in team_stats:
            pn = p["name"].lower().replace("'", "").replace(".", "")
            score = 0
            if norm == pn:
                score = 100
            elif norm in pn or pn in norm:
                score = min(len(norm), len(pn))
            if score > best_score:
                best = p
                best_score = score

        if not best or best_score < 3:
            return None

        pid = best["pid"]
        team_name = config.TEAM_NAME_REVERSE.get(team_abbr, team_abbr)

        position = best.get("position", "G")

        ppg = best.get("ppg", 0)
        is_starter = ppg >= 10.0

        result = {
            "name": player_name,
            "team": team_name,
            "position": position,
            "pid": best["pid"],
            "avgPoints_season": ppg,
            "avgRebounds_season": best["rpg"],
            "avgAssists_season": best["apg"],
            "avg3PT_season": best["tpg"],
            "games_season": best["gp"],
            "avgPoints_last5": best["ppg"],
            "avgRebounds_last5": best["rpg"],
            "avgAssists_last5": best["apg"],
            "avg3PT_last5": best["tpg"],
            "games_last5": best["gp"],
            "is_starter": is_starter,
            "avgMinutes_last5": 0.0,
        }
        return result
