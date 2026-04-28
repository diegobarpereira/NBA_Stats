import time
import re
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup, FeatureNotFound

import config


class ESPNScraper:
    TEAM_URL = "https://www.espn.com/nba/team/stats/_/name/{abbr}/season/{season}/type/2"
    PLAYER_LOG_URL = "https://www.espn.com/nba/player/gamelog/_/id/{pid}/type/nba"

    TEAM_ABBR_ALIASES = {
        "SA": "SAS",
        "GS": "GSW",
        "NO": "NOP",
        "NY": "NYK",
        "UTH": "UTA",
        "WSH": "WAS",
    }

    def _get_season_year(self):
        current_month = datetime.now().month
        current_year = datetime.now().year
        return current_year if current_month >= 10 else current_year
    
    def _get_current_season_year(self):
        return self._get_season_year()

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.espn.com/nba/",
        })
        self.delay = config.SCRAPING_CONFIG["request_delay_seconds"]

    def _get(self, url: str, timeout: int = 20, attempts: int = 3) -> Optional[requests.Response]:
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                time.sleep(self.delay)
                response = self.session.get(url, timeout=timeout)
                if response.status_code == 200:
                    return response
                if response.status_code in {403, 408, 429, 500, 502, 503, 504}:
                    print(f"ESPN retry {attempt}/{attempts} for {url} -> HTTP {response.status_code}")
                    last_error = RuntimeError(f"HTTP {response.status_code}")
                    time.sleep(min(6, attempt * 2))
                    continue
                print(f"ESPN request failed for {url} -> HTTP {response.status_code}")
                return response
            except requests.RequestException as exc:
                last_error = exc
                print(f"ESPN request error {attempt}/{attempts} for {url}: {exc}")
                time.sleep(min(6, attempt * 2))

        if last_error:
            print(f"ESPN request exhausted retries for {url}: {last_error}")
        return None

    def _parse_html(self, html: str) -> BeautifulSoup:
        try:
            return BeautifulSoup(html, "lxml")
        except FeatureNotFound:
            return BeautifulSoup(html, "html.parser")

    def _extract_opponent_abbr(self, opponent_raw: str) -> str:
        cleaned = str(opponent_raw or "").upper().replace("VS", "").replace("@", "").strip()
        match = re.search(r"\b([A-Z]{2,3})\b", cleaned)
        if not match:
            return ""
        return self.TEAM_ABBR_ALIASES.get(match.group(1), match.group(1))

    def _parse_minutes_value(self, minutes_raw: str) -> float:
        text = str(minutes_raw or "").strip()
        if not text:
            return 0.0
        if text.isdigit():
            return float(text)
        if ":" in text:
            parts = text.split(":", 1)
            if parts[0].isdigit() and parts[1].isdigit():
                return float(parts[0]) + (float(parts[1]) / 60.0)
        return 0.0

    def _safe_stat_float(self, cells, idx: int) -> float:
        try:
            raw = cells[idx].get_text(strip=True)
        except IndexError:
            return 0.0
        return float(raw) if raw.replace(".", "").isdigit() else 0.0

    def _parse_game_date(self, date_text: str) -> Optional[date]:
        match = re.search(r"(\d{1,2})/(\d{1,2})", str(date_text or ""))
        if not match:
            return None

        month = int(match.group(1))
        day = int(match.group(2))
        season_year = self._get_season_year()
        game_year = season_year - 1 if month >= 10 else season_year

        try:
            return date(game_year, month, day)
        except ValueError:
            return None

    def _fetch_player_game_log_rows(self, pid: str) -> List[Dict]:
        if not pid:
            return []

        season_year = self._get_season_year()
        url = f"https://www.espn.com/nba/player/gamelog/_/id/{pid}/season/{season_year}"
        resp = self._get(url, timeout=20)
        if resp is None or resp.status_code != 200:
            return []

        soup = self._parse_html(resp.text)
        rows_out = []

        for table in soup.find_all("table"):
            table_text = table.get_text()
            if "DateOPPResultMIN" not in table_text:
                continue
            if "Postseason" in table_text or "Preseason" in table_text:
                continue

            for row in table.find_all("tr"):
                cells = row.find_all(["td"])
                if len(cells) < 4:
                    continue

                date_text = cells[0].get_text(strip=True)
                if not re.search(r"\d+/\d+", date_text):
                    continue

                opponent_raw = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                result_raw = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                minutes_raw = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                minutes = self._parse_minutes_value(minutes_raw)
                played = minutes > 0

                fg3 = 0.0
                if len(cells) > 6:
                    fg3_raw = cells[6].get_text(strip=True)
                    if fg3_raw and "-" in fg3_raw:
                        try:
                            fg3 = float(fg3_raw.split("-")[0])
                        except ValueError:
                            fg3 = 0.0

                rows_out.append({
                    "date": date_text,
                    "game_date": self._parse_game_date(date_text),
                    "opponent_raw": opponent_raw,
                    "opponent_abbr": self._extract_opponent_abbr(opponent_raw),
                    "result_raw": result_raw,
                    "minutes_raw": minutes_raw,
                    "minutes": minutes,
                    "played": played,
                    "is_home": "vs" in opponent_raw.lower() or "@" not in opponent_raw,
                    "pts": self._safe_stat_float(cells, 16) if played else 0.0,
                    "reb": self._safe_stat_float(cells, 10) if played else 0.0,
                    "ast": self._safe_stat_float(cells, 11) if played else 0.0,
                    "fg3": fg3 if played else 0.0,
                })

        return rows_out

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
        season = self._get_current_season_year()
        url = f"https://www.espn.com/nba/team/stats/_/name/{self._abbr_to_espn(team_abbr)}/season/{season}/seasontype/2"
        try:
            resp = self._get(url, timeout=15)
            if resp is None or resp.status_code != 200:
                return None

            soup = self._parse_html(resp.text)
            tables = soup.find_all("table")
            if len(tables) < 4:
                page_title = soup.title.get_text(strip=True) if soup.title else "sem titulo"
                print(f"ESPN team page unexpected structure for {team_abbr}: {len(tables)} tables | {page_title}")
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

                gp_val = int(get_val(stat_cells, 0))
                if gp_val == 0 or gp_val == 1:
                    gp_val = 30
                results.append({
                    "name": name,
                    "position": position or "G",
                    "pid": pid,
                    "gp": gp_val,
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
            rows = self._fetch_player_game_log_rows(pid)
            all_games = [
                {
                    "pts": row["pts"],
                    "reb": row["reb"],
                    "ast": row["ast"],
                    "fg3": row["fg3"],
                    "min": row["minutes"],
                    "is_home": row["is_home"],
                }
                for row in rows
                if row.get("played")
            ]

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

            all_games = all_games[::-1]
            last5 = all_games[-5:]

            def avg(key):
                vals = [g[key] for g in last5]
                return round(sum(vals) / len(vals), 1) if vals else 0.0

            home_games = [g for g in last5 if g.get("is_home", True)]
            away_games = [g for g in last5 if not g.get("is_home", True)]

            minute_values = [g["min"] for g in last5 if g.get("min", 0) > 0]

            def minute_window_avg(values, take_last: bool) -> float:
                if not values:
                    return 0.0
                if len(values) == 1:
                    return round(values[0], 1)
                window = values[-2:] if take_last else values[:2]
                return round(sum(window) / len(window), 1)

            def minute_volatility(values) -> float:
                if not values:
                    return 0.0
                avg_minutes = sum(values) / len(values)
                if avg_minutes <= 0:
                    return 0.0
                spread = sum(abs(value - avg_minutes) for value in values) / len(values)
                return round(spread / avg_minutes, 3)

            early_minutes_avg = minute_window_avg(minute_values, take_last=False)
            recent_minutes_avg = minute_window_avg(minute_values, take_last=True)
            minute_trend = round(recent_minutes_avg - early_minutes_avg, 1) if minute_values else 0.0

            def home_avg(key):
                vals = [g[key] for g in home_games]
                return round(sum(vals) / len(vals), 1) if vals else 0.0

            def away_avg(key):
                vals = [g[key] for g in away_games]
                return round(sum(vals) / len(vals), 1) if vals else 0.0

            result = {
                "ppg": avg("pts"),
                "rpg": avg("reb"),
                "apg": avg("ast"),
                "tpg": avg("fg3"),
                "mpg": avg("min"),
                "games": len(last5),
                "home_games": len(home_games),
                "away_games": len(away_games),
                "home_ppg": home_avg("pts"),
                "away_ppg": away_avg("pts"),
                "home_reb": home_avg("reb"),
                "away_reb": away_avg("reb"),
                "home_ast": home_avg("ast"),
                "away_ast": away_avg("ast"),
                "early_minutes_avg": early_minutes_avg,
                "recent_minutes_avg": recent_minutes_avg,
                "minute_trend": minute_trend,
                "minute_volatility": minute_volatility(minute_values),
            }

            # Add individual game values for trend/variance analysis
            for i, g in enumerate(last5):
                result[f"game_{i+1}_pts"] = g["pts"]
                result[f"game_{i+1}_reb"] = g["reb"]
                result[f"game_{i+1}_ast"] = g["ast"]
                result[f"game_{i+1}_fg3"] = g["fg3"]
                result[f"game_{i+1}_min"] = g["min"]
                result[f"game_{i+1}_home"] = g.get("is_home", True)

            return result
        except Exception as e:
            print(f"Error in get_player_last5: {e}")
            return None

    def get_player_game_against_opponent(
        self,
        pid: str,
        player_name: str,
        opponent_abbr: str,
        reference_date: Optional[date] = None,
        max_age_days: int = 5,
    ) -> Optional[Dict]:
        if not pid or not opponent_abbr:
            return None

        try:
            rows = self._fetch_player_game_log_rows(pid)
            if not rows:
                return None

            opponent_abbr = self.TEAM_ABBR_ALIASES.get(opponent_abbr.upper(), opponent_abbr.upper())
            matching_rows = [row for row in rows if row.get("opponent_abbr") == opponent_abbr]
            if reference_date is not None:
                recent_rows = []
                for row in matching_rows:
                    game_date = row.get("game_date")
                    if game_date is None:
                        continue
                    age_days = (reference_date - game_date).days
                    if 0 <= age_days <= max_age_days:
                        recent_rows.append(row)
                if recent_rows:
                    matching_rows = recent_rows
                else:
                    matching_rows = []

            target_row = matching_rows[0] if matching_rows else None

            if target_row is None:
                return {
                    "status": "void",
                    "reason": "no_recent_game_for_opponent",
                    "opponent": opponent_abbr,
                    "games": 0,
                }

            if not target_row.get("played"):
                return {
                    "status": "void",
                    "reason": target_row.get("minutes_raw") or target_row.get("result_raw") or "did_not_play",
                    "opponent": opponent_abbr,
                    "date": target_row.get("date"),
                    "games": 1,
                }

            return {
                "status": "played",
                "ppg": target_row.get("pts", 0.0),
                "rpg": target_row.get("reb", 0.0),
                "apg": target_row.get("ast", 0.0),
                "tpg": target_row.get("fg3", 0.0),
                "mpg": target_row.get("minutes", 0.0),
                "games": 1,
                "date": target_row.get("date"),
                "opponent": opponent_abbr,
            }
        except Exception as e:
            print(f"Error in get_player_game_against_opponent: {e}")
            return None

            soup = self._parse_html(resp.text)

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
            result["games_last5"] = last5["games"] if last5.get("games", 0) > 1 else 5
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
