#!/usr/bin/env python3
"""
Generate a Strat-O-Matic baseball card for a player.

Usage:
    python generate_card.py <bbref_id> <year>

Example:
    python generate_card.py troutmi01 2019
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

    # Generate layout
    player_name = stats.get('name', bbref_id)
    layout = CardLayoutGenerator.generate_layout(chances, player_name, year)

    # Display
    print(layout)

    # Show warnings if any
    if chances.get('warnings'):
        print("\nWarnings:")
        for warning in chances['warnings']:
            print(f"  ⚠ {warning}")

    # Show calculated chances
    print("\nCalculated Chances:")
    print(f"  HR:  {chances['homerun']:6.2f}")
    print(f"  3B:  {chances['triple']:6.2f}")
    print(f"  2B:  {chances['double']:6.2f}")
    print(f"  1B:  {chances['single']:6.2f}")
    print(f"  BB:  {chances['walk']:6.2f}")
    print(f"  HBP: {chances['hbp']:6.2f}")
    print(f"  SO:  {chances['strikeout']:6.2f}")
    print(f"  OUT: {chances['outs']:6.2f}")
    print(f"  Total non-outs: {chances['total']:6.2f}")

    # Show actual totals from layout
    totals = layout.get_outcome_totals()
    print("\nLayout Totals:")
    print(f"  HR:  {totals.get('homerun', 0):6.2f}")
    print(f"  3B:  {totals.get('triple', 0):6.2f}")
    print(f"  2B:  {totals.get('double', 0):6.2f}")
    print(f"  1B:  {totals.get('single', 0):6.2f}")
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

    # Calculate card chances
    chances = PitcherCardFormulas.calculate_pitcher_card_chances(stats)

    # Generate layout
    player_name = stats.get('name', bbref_id)
    layout = CardLayoutGenerator.generate_layout(chances, player_name, year)

    # Display
    print(layout)

    print("\nCalculated Chances:")
    for outcome in ['walk', 'hbp', 'strikeout', 'homerun', 'triple', 'double', 'single', 'outs']:
        if outcome in chances:
            print(f"  {outcome:12s}: {chances[outcome]:6.2f}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python generate_card.py <bbref_id> <year>")
        print("\nExamples:")
        print("  python generate_card.py rainesti01 2001   # Tim Raines 2001")
        print("  python generate_card.py ruthba01 1927     # Babe Ruth 1927")
        print("  python generate_card.py troutmi01 2019    # Mike Trout 2019")
        sys.exit(1)

    bbref_id = sys.argv[1]
    year = int(sys.argv[2])

    print(f"Generating card for {bbref_id} in {year}...")
    print()

    # Try batter first, then pitcher
    generate_batter_card(bbref_id, year)
