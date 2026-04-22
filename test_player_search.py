import sys
sys.path.insert(0, '.')
from scrapers.espn_scraper import ESPNScraper

scraper = ESPNScraper()

# Test Jalen Johnson
print('=== Jalen Johnson ===')
team_stats = scraper.get_team_stats('ATL')
if team_stats:
    for p in team_stats:
        if 'jalen' in p.get('name', '').lower():
            name = p.get('name')
            pid = p.get('pid')
            print(f'Found: {name} - PID: {pid}')
            last5 = scraper.get_player_last5(pid, name, last_game_only=True)
            print(f'Last5: {last5}')
else:
    print('No team stats')

# Test Nickeil Alexander-Walker
print('\n=== Nickeil Alexander-Walker ===')
if team_stats:
    for p in team_stats:
        if 'nickeil' in p.get('name', '').lower():
            name = p.get('name')
            pid = p.get('pid')
            print(f'Found: {name} - PID: {pid}')
            last5 = scraper.get_player_last5(pid, name, last_game_only=True)
            print(f'Last5: {last5}')

# Test Deni Avdija
print('\n=== Deni Avdija ===')
team_stats = scraper.get_team_stats('POR')
if team_stats:
    for p in team_stats:
        if 'deni' in p.get('name', '').lower():
            name = p.get('name')
            pid = p.get('pid')
            print(f'Found: {name} - PID: {pid}')
            last5 = scraper.get_player_last5(pid, name, last_game_only=True)
            print(f'Last5: {last5}')
else:
    print('No team stats')