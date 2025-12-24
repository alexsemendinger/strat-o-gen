"""
Fielding location assignment for Strat-O-Matic cards.

Assigns outs to specific fielding positions and types based on league-average
distributions and weighted random selection.
"""

import random
from typing import Dict, Tuple


# League average batted ball type distribution
# Based on modern MLB averages (~2019-2024)
BATTED_BALL_DISTRIBUTION = {
    'groundball': 0.43,  # ~43% ground balls
    'flyball': 0.35,     # ~35% fly balls (excluding line drives)
    'linedrive': 0.21,   # ~21% line drives
    'popup': 0.01,       # ~1% popups (included in flyballs, separated here)
}

# Ground ball distribution by infield position
# SS gets most (right-handed pull tendency), followed by 2B, 3B, 1B, P
GROUNDBALL_POSITIONS = {
    '1b': 0.15,   # First baseman
    '2b': 0.28,   # Second baseman
    '3b': 0.20,   # Third baseman
    'ss': 0.32,   # Shortstop (most ground balls)
    'p': 0.05,    # Pitcher
}

# Fly ball distribution by outfield position
# CF gets most, followed by LF, RF
FLYBALL_POSITIONS = {
    'lf': 0.32,   # Left field
    'cf': 0.40,   # Center field (most fly balls)
    'rf': 0.28,   # Right field
}

# Line drive distribution (can go anywhere)
# More to outfield than infield
LINEDRIVE_POSITIONS = {
    '1b': 0.08,
    '2b': 0.10,
    '3b': 0.08,
    'ss': 0.10,
    'lf': 0.20,
    'cf': 0.22,
    'rf': 0.18,
    'p': 0.04,
}

# Popup distribution (mostly infield + catcher)
POPUP_POSITIONS = {
    'c': 0.25,    # Catcher
    '1b': 0.15,
    '2b': 0.15,
    '3b': 0.15,
    'ss': 0.15,
    'p': 0.10,
    'lf': 0.02,
    'cf': 0.02,
    'rf': 0.01,
}

# Ground ball ratings (double-play potential)
# A = high DP potential, B = medium, C = low
GROUNDBALL_RATINGS = {
    'A': 0.40,  # 40% high DP potential
    'B': 0.35,  # 35% medium
    'C': 0.25,  # 25% low/no DP
}

# Fly ball ratings (advancement potential)
# A = deep (all runners advance), B = medium depth, C = shallow
FLYBALL_RATINGS = {
    'A': 0.20,  # 20% deep flies
    'B': 0.40,  # 40% medium depth
    'C': 0.40,  # 40% shallow
}


class FieldingLocationAssigner:
    """Assigns fielding locations to outs using weighted random selection."""

    @staticmethod
    def assign_out_type() -> str:
        """
        Randomly assign a batted ball type based on league distributions.

        Returns:
            One of: 'groundball', 'flyball', 'linedrive', 'popup'
        """
        rand = random.random()
        cumulative = 0.0

        for out_type, prob in BATTED_BALL_DISTRIBUTION.items():
            cumulative += prob
            if rand < cumulative:
                return out_type

        return 'groundball'  # Fallback

    @staticmethod
    def assign_position(out_type: str) -> str:
        """
        Randomly assign a fielding position based on out type.

        Args:
            out_type: Type of batted ball

        Returns:
            Fielding position abbreviation (1B, 2B, 3B, SS, LF, CF, RF, C, P)
        """
        if out_type == 'groundball':
            distribution = GROUNDBALL_POSITIONS
        elif out_type == 'flyball':
            distribution = FLYBALL_POSITIONS
        elif out_type == 'linedrive':
            distribution = LINEDRIVE_POSITIONS
        elif out_type == 'popup':
            distribution = POPUP_POSITIONS
        else:
            distribution = GROUNDBALL_POSITIONS

        rand = random.random()
        cumulative = 0.0

        for position, prob in distribution.items():
            cumulative += prob
            if rand < cumulative:
                return position

        return list(distribution.keys())[0]  # Fallback

    @staticmethod
    def assign_groundball_rating() -> str:
        """
        Randomly assign a ground ball rating (A/B/C).

        Returns:
            'A', 'B', or 'C'
        """
        rand = random.random()
        cumulative = 0.0

        for rating, prob in GROUNDBALL_RATINGS.items():
            cumulative += prob
            if rand < cumulative:
                return rating

        return 'B'  # Fallback

    @staticmethod
    def assign_flyball_rating() -> str:
        """
        Randomly assign a fly ball rating (A/B/C).

        Returns:
            'A', 'B', or 'C'
        """
        rand = random.random()
        cumulative = 0.0

        for rating, prob in FLYBALL_RATINGS.items():
            cumulative += prob
            if rand < cumulative:
                return rating

        return 'B'  # Fallback

    @classmethod
    def generate_out_result(cls, for_pitcher: bool = False) -> str:
        """
        Generate a complete out result with fielding location.

        Args:
            for_pitcher: If True, use pitcher card format (UPPERCASE, X rating)

        Returns:
            Formatted out string
            - Batter: "groundball (2b)A", "flyball (cf)B", "lineout (lf)"
            - Pitcher: "GROUNDBALL(2b)X", "FLYBALL(cf)X", "lineout (lf)"
        """
        out_type = cls.assign_out_type()
        position = cls.assign_position(out_type)

        if for_pitcher:
            # Pitcher card format: UPPERCASE, X rating, no space before position
            if out_type == 'groundball':
                return f"GROUNDBALL({position})X"
            elif out_type == 'flyball':
                return f"FLYBALL({position})X"
            elif out_type == 'linedrive':
                return f"lineout ({position})"
            elif out_type == 'popup':
                return f"popout ({position})"
            else:
                return "OUT"
        else:
            # Batter card format: lowercase, A/B/C rating
            if out_type == 'groundball':
                rating = cls.assign_groundball_rating()
                return f"groundball ({position}){rating}"
            elif out_type == 'flyball':
                rating = cls.assign_flyball_rating()
                return f"flyball ({position}){rating}"
            elif out_type == 'linedrive':
                return f"lineout ({position})"
            elif out_type == 'popup':
                return f"popout ({position})"
            else:
                return "OUT"  # Fallback

    @classmethod
    def generate_multiple_outs(cls, count: int) -> Dict[str, int]:
        """
        Generate multiple outs and return distribution.

        Args:
            count: Number of outs to generate

        Returns:
            Dictionary mapping out result strings to counts
        """
        results = {}
        for _ in range(int(count)):
            result = cls.generate_out_result()
            results[result] = results.get(result, 0) + 1
        return results


if __name__ == "__main__":
    # Test the fielding location assigner
    print("Testing Fielding Location Assignment")
    print("=" * 70)

    # Generate 1000 outs to see the distribution
    assigner = FieldingLocationAssigner()
    outs = assigner.generate_multiple_outs(1000)

    # Count by type
    gb_count = sum(v for k, v in outs.items() if k.startswith('gb'))
    fb_count = sum(v for k, v in outs.items() if k.startswith('fly'))
    ld_count = sum(v for k, v in outs.items() if k.startswith('line'))
    pu_count = sum(v for k, v in outs.items() if k.startswith('popup'))

    print(f"\nBatted Ball Type Distribution (1000 outs):")
    print(f"  Ground balls: {gb_count} ({gb_count/10:.1f}%)")
    print(f"  Fly balls:    {fb_count} ({fb_count/10:.1f}%)")
    print(f"  Line drives:  {ld_count} ({ld_count/10:.1f}%)")
    print(f"  Popups:       {pu_count} ({pu_count/10:.1f}%)")

    print(f"\nSample results:")
    for result, count in sorted(outs.items(), key=lambda x: -x[1])[:15]:
        print(f"  {result:20s}: {count:3d} ({count/10:.1f}%)")
