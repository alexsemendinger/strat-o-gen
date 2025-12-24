#!/usr/bin/env python3
"""Test card generation for Isiah Kiner-Falefa 2023"""

from card_formulas import BatterCardFormulas
from card_layout import CardLayoutGenerator

# IKF 2023 stats
ikf_2023_stats = {
    'name': 'Isiah Kiner-Falefa',
    'year': 2023,
    'league': 'AL',
    'AB': 515,
    'H': 131,
    'BA': 0.254,
    '2B': 21,
    '3B': 2,
    'HR': 8,
    'BB': 28,
    'SO': 71,
    'HBP': 8,
    'SB': 14,  # Just below fast threshold
    'CS': 5,
    'PA': 560,
    'SLG': 0.354,
    'OBP': 0.304,
}

# League averages for 2023 AL
league_avg = {
    'year': 2023,
    'league': 'AL',
    'BA': 0.2467,
    'HR_per_PA': 0.0318,
    'BB_per_PA': 0.0810,
    'K_per_PA': 0.2313,
    '2B_per_PA': 0.0449,
    '3B_per_PA': 0.0038,
    'HBP_per_PA': 0.0114,
}

# Calculate card chances
chances = BatterCardFormulas.calculate_batter_card_chances(ikf_2023_stats, league_avg)

# Generate layout with player stats for baserunning modifiers
layout = CardLayoutGenerator.generate_layout(
    chances,
    ikf_2023_stats['name'],
    ikf_2023_stats['year'],
    player_stats=ikf_2023_stats
)

# Display
print(layout)

# Show totals
totals = layout.get_outcome_totals()
print("\nLayout Totals:")
for outcome, count in sorted(totals.items()):
    print(f"  {outcome:15s}: {count:6.2f}")
print(f"  {'TOTAL':15s}: {sum(totals.values()):6.2f} / 108.00")
