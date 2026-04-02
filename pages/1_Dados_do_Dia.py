import streamlit as st
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

import config


def _init_session():
    if "loader" not in st.session_state:
        from utils.data_loader import DataLoader
        st.session_state.loader = DataLoader()
        try:
            st.session_state.loader.load_all()
        except FileNotFoundError:
            pass
    if "stats" not in st.session_state:
        st.session_state.stats = st.session_state.loader.stats_cache.copy()
        st.session_state.stats_loaded = bool(st.session_state.stats)
    if "matchup_data" not in st.session_state:
        st.session_state.matchup_data = None
    if "props_generated" not in st.session_state:
        st.session_state.props_generated = False
    if "bilhetes_generated" not in st.session_state:
        st.session_state.bilhetes_generated = False


_init_session()

st.title("📋 Dados do Dia")

col_fetch, col_date = st.columns([2, 1])
with col_fetch:
    st.markdown("#### 🤖 Auto-fetch GameRead")
with col_date:
    today = datetime.now().strftime("%Y-%m-%d")
    auto_date = st.text_input("Data", value=today)

if st.button("📥 Buscar do GameRead", type="primary"):
    with st.spinner("Buscando..."):
        from scrapers.gameread_scraper import fetch_games_from_gameread, fetch_injuries_from_gameread
        import json
        try:
            games = fetch_games_from_gameread(auto_date)
            with open(config.DATA_FILES["games"], "w", encoding="utf-8") as f:
                json.dump(games, f, indent=2, ensure_ascii=False)
            
            injuries = fetch_injuries_from_gameread(auto_date)
            with open(config.DATA_FILES["injuries"], "w", encoding="utf-8") as f:
                json.dump(injuries, f, indent=2, ensure_ascii=False)
            
            st.session_state.loader.load_all()
            st.session_state.props_generated = False
            st.session_state.bilhetes_generated = False
            st.rerun()
        except Exception as e:
            st.error(f"Erro: {e}")

st.markdown("---")

tab1, tab2, tab3 = st.tabs(["📝 Texto Plano", "🏀 Jogos do Dia", "🏥 Relatório de Lesões"])


def parse_games_text(raw: str) -> list[dict]:
    games = []
    lines = raw.strip().split("\n")
    date_hint = None

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue

        date_match = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", line)
        if date_match and "vs" not in line.lower() and "x" not in line.lower() and "@" not in line:
            date_hint = date_match.group(1)
            continue

        parts = re.split(r"\s+(?:vs|v|x|@)\s+", line, flags=re.IGNORECASE)
        if len(parts) < 2:
            continue

        t1 = parts[0].strip()
        rest = parts[1].strip()

        time_match = re.search(r"(\d{1,2}:\d{2})", rest)
        if time_match:
            game_time = time_match.group(1)
            t2 = re.sub(r"\s*\d{1,2}:\d{2}\s*$", "", rest).strip()
        else:
            game_time = None
            t2 = rest

        if "@" in line.lower():
            home_name, away_name = t2, t1
        else:
            home_name, away_name = t1, t2

        team1_full = _resolve_team(home_name)
        team2_full = _resolve_team(away_name)

        if not team1_full or not team2_full:
            continue

        game_date = date_hint or datetime.now().strftime("%Y-%m-%d")
        if "/" in game_date:
            parts = game_date.replace("-", "/").split("/")
            month, day = parts[0], parts[1]
            year = parts[2] if len(parts) > 2 else datetime.now().strftime("%Y")
            if len(year) == 2:
                year = "20" + year
            game_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"

        game_id = f"{team2_full.split()[-1]}vs{team1_full.split()[-1]}_{game_date[:10]}"

        if game_time:
            h, m = game_time.split(":")
            dt_obj = datetime.fromisoformat(game_date[:10]) + timedelta(hours=int(h), minutes=int(m))
            game_datetime = dt_obj.isoformat()
        else:
            game_datetime = f"{game_date[:10]}T21:00:00"

        games.append({
                "id": game_id,
                "home": team1_full,
                "away": team2_full,
                "datetime": game_datetime,
            })

    return games


def parse_injuries_text(raw: str) -> dict:
    by_team = {}
    current_team = None
    current_abbr = None
    lines = raw.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue

        team_header_brackets = re.match(r"\[(?P<abbr>[A-Z]{2,3})\](?:\s+(?P<name>.+))?", line, re.IGNORECASE)
        if team_header_brackets and (team_header_brackets.group("name") or team_header_brackets.group("abbr")):
            abbr = (team_header_brackets.group("abbr") or "").upper()
            name = team_header_brackets.group("name")
            if name or abbr:
                current_team = name.strip() if name else _abbr_to_team_name(abbr)
                current_abbr = abbr or _team_name_to_abbr(current_team)
                if current_team and current_abbr and current_team not in by_team:
                    by_team[current_team] = {"abbr": current_abbr, "team": current_team, "jogadores": []}
            continue

        team_header_colon = re.match(r"^(?P<abbr>[A-Z]{2,3})\s*:\s*(?P<name>.*)$", line, re.IGNORECASE)
        if team_header_colon:
            abbr = (team_header_colon.group("abbr") or "").upper()
            name = team_header_colon.group("name")
            if abbr:
                current_team = name.strip() if name.strip() else _abbr_to_team_name(abbr)
                current_abbr = abbr
                if current_team and current_abbr and current_team not in by_team:
                    by_team[current_team] = {"abbr": current_abbr, "team": current_team, "jogadores": []}
            continue

        injury_line = re.match(
            r"(?P<player>[A-Z][A-Za-z'\-À-ÿ]+(?:\s+[A-Za-z'\-À-ÿ]+)*)"
            r"(?:\s*[-–:]\s*)"
            r"(?P<status>.+)",
            line,
        )
        if injury_line and current_team:
            player = injury_line.group("player").strip()
            status_raw = injury_line.group("status").strip().upper()
            status = _normalize_status(status_raw)
            by_team[current_team]["jogadores"].append({"nome": player, "status": status})
        elif current_team:
            status = _normalize_status(line)
            if status in ("OUT", "DOUBTFUL", "QUESTIONABLE", "PROBABLE", "ACTIVE"):
                parts = line.split()
                if parts:
                    player = " ".join(parts[:-1]).strip()
                    if player:
                        by_team[current_team]["jogadores"].append({"nome": player, "status": status})

    return {
        "relatorio_lesoes": {
            "data": datetime.now().strftime("%Y-%m-%d"),
            "times": list(by_team.values()),
        }
    }


def _normalize_status(s: str) -> str:
    s = s.upper().strip()
    if any(k in s for k in ["OUT", "INATIVO", "SUSPENSO"]):
        return "OUT"
    if "DOUBT" in s:
        return "DOUBTFUL"
    if "QUESTION" in s or "DUVIDA" in s:
        return "QUESTIONABLE"
    if "PROBABLE" in s or "PROVAVEL" in s or "PROB" in s:
        return "PROBABLE"
    if "ACTIVE" in s or "ATIVO" in s:
        return "ACTIVE"
    return "OUT"


_TEAM_KEYWORDS = {
    "ATLANTA": "Atlanta Hawks", "HAWKS": "Atlanta Hawks", "ATL": "Atlanta Hawks",
    "BOSTON": "Boston Celtics", "CELTICS": "Boston Celtics", "BOS": "Boston Celtics",
    "BROOKLYN": "Brooklyn Nets", "NETS": "Brooklyn Nets", "BKN": "Brooklyn Nets",
    "CHARLOTTE": "Charlotte Hornets", "HORNETS": "Charlotte Hornets", "CHA": "Charlotte Hornets",
    "CHICAGO": "Chicago Bulls", "BULLS": "Chicago Bulls", "CHI": "Chicago Bulls",
    "CLEVELAND": "Cleveland Cavaliers", "CAVALIERS": "Cleveland Cavaliers", "CLE": "Cleveland Cavaliers",
    "DALLAS": "Dallas Mavericks", "MAVERICKS": "Dallas Mavericks", "DAL": "Dallas Mavericks",
    "DENVER": "Denver Nuggets", "NUGGETS": "Denver Nuggets", "DEN": "Denver Nuggets",
    "DETROIT": "Detroit Pistons", "PISTONS": "Detroit Pistons", "DET": "Detroit Pistons",
    "GOLDEN STATE": "Golden State Warriors", "WARRIORS": "Golden State Warriors", "GSW": "Golden State Warriors",
    "G.S.W.": "Golden State Warriors",
    "HOUSTON": "Houston Rockets", "ROCKETS": "Houston Rockets", "HOU": "Houston Rockets",
    "INDIANA": "Indiana Pacers", "PACERS": "Indiana Pacers", "IND": "Indiana Pacers",
    "L.A. CLIPPERS": "Los Angeles Clippers", "L.A. CLIPPERS": "Los Angeles Clippers",
    "LA CLIPPERS": "Los Angeles Clippers", "LAC": "Los Angeles Clippers",
    "CLIPPERS": "Los Angeles Clippers",
    "L.A. LAKERS": "Los Angeles Lakers", "L.A. LAKERS": "Los Angeles Lakers",
    "LA LAKERS": "Los Angeles Lakers", "LAL": "Los Angeles Lakers",
    "LAKERS": "Los Angeles Lakers",
    "MEMPHIS": "Memphis Grizzlies", "GRIZZLIES": "Memphis Grizzlies", "MEM": "Memphis Grizzlies",
    "MIAMI": "Miami Heat", "HEAT": "Miami Heat", "MIA": "Miami Heat",
    "MILWAUKEE": "Milwaukee Bucks", "BUCKS": "Milwaukee Bucks", "MIL": "Milwaukee Bucks",
    "MINNESOTA": "Minnesota Timberwolves", "TIMBERWOLVES": "Minnesota Timberwolves",
    "MIN": "Minnesota Timberwolves", "WOLVES": "Minnesota Timberwolves",
    "NEW ORLEANS": "New Orleans Pelicans", "NOP": "New Orleans Pelicans",
    "N.O.P.": "New Orleans Pelicans",
    "PELICANS": "New Orleans Pelicans", "PELS": "New Orleans Pelicans",
    "NEW YORK": "New York Knicks", "KNICKS": "New York Knicks", "NYK": "New York Knicks", "NY KNICKS": "New York Knicks", "NY": "New York Knicks",
    "OKLAHOMA CITY": "Oklahoma City Thunder", "THUNDER": "Oklahoma City Thunder", "OKC": "Oklahoma City Thunder",
    "ORLANDO": "Orlando Magic", "MAGIC": "Orlando Magic", "ORL": "Orlando Magic",
    "PHILADELPHIA": "Philadelphia 76ers", "76ERS": "Philadelphia 76ers", "PHI": "Philadelphia 76ers",
    "PHOENIX": "Phoenix Suns", "SUNS": "Phoenix Suns", "PHX": "Phoenix Suns",
    "PORTLAND": "Portland Trail Blazers", "BLAZERS": "Portland Trail Blazers", "POR": "Portland Trail Blazers",
    "SACRAMENTO": "Sacramento Kings", "KINGS": "Sacramento Kings", "SAC": "Sacramento Kings",
    "SAN ANTONIO": "San Antonio Spurs", "SPURS": "San Antonio Spurs", "SAS": "San Antonio Spurs",
    "TORONTO": "Toronto Raptors", "RAPTORS": "Toronto Raptors", "TOR": "Toronto Raptors",
    "UTAH": "Utah Jazz", "JAZZ": "Utah Jazz", "UTA": "Utah Jazz",
    "WASHINGTON": "Washington Wizards", "WIZARDS": "Washington Wizards", "WAS": "Washington Wizards",
}


def _resolve_team(name: str) -> str:
    name_clean = name.strip().upper()
    if name_clean in _TEAM_KEYWORDS:
        return _TEAM_KEYWORDS[name_clean]
    for kw, full in _TEAM_KEYWORDS.items():
        if kw in name_clean or name_clean in kw:
            return full
    return name.strip()


def _abbr_to_team_name(abbr: str) -> str:
    abbr = abbr.upper()
    for kw, full in _TEAM_KEYWORDS.items():
        if kw == abbr:
            return full
    return abbr


def _team_name_to_abbr(name: str) -> str:
    name_upper = name.strip().upper()
    if name_upper in _TEAM_KEYWORDS:
        return _TEAM_KEYWORDS[name_upper]
    for kw, full in _TEAM_KEYWORDS.items():
        if kw in name_upper:
            return full
    return name.strip()


def save_games(games: list):
    import json
    with open(config.DATA_FILES["games"], "w", encoding="utf-8") as f:
        json.dump(games, f, indent=2, ensure_ascii=False)
    st.session_state.loader.games_data = games
    st.session_state.props_generated = False
    st.session_state.bilhetes_generated = False


def save_injuries(injuries: dict):
    import json
    with open(config.DATA_FILES["injuries"], "w", encoding="utf-8") as f:
        json.dump(injuries, f, indent=2, ensure_ascii=False)
    st.session_state.loader.injuries_data = st.session_state.loader._parse_injuries(injuries)
    st.session_state.loader._build_injury_index()
    st.session_state.props_generated = False
    st.session_state.bilhetes_generated = False


with tab1:
    st.markdown("#### 📝 Entrada de Texto Plano")
    st.caption("Cole os jogos e lesões no formato livre abaixo — o sistema detecta automaticamente.")

    col_games, col_injuries = st.columns(2)

    with col_games:
        st.markdown("**🏀 Jogos do Dia**")
        st.caption("Formato: `Time vs Time 21:00` ou `Time x Time`")
        default_games = ""
        if st.session_state.loader.games_data:
            for g in st.session_state.loader.games_data:
                try:
                    dt = datetime.fromisoformat(g["datetime"])
                    t = dt.strftime("%H:%M")
                except Exception:
                    t = "21:00"
                default_games += f"{g['away']} vs {g['home']} {t}\n"
        games_text = st.text_area(
            "Jogos", value=default_games, height=300,
            placeholder="DET vs WAS 20:30\nORL @ CHA 19:00\nCLE x CHI 21:00\nLAL vs MIA 22:30",
            label_visibility="collapsed",
        )

    with col_injuries:
        st.markdown("**🏥 Relatório de Lesões**")
        st.caption("Formato: `[DET] Detroit` depois `Jogador OUT`")
        default_injuries = ""
        if st.session_state.loader.injuries_data and isinstance(st.session_state.loader.injuries_data, list):
            prev_team = ""
            for entry in st.session_state.loader.injuries_data:
                team = entry.get("team", "")
                if team != prev_team:
                    abbr = _team_name_to_abbr(team)
                    default_injuries += f"[{abbr}] {team}\n"
                    prev_team = team
                default_injuries += f"{entry['player']} {entry['status']}\n"

        injuries_text = st.text_area(
            "Lesões", value=default_injuries, height=300,
            placeholder="[DET] Detroit Pistons\nCade Cunningham OUT\nIsaiah Stewart OUT\n\n[WIZ] Washington Wizards\nTrae Young OUT\nAnthony Davis OUT",
            label_visibility="collapsed",
        )

    if st.button("🔄 Processar e Salvar", type="primary"):
        errors = []

        games = parse_games_text(games_text)
        if not games:
            errors.append("⚠️ Nenhum jogo reconhecido. Verifique o formato.")
        else:
            save_games(games)
            st.success(f"✅ {len(games)} jogos salvos!")

        injuries = parse_injuries_text(injuries_text)
        total_inj = sum(len(t["jogadores"]) for t in injuries.get("relatorio_lesoes", {}).get("times", []))
        if total_inj > 0:
            save_injuries(injuries)
            st.success(f"✅ {total_inj} jogadores com lesão salvos!")

        if errors:
            for e in errors:
                st.error(e)

        if games or total_inj > 0:
            st.rerun()

    with st.expander("📖 Formato aceito"):
        st.markdown("""
**Jogos:**
- `DET vs WAS 20:30` —DET em casa, jogo às 20:30
- `CLE x CHI` —CLE em casa, às 21:00
- `ORL @ CHA` —ORL fora, CHA em casa
- `2026-03-20\nLAL vs MIA 22:30` — com data na linha acima
- Times: use nome completo ou abreviatura (CLE, WAS, LAC, LAL...)

**Lesões:**
- `[DET] Detroit Pistons` — abre seção do time
- `Jogador OUT` — OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, ACTIVE
- `Jogador - OUT (tornozelo)` — com descrição opcional
- `[WAS] Washington Wizards` depois linhas de jogadores
""")


with tab2:
    st.markdown("#### 🏀 Jogos do Dia")

    if st.session_state.loader.games_data:
        import json
        edited = st.data_editor(
            st.session_state.loader.games_data,
            num_rows="dynamic",
            column_config={
                "id": st.column_config.TextColumn("ID", width="medium"),
                "home": st.column_config.TextColumn("Casa", width="medium"),
                "away": st.column_config.TextColumn("Fora", width="medium"),
                "datetime": st.column_config.TextColumn("DataTime ISO", width="medium"),
            },
            hide_index=True,
            key="games_editor",
        )
        if st.button("💾 Salvar Jogos", type="primary"):
            save_games(st.session_state.get("games_editor", edited))
            st.success("✅ Jogos salvos!")
            st.rerun()
    else:
        st.info("Nenhum jogo carregado. Use a aba **📝 Texto Plano** para adicionar.")


with tab3:
    st.markdown("#### 🏥 Relatório de Lesões")

    if st.session_state.loader.injuries_data and isinstance(st.session_state.loader.injuries_data, list):
        rows = []
        for entry in st.session_state.loader.injuries_data:
            rows.append({
                "team": entry.get("team", ""),
                "player": entry.get("player", ""),
                "status": entry.get("status", ""),
            })

        edited = st.data_editor(
            rows,
            num_rows="dynamic",
            column_config={
                "team": st.column_config.TextColumn("Time", width="medium"),
                "player": st.column_config.TextColumn("Jogador", width="medium"),
                "status": st.column_config.SelectboxColumn(
                    "Status", width="small",
                    options=["OUT", "DOUBTFUL", "QUESTIONABLE", "PROBABLE", "ACTIVE"],
                ),
            },
            hide_index=True,
            key="injuries_editor",
        )

        if st.button("💾 Salvar Lesões", type="primary"):
            by_team = {}
            edited_rows = st.session_state.get("injuries_editor", [])
            if hasattr(edited_rows, "to_dict"):
                edited_rows = edited_rows.to_dict("records")
            for row in edited_rows:
                t = row["team"]
                if t not in by_team:
                    by_team[t] = {"abbr": _team_name_to_abbr(t), "team": t, "jogadores": []}
                by_team[t]["jogadores"].append({"nome": row["player"], "status": row["status"]})
            injuries = {"relatorio_lesoes": {"data": datetime.now().strftime("%Y-%m-%d"), "times": list(by_team.values())}}
            save_injuries(injuries)
            st.success("✅ Lesões salvas!")
            st.rerun()
    else:
        st.info("Nenhum relatório carregado. Use a aba **📝 Texto Plano** para adicionar.")
