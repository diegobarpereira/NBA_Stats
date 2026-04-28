import streamlit as st
import datetime


TEAM_COLORS = {
    "Atlanta Hawks": ("#E31837", "#C1D32F"),
    "Boston Celtics": ("#007A33", "#FFFFFF"),
    "Brooklyn Nets": ("#000000", "#FFFFFF"),
    "Charlotte Hornets": ("#1D1160", "#00788C"),
    "Chicago Bulls": ("#CE1141", "#000000"),
    "Cleveland Cavaliers": ("#6B1414", "#FFB81C"),
    "Dallas Mavericks": ("#00538C", "#002B5E"),
    "Denver Nuggets": ("#0E2240", "#FEC524"),
    "Detroit Pistons": ("#1D42BA", "#D50032"),
    "Golden State Warriors": ("#1D428A", "#FFC72C"),
    "Houston Rockets": ("#CE1141", "#000000"),
    "Indiana Pacers": ("#002D62", "#FDBB30"),
    "Los Angeles Clippers": ("#C8102E", "#1D42BA"),
    "Los Angeles Lakers": ("#552583", "#FDB927"),
    "Memphis Grizzlies": ("#5D76A9", "#12173F"),
    "Miami Heat": ("#98002E", "#F9A01B"),
    "Milwaukee Bucks": ("#004714", "#FFFFFF"),
    "Minnesota Timberwolves": ("#0C2340", "#78BE20"),
    "New Orleans Pelicans": ("#002B5E", "#C8102E"),
    "New York Knicks": ("#006BB6", "#F58426"),
    "Oklahoma City Thunder": ("#EF3B24", "#007AC1"),
    "Orlando Magic": ("#0077C0", "#C4CED4"),
    "Philadelphia 76ers": ("#006BB6", "#ED0145"),
    "Phoenix Suns": ("#1D1160", "#E56020"),
    "Portland Trail Blazers": ("#E03A3E", "#000000"),
    "Sacramento Kings": ("#5C2D91", "#000000"),
    "San Antonio Spurs": ("#C4CED4", "#000000"),
    "Toronto Raptors": ("#CE1141", "#000000"),
    "Utah Jazz": ("#002B5E", "#00A9E0"),
    "Washington Wizards": ("#002B5E", "#E31837"),
}

TEAM_ABBR = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP", "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}

TYPE_ICONS = {
    "points": "🏀 PTS",
    "rebounds": "🔴 REB",
    "assists": "🔵 AST",
    "3pt": "🟡 3PM",
}

_CSS_LOADED = False

_TICKET_CSS = """
<style>
.ticket-wrapper {
    border: 2px solid #333;
    border-radius: 12px;
    overflow: hidden;
    background: #0d0d1a;
    max-width: 700px;
    margin: 0 auto;
    box-shadow: 0 4px 20px rgba(0,0,0,0.5);
    font-family: 'Segoe UI', sans-serif;
}
.ticket-header {
    display: flex;
    justify-content: space-between;
    padding: 12px 16px;
    color: white;
    font-weight: bold;
    font-size: 14px;
}
.ticket-teams {
    display: flex;
    align-items: center;
    gap: 15px;
}
.ticket-team {
    padding: 6px 12px;
    border-radius: 6px;
    font-weight: bold;
}
.ticket-odds {
    text-align: right;
}
.ticket-odds .value {
    font-size: 20px;
    font-weight: bold;
}
.ticket-odds .label {
    font-size: 11px;
    opacity: 0.7;
}
.confidence-bar {
    font-family: monospace;
    letter-spacing: 2px;
}
.odds-high { color: #22c55e; }
.odds-mid { color: #eab308; }
.odds-low { color: #ef4444; }
.ticket-props {
    padding: 16px;
    background: #151528;
}
.ticket-prop {
    display: flex;
    justify-content: space-between;
    padding: 8px 12px;
    margin: 6px 0;
    background: #1a1a35;
    border-radius: 8px;
    color: white;
    font-size: 14px;
}
.ticket-prop .player { font-weight: 600; }
.ticket-prop .line { color: #22c55e; }
.ticket-prop .odds { color: #fbbf24; font-weight: bold; }
.ticket-footer {
    padding: 10px 16px;
    background: #0d0d1a;
    border-top: 1px solid #333;
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: #888;
}
.boost-tag, .damp-tag { margin-right: 3px; }
.prop-free {
    display: block;
    margin-top: 2px;
    font-size: 11px;
    color: #94a3b8;
}
</style>
"""


def _inject_css():
    global _CSS_LOADED
    if _CSS_LOADED:
        return
    if "ticket_css_loaded" not in st.session_state:
        st.session_state.ticket_css_loaded = False
    
    if st.session_state.ticket_css_loaded:
        _CSS_LOADED = True
        return
    
    _CSS_LOADED = True
    st.session_state.ticket_css_loaded = True
    st.markdown(_TICKET_CSS, unsafe_allow_html=True)


def render_ticket_card(ticket: dict, ticket_num: int):
    _inject_css()
    home = ticket["home"]
    away = ticket["away"]
    total_odds = ticket["total_odds"]
    props_list = ticket["props"]

    h_color = TEAM_COLORS.get(home, ("#333333", "#FFFFFF"))
    a_color = TEAM_COLORS.get(away, ("#333333", "#FFFFFF"))

    try:
        dt = datetime.datetime.fromisoformat(ticket["datetime"])
        date_str = dt.strftime("%d/%m")
        time_str = dt.strftime("%H:%M")
    except Exception:
        date_str = ticket.get("datetime", "")[:10]
        time_str = ""

    conf = ticket.get("avg_confidence", 0)
    if conf >= 8:
        conf_color = "#22c55e"
        conf_label = "ALTA"
    elif conf >= 5:
        conf_color = "#eab308"
        conf_label = "MÉDIA"
    else:
        conf_color = "#ef4444"
        conf_label = "BAIXA"

    conf_bars = "█" * int(conf) + "░" * (10 - int(conf))

    odds_class = "odds-high" if total_odds >= 9 else ("odds-mid" if total_odds >= 7 else "odds-low")

    props_html = ""
    for i, prop in enumerate(props_list):
        ptype = prop.get("type", "points")
        icon = TYPE_ICONS.get(ptype, "🏀 PTS")
        free_projection = prop.get("free_projection")
        free_score = prop.get("free_score")
        free_text = ""
        if isinstance(free_projection, (int, float)) or isinstance(free_score, (int, float)):
            proj_text = f"Proj {free_projection:.2f}" if isinstance(free_projection, (int, float)) else "Proj -"
            score_text = f"Livre {free_score:.2f}" if isinstance(free_score, (int, float)) else "Livre -"
            free_text = f'<span class="prop-free">{proj_text} | {score_text}</span>'
        injury_tag = ""
        if prop.get("injury_status"):
            injury_tag = f'<span class="injury-tag">{prop["injury_status"]}</span>'
        matchup_tag = ""
        if prop.get("matchup_mult", 1.0) > 1.05:
            matchup_tag = '<span class="boost-tag">🔥</span>'
        elif prop.get("matchup_mult", 1.0) < 0.95:
            matchup_tag = '<span class="damp-tag">❄️</span>'

        bg = "#1a1a2e" if i % 2 == 0 else "#16162a"
        props_html += f"""
        <tr class="prop-row">
            <td class="prop-player">
                {matchup_tag}{prop['player']}{injury_tag}
                <span class="prop-team">{TEAM_ABBR.get(prop.get('team', ''), prop.get('team', ''))}</span>
                {free_text}
            </td>
            <td class="prop-type">{icon}</td>
            <td class="prop-line">{prop.get('over_under', 'Over')} +{prop['line']}</td>
            <td class="prop-odds">@ {prop['odds']:.2f}</td>
            <td class="prop-conf">
                <span class="conf-dot" style="background:{conf_color}"></span>
                {prop['confidence']}/10
            </td>
        </tr>"""

    html = f"""
<div class="ticket-wrapper">
    <div class="ticket-header">
        <div class="team-badge" style="background:{a_color[0]};color:{a_color[1]}">
            <span class="badge-abbr">{TEAM_ABBR.get(away, away[:3])}</span>
            <span class="badge-name">{away}</span>
        </div>
        <div class="game-meta">
            <div class="game-datetime">{date_str} {time_str}</div>
            <div class="vs-badge">VS</div>
        </div>
        <div class="team-badge" style="background:{h_color[0]};color:{h_color[1]}">
            <span class="badge-abbr">{TEAM_ABBR.get(home, home[:3])}</span>
            <span class="badge-name">{home}</span>
        </div>
    </div>

    <div class="ticket-body">
        <table class="props-table">
            <thead>
                <tr>
                    <th>Jogador</th>
                    <th>Tipo</th>
                    <th>Linha</th>
                    <th>Odds</th>
                    <th>Conf</th>
                </tr>
            </thead>
            <tbody>
                {props_html}
            </tbody>
        </table>
    </div>

    <div class="ticket-footer">
        <div class="conf-section">
            <span class="conf-label">CONFIANÇA</span>
            <span class="conf-bars">{conf_bars}</span>
            <span class="conf-score" style="color:{conf_color}">{conf_label}</span>
        </div>
        <div class="odds-section {odds_class}">
            <span class="odds-label">ODD TOTAL</span>
            <span class="odds-value">{total_odds:.2f}x</span>
            <span class="props-count">({len(props_list)} props)</span>
        </div>
    </div>
</div>
"""
    st.html(html)
