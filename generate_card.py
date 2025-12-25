#!/usr/bin/env python3
"""
Generate a Strat-O-Matic baseball card for a player.

Usage:
    python generate_card.py <player> <year>           # Batter card (default)
    python generate_card.py <player> <year> --pitcher # Pitcher card
    python generate_card.py --search <name>           # Search for player ID

The <player> can be either:
    - A Baseball Reference ID (e.g., troutmi01, ruthba01)
    - A player name (e.g., "Mike Trout", "Babe Ruth")

If a name matches multiple players, you'll be prompted to select one.

Examples:
    python generate_card.py troutmi01 2019              # Mike Trout 2019 (by ID)
    python generate_card.py "Mike Trout" 2019           # Mike Trout 2019 (by name)
    python generate_card.py "Nolan Ryan" 1972 --pitcher # Nolan Ryan 1972 (pitcher)
    python generate_card.py --search "Ken Griffey"      # Find Ken Griffey Jr/Sr IDs
"""

import sys
import re
from stats_fetcher import StatsFetcher
from card_formulas import BatterCardFormulas, PitcherCardFormulas
from league_averages import LeagueAveragesFetcher
from card_layout import CardLayoutGenerator


def is_bbref_id(text: str) -> bool:
    """Check if text looks like a Baseball Reference ID (e.g., troutmi01)."""
    # BBRef IDs are typically: last name (up to 5 chars) + first 2 of first name + 2 digits
    # Pattern: lowercase letters followed by 2 digits
    return bool(re.match(r'^[a-z]+\d{2}$', text.lower()))


def resolve_player(player_input: str, fetcher: StatsFetcher, select_num: int = None) -> str:
    """
    Resolve a player input to a Baseball Reference ID.

    If input looks like a bbref ID, returns it directly.
    If input is a name, searches and handles disambiguation.

    Args:
        player_input: Player name or bbref ID
        fetcher: StatsFetcher instance
        select_num: If provided, auto-select this result number (1-indexed)

    Returns:
        bbref_id string, or None if not found/cancelled
    """
    # If it looks like an ID already, return it
    if is_bbref_id(player_input):
        return player_input

    # Otherwise, search by name
    print(f"Searching for '{player_input}'...")
    results = fetcher.search_player(player_input)

    if not results:
        print(f"No players found matching '{player_input}'")
        return None

    if len(results) == 1:
        # Single match - use it
        player = results[0]
        print(f"Found: {player['name']} ({player['id']})")
        return player['id']

    # Multiple matches - show list
    print(f"\nFound {len(results)} players matching '{player_input}':")
    print("-" * 50)
    for i, player in enumerate(results, 1):
        years_str = f" ({player['years']})" if player['years'] else ""
        print(f"  {i}. {player['name']}{years_str} - {player['id']}")
    print("-" * 50)

    # If select_num provided, use it directly
    if select_num is not None:
        idx = select_num - 1
        if 0 <= idx < len(results):
            selected = results[idx]
            print(f"Auto-selected: {selected['name']} ({selected['id']})")
            return selected['id']
        else:
            print(f"Invalid selection {select_num}. Must be 1-{len(results)}")
            return None

    # Check if stdin is interactive
    if not sys.stdin.isatty():
        print("\nMultiple players found. Use --select N to choose, or use --search first.")
        print("Example: python generate_card.py 'Babe Ruth' 1927 --select 1")
        return None

    # Interactive selection
    while True:
        try:
            choice = input("Enter number to select (or 'q' to quit): ").strip()
            if choice.lower() == 'q':
                return None

            idx = int(choice) - 1
            if 0 <= idx < len(results):
                selected = results[idx]
                print(f"Selected: {selected['name']} ({selected['id']})")
                return selected['id']
            else:
                print(f"Please enter a number between 1 and {len(results)}")
        except ValueError:
            print("Please enter a valid number")


def search_only(name: str):
    """Just search for a player and display results."""
    fetcher = StatsFetcher()
    results = fetcher.search_player(name)

    if not results:
        print(f"No players found matching '{name}'")
        return

    print(f"\nPlayers matching '{name}':")
    print("-" * 60)
    for player in results:
        years_str = f" ({player['years']})" if player['years'] else ""
        print(f"  {player['name']}{years_str}")
        print(f"    ID: {player['id']}")
    print("-" * 60)


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
        player_stats=stats, card_type='pitcher'
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
    # Parse --select N option first (need to remove it from args)
    select_num = None
    argv_filtered = []
    skip_next = False
    for i, arg in enumerate(sys.argv[1:]):
        if skip_next:
            skip_next = False
            continue
        if arg == '--select':
            if i + 1 < len(sys.argv) - 1:
                try:
                    select_num = int(sys.argv[i + 2])
                    skip_next = True
                    continue
                except ValueError:
                    pass
        argv_filtered.append(arg)

    # Parse remaining arguments
    args = [a for a in argv_filtered if not a.startswith('--') and not a.startswith('-')]
    is_pitcher = '--pitcher' in argv_filtered or '-p' in argv_filtered
    is_search = '--search' in argv_filtered or '-s' in argv_filtered

    # Handle search-only mode
    if is_search:
        if not args:
            print("Usage: python generate_card.py --search <name>")
            print("Example: python generate_card.py --search 'Ken Griffey'")
            sys.exit(1)
        search_only(' '.join(args))
        sys.exit(0)

    # Normal card generation mode
    if len(args) != 2:
        print("Usage: python generate_card.py <player> <year> [--pitcher]")
        print("       python generate_card.py --search <name>")
        print()
        print("The <player> can be a name or Baseball Reference ID.")
        print()
        print("Examples:")
        print("  python generate_card.py 'Mike Trout' 2019         # Search by name")
        print("  python generate_card.py troutmi01 2019            # Use ID directly")
        print("  python generate_card.py 'Nolan Ryan' 1972 -p      # Pitcher card")
        print("  python generate_card.py --search 'Ken Griffey'    # Find player IDs")
        print("  python generate_card.py 'Ken Griffey' 1990 --select 1  # Auto-select")
        sys.exit(1)

    player_input = args[0]
    year = int(args[1])

    # Resolve player name to ID if needed
    fetcher = StatsFetcher()
    bbref_id = resolve_player(player_input, fetcher, select_num)

    if not bbref_id:
        sys.exit(1)

    if is_pitcher:
        print(f"\nGenerating PITCHER card for {bbref_id} in {year}...")
        print()
        generate_pitcher_card(bbref_id, year)
    else:
        print(f"\nGenerating BATTER card for {bbref_id} in {year}...")
        print()
        generate_batter_card(bbref_id, year)
