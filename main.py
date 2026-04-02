#!/usr/bin/env python3
import sys
import argparse
from datetime import datetime

import config
from utils.data_loader import DataLoader
from scrapers.espn_scraper import ESPNScraper
from scrapers.stats_scraper import generate_fallback_stats
from scrapers.matchup_scraper import fetch_and_cache_matchups, print_matchup_summary
from scrapers.blowout_risk import analyze_games_blowout_risk, print_blowout_summary
from gerador.props_engine import PropsEngine
from gerador.bilheteiro import Bilheteiro


def parse_args():
    parser = argparse.ArgumentParser(description="Gerador de Bilhetes NBA Milionarios")
    parser.add_argument(
        "--scrape",
        action="store_true",
        help="Buscar estatisticas online (scraping Basketball Reference)",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Nao usar estatisticas ficticias para jogadores sem dados",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Nome do arquivo de output",
    )
    return parser.parse_args()


def load_or_generate_stats(loader: DataLoader, teams_data: list, do_scrape: bool, use_fallback: bool):
    existing_cache = loader.stats_cache
    stats = existing_cache.copy()

    players_in_games = loader.get_all_players_from_games()
    missing = [p for p in players_in_games if p["name"] not in stats]

    if do_scrape and missing:
        scraper = ESPNScraper()
        new_stats = scraper.scrape_all_players_from_games(
            loader.games_data, teams_data
        )
        stats.update(new_stats)
        if new_stats:
            loader.save_stats_cache(stats)
            print(f"\nScraping concluido: {len(new_stats)}/{len(missing)} encontrados")
        else:
            print("\nScraping nao retornou dados.")

    if use_fallback and missing:
        remaining = [p for p in missing if p["name"] not in stats]
        if remaining:
            print(f"\nGerando fallback para {len(remaining)} jogadores sem dados...")
            fallback = generate_fallback_stats(remaining)
            stats.update(fallback)
            loader.save_stats_cache(stats)
        print(f"Total de jogadores com stats: {len(stats)}")
    elif existing_cache:
        print(f"\nUsando cache existente: {len(stats)} jogadores")
    else:
        print(f"\nAviso: nenhum dado disponivel!")

    return stats


def generate_all_props(loader: DataLoader, stats: dict, matchup_data=None, blowout_risks=None):
    props_engine = PropsEngine()
    all_props = []

    injured = loader.get_injured_players()
    questionable = loader.get_questionable_players()

    print("\nGerando props para os jogos do dia...")

    for game in loader.games_data:
        game_risk = (blowout_risks or {}).get(game["id"])
        game_props = props_engine.generate_props_for_game(
            game, stats, injured, questionable, loader.teams_data, matchup_data, game_risk
        )
        all_props.extend(game_props)

    print(f"Total de props gerados: {len(all_props)}")
    return all_props


def main():
    args = parse_args()

    print("\n" + "=" * 60)
    print("       NBA MILIONARIO - GERADOR DE BILHETES")
    print("=" * 60)

    loader = DataLoader()

    print("\n[1/5] Carregando dados...")
    try:
        loader.load_all()
        loader.print_summary()
    except FileNotFoundError as e:
        print(f"\n[X] ERRO: {e}")
        print("\nArquivos necessarios:")
        print("  - nba_por_equipe.json (na raiz)")
        print("  - data/jogos_do_dia.json")
        print("  - data/relatorio_lesoes.json")
        sys.exit(1)

    print("\n[2/5] Buscando/carregando estatisticas...")
    stats = load_or_generate_stats(
        loader,
        loader.teams_data,
        do_scrape=args.scrape,
        use_fallback=not args.no_fallback,
    )

    print("\n[3/5] Carregando dados de matchups (defesa vs posicao)...")
    matchup_data = fetch_and_cache_matchups()
    if matchup_data:
        print_matchup_summary(matchup_data)

    print("\n[4/5] Analisando risco de blowout por jogo...")
    injured_all = loader.get_injured_players()
    blowout_risks = analyze_games_blowout_risk(
        loader.games_data, stats, injured_all, loader.teams_data
    )
    print_blowout_summary(blowout_risks)

    print("\n[5/5] Gerando props e analisando jogos...")
    all_props = generate_all_props(loader, stats, matchup_data, blowout_risks)

    if not all_props:
        print("\n[X] Nenhum prop gerado. Verifique os dados.")
        sys.exit(1)

    game_date = "2026-03-26"
    if loader.games_data:
        first_game = loader.games_data[0]
        dt = first_game.get("datetime", "")
        if dt:
            game_date = dt[:10]

    print("\n[OK] Montando bilhetes por jogo...")
    bilheteiro = Bilheteiro(date=game_date)
    tickets = bilheteiro.generate_multi_game_ticket(all_props, loader.games_data)

    if not tickets:
        print("\n[X] Nao foi possivel montar bilhetes validos.")
        sys.exit(1)

    print("\n[OK] Exibindo resultados...")
    bilheteiro.print_all_tickets(tickets)

    output_path = bilheteiro.save_all_tickets(tickets, args.output)
    print(f"\n[*] Bilhetes salvos em: {output_path}")

    low_odds = [t for t in tickets if t["total_odds"] < bilheteiro.game_min_odds]
    if low_odds:
        for t in low_odds:
            print(
                f"  [!] {t['away']} @ {t['home']}: odd {t['total_odds']:.2f}x "
                f"abaixo do minimo ({bilheteiro.game_min_odds}x)"
            )

    print("\n[OK] Concluido!\n")


if __name__ == "__main__":
    main()
