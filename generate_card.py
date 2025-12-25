#!/usr/bin/env python3
"""
Generate a Strat-O-Matic baseball card for a player.

Usage:
    python generate_card.py <bbref_id> <year>           # Batter card (default)
    python generate_card.py <bbref_id> <year> --pitcher # Pitcher card

Example:
    python generate_card.py troutmi01 2019              # Mike Trout 2019 (batter)
    python generate_card.py ryanno01 1972 --pitcher     # Nolan Ryan 1972 (pitcher)
"""

import sys
from stats_fetcher import StatsFetcher
from card_formulas import BatterCardFormulas, PitcherCardFormulas
from league_averages import LeagueAveragesFetcher
from card_layout import CardLayoutGenerator


def generate_batter_card(bbref_id: str, year: int):
    """Generate a batter card."""
    # Fetch stats
    fetcher = StatsFetcher()
    stats = fetcher.get_batting_stats(bbref_id, year)

    if not stats:
        print(f"Error: Could not fetch batting stats for {bbref_id} in {year}")
        return

    # Get league averages
    league = stats.get('league', 'AL')
    league_fetcher = LeagueAveragesFetcher()
    league_avg = league_fetcher.get_league_averages(year, league)

    # Calculate card chances
    chances = BatterCardFormulas.calculate_batter_card_chances(stats, league_avg)

    # Generate layout (card_type='batter' for columns 1-2-3)
    player_name = stats.get('name', bbref_id)
    layout = CardLayoutGenerator.generate_layout(
        chances, player_name, year,
        player_stats=stats, card_type='batter'
    )

    # Display
    print(layout)

    # Show warnings if any
    if chances.get('warnings'):
        print("\nWarnings:")
        for warning in chances['warnings']:
            print(f"  - {warning}")

    # Show calculated chances
    print("\nCalculated Chances:")
    print(f"  HR:  {chances['homerun']:6.2f}")
    print(f"  3B:  {chances['triple']:6.2f}")
    print(f"  2B:  {chances['double']:6.2f}")
    print(f"  1B:  {chances['single']:6.2f}")
    print(f"  BB:  {chances['walk']:6.2f}")
    print(f"  HBP: {chances.get('hbp', 0):6.2f}")
    print(f"  SO:  {chances['strikeout']:6.2f}")
    print(f"  OUT: {chances['outs']:6.2f}")
    print(f"  Total non-outs: {chances['total']:6.2f}")

    # Show actual totals from layout
    totals = layout.get_outcome_totals()
    print("\nLayout Totals:")
    print(f"  HR:  {totals.get('homerun', 0):6.2f}")
    print(f"  3B:  {totals.get('triple', 0):6.2f}")
    print(f"  2B:  {totals.get('double', 0):6.2f}")
    print(f"  1B:  {totals.get('single', 0) + totals.get('single*', 0) + totals.get('single**', 0):6.2f}")
    print(f"  BB:  {totals.get('walk', 0):6.2f}")
    print(f"  HBP: {totals.get('hbp', 0):6.2f}")
    print(f"  SO:  {totals.get('strikeout', 0):6.2f}")
    print(f"  OUT: {totals.get('out', 0):6.2f}")
    print(f"  TOTAL: {sum(totals.values()):6.2f} / 108.00")


def generate_pitcher_card(bbref_id: str, year: int):
    """Generate a pitcher card."""
    # Fetch stats
    fetcher = StatsFetcher()
    stats = fetcher.get_pitching_stats(bbref_id, year)

    if not stats:
        print(f"Error: Could not fetch pitching stats for {bbref_id} in {year}")
        return

    # Get league averages for estimating 2B/3B from hits
    league = stats.get('league', 'AL')
    league_fetcher = LeagueAveragesFetcher()
    league_avg = league_fetcher.get_league_averages(year, league)

    # Calculate card chances using pitcher formulas
    chances = PitcherCardFormulas.calculate_pitcher_card_chances(stats, league_avg)

    # Generate layout (card_type='pitcher' for columns 4-5-6)
    player_name = stats.get('name', bbref_id)
    layout = CardLayoutGenerator.generate_layout(
        chances, player_name, year,
        card_type='pitcher'
    )

    # Display
    print(layout)

    # Show warnings if any
    if chances.get('warnings'):
        print("\nWarnings:")
        for warning in chances['warnings']:
            print(f"  - {warning}")

    # Show calculated chances
    print("\nCalculated Chances:")
    for outcome in ['walk', 'strikeout', 'homerun', 'triple', 'double', 'single', 'outs']:
        if outcome in chances:
            print(f"  {outcome:12s}: {chances[outcome]:6.2f}")

    # Show actual totals from layout
    totals = layout.get_outcome_totals()
    print("\nLayout Totals:")
    print(f"  BB:  {totals.get('walk', 0):6.2f}")
    print(f"  SO:  {totals.get('strikeout', 0):6.2f}")
    print(f"  HR:  {totals.get('homerun', 0):6.2f}")
    print(f"  3B:  {totals.get('triple', 0):6.2f}")
    print(f"  2B:  {totals.get('double', 0):6.2f}")
    print(f"  1B:  {totals.get('single', 0) + totals.get('single*', 0) + totals.get('single**', 0):6.2f}")
    print(f"  OUT: {totals.get('out', 0):6.2f}")
    print(f"  TOTAL: {sum(totals.values()):6.2f} / 108.00")


if __name__ == "__main__":
    # Parse arguments
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    is_pitcher = '--pitcher' in sys.argv or '-p' in sys.argv

    if len(args) != 2:
        print("Usage: python generate_card.py <bbref_id> <year> [--pitcher]")
        print("\nExamples:")
        print("  python generate_card.py troutmi01 2019           # Mike Trout 2019 (batter)")
        print("  python generate_card.py ruthba01 1927            # Babe Ruth 1927 (batter)")
        print("  python generate_card.py ryanno01 1972 --pitcher  # Nolan Ryan 1972 (pitcher)")
        print("  python generate_card.py morrija02 1983 --pitcher # Jack Morris 1983 (pitcher)")
        sys.exit(1)

    bbref_id = args[0]
    year = int(args[1])

    if is_pitcher:
        print(f"Generating PITCHER card for {bbref_id} in {year}...")
        print()
        generate_pitcher_card(bbref_id, year)
    else:
        print(f"Generating BATTER card for {bbref_id} in {year}...")
        print()
        generate_batter_card(bbref_id, year)
