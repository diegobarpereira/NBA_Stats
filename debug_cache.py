import sys
sys.path.insert(0, '.')
import json
import config
from pathlib import Path

# Check what's in the saved_player_last_game
comparison_file = config.DATA_DIR / "comparison_history.json"

if comparison_file.exists():
    with open(comparison_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    player_cache = data.get('player_last_game', {})
    
    print("Players in cache:")
    for name in sorted(player_cache.keys()):
        stats = player_cache[name]
        print(f"  {name}: {stats}")
else:
    print("No comparison history file")

# Also check what's in session state
print("\n--- Checking ticket ---")
bilhete_file = "bilhetes_2026-04-06_160722.json"  # Latest
if Path(f"output/{bilhete_file}").exists():
    with open(f"output/{bilhete_file}", 'r') as f:
        bilhete = json.load(f)
    
    print(f"Game: {bilhete['tickets'][0]['home']} @ {bilhete['tickets'][0]['away']}")
    print(f"Game ID: {bilhete['tickets'][0]['game_id']}")
    print("\nPlayers in ticket:")
    for prop in bilhete['tickets'][0]['props']:
        print(f"  {prop['player']} - {prop['abbrev']}: {prop['line']}")