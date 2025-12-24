"""
Real Strat-O-Matic cards for validation testing.

These are manually transcribed from actual SOM cards. They should validate
perfectly (or reveal how much error exists in real SOM cards).
"""

# Tim Raines 2001 (Batter)
tim_raines_2001_stats = {
    'year': 2001,
    'BA': 0.312,
    'AB': 551,
    'H': 172,  # Calculated from BA * AB
    '2B': 31,
    '3B': 8,
    'HR': 12,
    'RBI': 59,
    'BB': 84,
    'SO': 96,
    'SB': 60,
    'CS': 9,
    'SLG': 0.462,
    'OBP': 0.404,
    # Need to calculate/estimate these
    'PA': 640,  # Estimated from OBP calculation
    'IBB': 0,   # Not provided, estimate
    'HBP': 4,   # Estimated to make OBP work
    'SF': 0,    # Not provided
}

# Jack Morris 1983 (Pitcher)
jack_morris_1983_stats = {
    'year': 1983,
    'W': 20,
    'L': 13,
    'ERA': 3.34,
    'IP': 294.0,
    'H': 257,
    'BB': 83,
    'SO': 232,
    'HR': 30,
    # Need these for formulas
    'IBB': 0,   # Not provided
    'HBP': 0,   # Not provided
    'R': 0,     # Not provided
    'ER': 109,  # Calculated from ERA * IP / 9
    'TBF': 1200,  # Estimated
    '2B': 0,    # Not in card
    '3B': 0,    # Not in card
}

# Nolan Ryan 1972 (Pitcher)
nolan_ryan_1972_stats = {
    'year': 1972,
    'W': 19,
    'L': 16,
    'ERA': 2.28,
    'IP': 284.0,
    'H': 166,
    'BB': 157,
    'SO': 329,
    'HR': 14,
    # Need these for formulas
    'IBB': 0,   # Not provided
    'HBP': 0,   # Not provided
    'R': 0,     # Not provided
    'ER': 72,   # Calculated from ERA * IP / 9
    'TBF': 1120,  # Estimated
    '2B': 0,    # Not in card
    '3B': 0,    # Not in card
}


if __name__ == "__main__":
    print("Real SOM Card Test Data")
    print("=" * 70)

    print("\n1. Tim Raines 2001 (Batter)")
    print("-" * 70)
    print(f"BA: {tim_raines_2001_stats['BA']:.3f}")
    print(f"AB: {tim_raines_2001_stats['AB']}, H: {tim_raines_2001_stats['H']}")
    print(f"HR: {tim_raines_2001_stats['HR']}, BB: {tim_raines_2001_stats['BB']}, SO: {tim_raines_2001_stats['SO']}")

    print("\n2. Jack Morris 1983 (Pitcher)")
    print("-" * 70)
    print(f"Record: {jack_morris_1983_stats['W']}-{jack_morris_1983_stats['L']}")
    print(f"ERA: {jack_morris_1983_stats['ERA']:.2f}, IP: {jack_morris_1983_stats['IP']}")
    print(f"SO: {jack_morris_1983_stats['SO']}, BB: {jack_morris_1983_stats['BB']}, H: {jack_morris_1983_stats['H']}")

    print("\n3. Nolan Ryan 1972 (Pitcher)")
    print("-" * 70)
    print(f"Record: {nolan_ryan_1972_stats['W']}-{nolan_ryan_1972_stats['L']}")
    print(f"ERA: {nolan_ryan_1972_stats['ERA']:.2f}, IP: {nolan_ryan_1972_stats['IP']}")
    print(f"SO: {nolan_ryan_1972_stats['SO']}, BB: {nolan_ryan_1972_stats['BB']}, H: {nolan_ryan_1972_stats['H']}")
