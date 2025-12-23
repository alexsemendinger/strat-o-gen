"""
Bundy formulas for generating Strat-O-Matic cards.

These are community-reverse-engineered formulas from Bruce Bundy's work.
They are approximations, not official Strat-O-Matic formulas.

Sources:
- https://www.somworld.com/2003/bundy1.htm
- Community research and refinements

Key concepts:
- Cards have 108 chances total (3 columns × 36 weighted chances each)
- Full cycle (batter + pitcher) = 216 chances
- Results are split 50/50 between batter and pitcher cards
"""

from typing import Dict


class PitcherCardFormulas:
    """Implements Bundy formulas for pitcher cards."""

    @staticmethod
    def calculate_tbf(stats: Dict) -> float:
        """
        Formula #15: Calculate Total Batters Faced.

        If TBF is already in stats (from Baseball Reference), use it.
        Otherwise estimate from innings pitched.

        Args:
            stats: Dictionary with pitching stats (IP, H, BB, IBB)

        Returns:
            Total batters faced
        """
        # If we have actual TBF from Baseball Reference, use it
        if stats.get('TBF', 0) > 0:
            return float(stats['TBF'])

        # Otherwise estimate using Bundy's formula
        # TBF = (IP * 2.95) + H + (BB - IBB)
        ip = stats.get('IP', 0.0)
        h = stats.get('H', 0)
        bb = stats.get('BB', 0)
        ibb = stats.get('IBB', 0)

        return (ip * 2.95) + h + (bb - ibb)

    @staticmethod
    def calculate_walk_chances(stats: Dict, tbf: float) -> float:
        """
        Formula #16: Calculate walk chances on pitcher's card.

        sompW = ((BB - IBB) * 216) / (TBF - IBB)) - 9

        Args:
            stats: Dictionary with pitching stats
            tbf: Total batters faced

        Returns:
            Walk chances out of 108
        """
        bb = stats.get('BB', 0)
        ibb = stats.get('IBB', 0)

        if tbf <= ibb:
            return 0.0

        # Non-intentional walks
        bb_non_int = bb - ibb
        tbf_adj = tbf - ibb

        # Formula: ((BB-IBB) * 216 / (TBF-IBB)) - 9
        walk_chances = ((bb_non_int * 216) / tbf_adj) - 9

        # Can't have negative chances
        return max(0.0, walk_chances)

    @staticmethod
    def calculate_strikeout_chances(stats: Dict, tbf: float) -> float:
        """
        Formula #21: Calculate strikeout chances on pitcher's card.

        sompK = (SO * 216) / (TBF - IBB)

        Args:
            stats: Dictionary with pitching stats
            tbf: Total batters faced

        Returns:
            Strikeout chances out of 108
        """
        so = stats.get('SO', 0)
        ibb = stats.get('IBB', 0)

        if tbf <= ibb:
            return 0.0

        tbf_adj = tbf - ibb

        # Formula: (SO * 216) / (TBF - IBB)
        strikeout_chances = (so * 216) / tbf_adj

        return max(0.0, strikeout_chances)

    @staticmethod
    def calculate_homerun_chances(stats: Dict, tbf: float) -> float:
        """
        Formula #20: Calculate home run chances on pitcher's card.

        sompHR = ((HR * 216) / (TBF - IBB)) - 50

        Args:
            stats: Dictionary with pitching stats
            tbf: Total batters faced

        Returns:
            Home run chances out of 108
        """
        hr = stats.get('HR', 0)
        ibb = stats.get('IBB', 0)

        if tbf <= ibb:
            return 0.0

        tbf_adj = tbf - ibb

        # Formula: ((HR * 216) / (TBF - IBB)) - 50
        hr_chances = ((hr * 216) / tbf_adj) - 50

        return max(0.0, hr_chances)

    @staticmethod
    def calculate_hit_chances(stats: Dict, tbf: float, walk_chances: float,
                             xchart_factor: float = 4.9) -> float:
        """
        Formula #17a: Calculate hit chances on pitcher's card.

        sompH = (((H / TBF) * 216) - 29.4) + XF

        where XF is the X-chart factor (default 4.9)

        Args:
            stats: Dictionary with pitching stats
            tbf: Total batters faced
            walk_chances: Already calculated walk chances
            xchart_factor: X-chart adjustment factor

        Returns:
            Hit chances out of 108
        """
        h = stats.get('H', 0)

        if tbf == 0:
            return 0.0

        # Formula #17a: (((H / TBF) * 216) - 29.4) + XF
        hit_rate = h / tbf
        hit_chances = ((hit_rate * 216) - 29.4) + xchart_factor

        return max(0.0, hit_chances)

    @staticmethod
    def calculate_double_chances(stats: Dict, tbf: float) -> float:
        """
        Formula #18: Calculate double chances on pitcher's card.

        sompD = ((2B * 216) / (TBF - IBB)) - 90

        Note: 2B allowed is often not available. Returns 0 if missing.

        Args:
            stats: Dictionary with pitching stats
            tbf: Total batters faced

        Returns:
            Double chances out of 108
        """
        doubles = stats.get('2B', 0)
        ibb = stats.get('IBB', 0)

        if tbf <= ibb or doubles == 0:
            return 0.0

        tbf_adj = tbf - ibb

        # Formula: ((2B * 216) / (TBF - IBB)) - 90
        double_chances = ((doubles * 216) / tbf_adj) - 90

        return max(0.0, double_chances)

    @staticmethod
    def calculate_triple_chances(stats: Dict, tbf: float) -> float:
        """
        Formula #19: Calculate triple chances on pitcher's card.

        sompT = ((3B * 216) / (TBF - IBB)) - 15

        Note: 3B allowed is often not available. Returns 0 if missing.

        Args:
            stats: Dictionary with pitching stats
            tbf: Total batters faced

        Returns:
            Triple chances out of 108
        """
        triples = stats.get('3B', 0)
        ibb = stats.get('IBB', 0)

        if tbf <= ibb or triples == 0:
            return 0.0

        tbf_adj = tbf - ibb

        # Formula: ((3B * 216) / (TBF - IBB)) - 15
        triple_chances = ((triples * 216) / tbf_adj) - 15

        return max(0.0, triple_chances)

    @classmethod
    def calculate_pitcher_card_chances(cls, stats: Dict) -> Dict:
        """
        Calculate all outcome chances for a pitcher's card.

        Args:
            stats: Dictionary of pitching stats from StatsFetcher

        Returns:
            Dictionary with chances for each outcome (out of 108)
        """
        # First, get or calculate TBF
        tbf = cls.calculate_tbf(stats)

        # Calculate chances for each outcome
        walk_chances = cls.calculate_walk_chances(stats, tbf)
        strikeout_chances = cls.calculate_strikeout_chances(stats, tbf)
        homerun_chances = cls.calculate_homerun_chances(stats, tbf)
        hit_chances = cls.calculate_hit_chances(stats, tbf, walk_chances)
        double_chances = cls.calculate_double_chances(stats, tbf)
        triple_chances = cls.calculate_triple_chances(stats, tbf)

        # Singles are hits minus extra base hits
        # For now, we'll calculate this after we have the total
        single_chances = hit_chances - double_chances - triple_chances - homerun_chances
        single_chances = max(0.0, single_chances)

        # Calculate outcome chances
        outcome_chances = walk_chances + strikeout_chances + homerun_chances + hit_chances

        # Remaining chances are outs (fielding chances)
        # Pitcher cards traditionally have 30 fielding chances
        out_chances = 108.0 - outcome_chances

        return {
            'tbf': tbf,
            'walk': walk_chances,
            'strikeout': strikeout_chances,
            'homerun': homerun_chances,
            'triple': triple_chances,
            'double': double_chances,
            'single': single_chances,
            'hit_total': hit_chances,
            'outs': out_chances,
            'total': outcome_chances,
            'warnings': cls._generate_warnings(stats, out_chances)
        }

    @staticmethod
    def _generate_warnings(stats: Dict, out_chances: float) -> list:
        """Generate warnings about the card generation."""
        warnings = []

        year = stats.get('year', 0)

        # Historical data warnings
        if year < 1955:
            warnings.append('IBB not tracked before 1955 (treated as 0)')

        # Missing data
        if stats.get('2B', 0) == 0:
            warnings.append('2B allowed not available (double chances may be underestimated)')
        if stats.get('3B', 0) == 0:
            warnings.append('3B allowed not available (triple chances may be underestimated)')

        # Out chances warning
        if out_chances < 0:
            warnings.append(f'Negative out chances ({out_chances:.1f}) - too many outcome chances!')
        elif out_chances < 20:
            warnings.append(f'Very few out chances ({out_chances:.1f}) - high strikeout/walk pitcher')

        return warnings


# Test function
if __name__ == "__main__":
    # Test with Sandy Koufax 1965
    koufax_1965 = {
        'year': 1965,
        'IP': 335.2,
        'TBF': 1297,
        'H': 216,
        'BB': 71,
        'IBB': 4,
        'SO': 382,
        'HR': 26,
        '2B': 0,  # Not available
        '3B': 0,  # Not available
    }

    print("=" * 60)
    print("Testing Bundy Pitcher Formulas")
    print("=" * 60)
    print("\nSandy Koufax 1965 (26-8, 2.04 ERA, 382 SO)")
    print("-" * 60)

    chances = PitcherCardFormulas.calculate_pitcher_card_chances(koufax_1965)

    print(f"\nTotal Batters Faced: {chances['tbf']:.0f}")
    print(f"\nChances (out of 108):")
    print(f"  Walks:      {chances['walk']:6.2f}")
    print(f"  Strikeouts: {chances['strikeout']:6.2f}")
    print(f"  Home Runs:  {chances['homerun']:6.2f}")
    print(f"  Triples:    {chances['triple']:6.2f}")
    print(f"  Doubles:    {chances['double']:6.2f}")
    print(f"  Singles:    {chances['single']:6.2f}")
    print(f"  -----------")
    print(f"  Total Hits: {chances['hit_total']:6.2f}")
    print(f"  Outs:       {chances['outs']:6.2f}")
    print(f"  -----------")
    print(f"  TOTAL:      {chances['total'] + chances['outs']:6.2f}")

    if chances['warnings']:
        print(f"\nWarnings:")
        for warning in chances['warnings']:
            print(f"  - {warning}")
