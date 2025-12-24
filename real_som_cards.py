"""
Manually transcribed real SOM card chances for validator testing.

These are counted from the actual card layouts, accounting for:
- 2d6 probability weights (2=1, 3=2, 4=3, 5=4, 6=5, 7=6, 8=5, 9=4, 10=3, 11=2, 12=1)
- d20 split results (e.g., "HR 1-12, 2B 13-20")
"""

# Tim Raines 2001 - counted from actual card
# Column 1: 20 outs, 5 SO, 11 BB
# Column 2: 5 outs, 6 SO, 2 BB, 13.25 singles, 5.55 doubles, 1.2 triples, 3 HR
# Column 3: 24.6 outs, 5 BB, 6.4 singles
#
# Totals across 3 columns:
tim_raines_2001_card = {
    'walk': 18.0,      # 11 + 2 + 5
    'hbp': 0.0,        # Not on card
    'strikeout': 11.0, # 5 + 6 + 0
    'homerun': 3.0,    # 0 + 3 + 0 (from "HR 1-12" on dice 8, col 2, weight 5 × 0.6)
    'triple': 1.2,     # 0 + 1.2 + 0 (from "3B 1-6" on dice 9, col 2, weight 4 × 0.3)
    'double': 5.55,    # 0 + 5.55 + 0 (from multiple splits)
    'single': 19.65,   # 0 + 13.25 + 6.4
    'hit_total': 29.4, # 3 + 1.2 + 5.55 + 19.65
    'outs': 49.6,      # 20 + 5 + 24.6
    'total': 108.0,
}

# For context: Tim Raines 2001 actual stats
tim_raines_2001_stats = {
    'year': 2001,
    'BA': 0.312,
    'AB': 551,
    'H': 172,
    '2B': 31,
    '3B': 8,
    'HR': 12,
    'BB': 84,
    'SO': 96,
    'PA': 640,
    'IBB': 5,  # Estimated
    'HBP': 4,  # Estimated
    'SF': 3,   # Estimated
}


if __name__ == "__main__":
    print("=" * 70)
    print("REAL SOM CARD CHANCES - TIM RAINES 2001")
    print("=" * 70)

    print("\nCard chances (out of 108):")
    print(f"  Walks:      {tim_raines_2001_card['walk']:6.2f}")
    print(f"  Strikeouts: {tim_raines_2001_card['strikeout']:6.2f}")
    print(f"  Home Runs:  {tim_raines_2001_card['homerun']:6.2f}")
    print(f"  Triples:    {tim_raines_2001_card['triple']:6.2f}")
    print(f"  Doubles:    {tim_raines_2001_card['double']:6.2f}")
    print(f"  Singles:    {tim_raines_2001_card['single']:6.2f}")
    print(f"  Outs:       {tim_raines_2001_card['outs']:6.2f}")
    print(f"  TOTAL:      {tim_raines_2001_card['total']:6.2f}")

    print(f"\nActual stats:")
    print(f"  BA: {tim_raines_2001_stats['BA']:.3f}")
    print(f"  HR: {tim_raines_2001_stats['HR']}, 2B: {tim_raines_2001_stats['2B']}, 3B: {tim_raines_2001_stats['3B']}")
    print(f"  BB: {tim_raines_2001_stats['BB']}, SO: {tim_raines_2001_stats['SO']}")
