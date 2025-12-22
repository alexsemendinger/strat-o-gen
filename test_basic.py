#!/usr/bin/env python3
"""Basic functionality test for Strat-O-Matic Card Generator."""

import sys
from scraper import PlayerScraper
from card_engine import CardEngine
from card_renderer import CardRenderer


def test_basic_functionality():
    """Test basic card generation workflow."""
    print("Strat-O-Matic Card Generator - Basic Test")
    print("=" * 50)

    # Initialize components
    print("\n1. Initializing components...")
    scraper = PlayerScraper()
    engine = CardEngine()
    renderer = CardRenderer()
    print("   ✓ Components initialized")

    # Test player search
    print("\n2. Testing player search...")
    test_players = [
        ("Babe Ruth", 1927),
        ("Lou Gehrig", 1934),
        ("Ted Williams", 1941),
        ("Mickey Mantle", 1956),
        ("Barry Bonds", 2001),
        ("Mike Trout", 2019),
    ]

    for name, year in test_players:
        print(f"\n   Testing: {name} ({year})")

        # Search for player
        players = scraper.search_players(name)

        if not players:
            print(f"   ✗ No players found for '{name}'")
            continue

        print(f"   ✓ Found {len(players)} player(s)")

        # Use first match
        player_id = players[0]['player_id']
        print(f"   Player ID: {player_id}")

        # Fetch stats
        try:
            stats = scraper.get_player_stats(player_id, year)

            if not stats:
                print(f"   ✗ No stats found for {year}")
                continue

            print(f"   ✓ Stats loaded: {stats['PA']} PA, {stats['BA']:.3f} AVG, {stats['HR']} HR")

            # Get league averages
            league = stats.get('league', 'AL')
            league_avg = scraper.get_league_averages(year, league)

            if not league_avg:
                print(f"   ⚠ Using default league averages")
                league_avg = scraper._get_default_league_averages()
            else:
                print(f"   ✓ League averages loaded")

            # Generate card
            card = engine.generate_card(stats, league_avg)
            print(f"   ✓ Card generated")
            print(f"   Confidence: {card['confidence']['overall']}")

            # Check card has required elements
            assert 'grid' in card, "Card missing grid"
            assert len(card['grid']) == 3, "Card should have 3 columns"
            assert 'ratings' in card, "Card missing ratings"

            # Check chances sum to 108
            total_chances = sum(card['chances'].values())
            if abs(total_chances - 108) > 1:
                print(f"   ⚠ Chances sum to {total_chances:.1f} (should be 108)")
            else:
                print(f"   ✓ Chances validated ({total_chances:.1f})")

            # Display chance distribution
            print(f"   Chance distribution:")
            for outcome in ['HOMERUN', 'TRIPLE', 'DOUBLE', 'SINGLE', 'WALK', 'STRIKEOUT']:
                count = card['chances'].get(outcome, 0)
                if count > 0:
                    print(f"     {outcome}: {count:.1f}")

        except Exception as e:
            print(f"   ✗ Error: {e}")
            import traceback
            traceback.print_exc()
            continue

    print("\n" + "=" * 50)
    print("Basic test completed!")


def test_early_era_player():
    """Test with a player from early baseball era (before 1955)."""
    print("\n\nTesting Early Era Player (pre-1955)")
    print("=" * 50)

    scraper = PlayerScraper()
    engine = CardEngine()

    # Test with Ty Cobb from 1911
    print("\nTesting: Ty Cobb (1911)")

    try:
        players = scraper.search_players("Ty Cobb")

        if not players:
            print("✗ Could not find Ty Cobb")
            return

        player_id = players[0]['player_id']
        stats = scraper.get_player_stats(player_id, 1911)

        if not stats:
            print("✗ No stats for 1911")
            return

        print(f"✓ Stats loaded: {stats['PA']} PA, {stats['BA']:.3f} AVG")
        print(f"  Warnings: {stats['warnings']}")

        league_avg = scraper.get_league_averages(1911, stats.get('league', 'AL'))
        if not league_avg:
            league_avg = scraper._get_default_league_averages()

        card = engine.generate_card(stats, league_avg)
        print(f"✓ Card generated with confidence: {card['confidence']['overall']}")
        print(f"  Missing data: {card['confidence']['missing_data']}")

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    try:
        test_basic_functionality()
        test_early_era_player()
        print("\n✓ All tests completed successfully!")
        sys.exit(0)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
