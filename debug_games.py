import json

files = {
    "165806": "output/bilhetes_2026-04-07_165806.json",
    "005322": "output/bilhetes_2026-04-07_005322.json",
}

for name, path in files.items():
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    print(f"\n=== {name} ===")
    game_ids = []
    teams = set()
    for ticket in data.get("tickets", []):
        game_ids.append(ticket.get("game_id", ""))
        parts = ticket.get("game_id", "").split("_")
        if len(parts) >= 2:
            team_part = parts[0].split("vs")
            if len(team_part) == 2:
                teams.add(team_part[0])
                teams.add(team_part[1])
    
    print(f"Game IDs: {game_ids}")
    print(f"Teams found: {sorted(teams)}")
