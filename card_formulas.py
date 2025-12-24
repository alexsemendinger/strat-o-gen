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
- Batter's card shows deviation from league average (pitcher handles baseline)
"""

from typing import Dict


class BatterCardFormulas:
    """Implements Bundy formulas for batter cards."""

    @staticmethod
    def calculate_pa_effective(stats: Dict) -> int:
        """
        Calculate effective plate appearances (excludes IBB).

        IBB are excluded because they bypass the card system entirely.

        Args:
            stats: Dictionary with batting stats

        Returns:
            Effective PA
        """
        ab = stats.get('AB', 0)
        bb = stats.get('BB', 0)
        ibb = stats.get('IBB', 0)
        hbp = stats.get('HBP', 0)
        sf = stats.get('SF', 0)

        # PA_eff = AB + (BB - IBB) + HBP + SF
        return ab + (bb - ibb) + hbp + sf

    @staticmethod
    def calculate_walk_chances(stats: Dict, pa_eff: int, league_bb_rate: float = 0.085) -> float:
        """
        Calculate walk chances on batter's card.

        The batter's card only gets walks ABOVE what the average pitcher would yield.

        Args:
            stats: Dictionary with batting stats
            pa_eff: Effective plate appearances
            league_bb_rate: League walk rate (non-IBB BB per PA)

        Returns:
            Walk chances out of 108
        """
        if pa_eff == 0:
            return 0.0

        bb = stats.get('BB', 0)
        ibb = stats.get('IBB', 0)
        bb_non_int = bb - ibb

        # Batter's walk rate
        batter_bb_rate = bb_non_int / pa_eff

        # Formula: (batter_rate * 216) - (league_rate * 216)
        # But batter card only has 108 chances, so we adjust
        # The pitcher card handles half the walks at league average rate

        # Total walks in 216 PAs at batter's rate
        total_walks = batter_bb_rate * 216

        # Walks from average pitcher (happens on pitcher's card)
        pitcher_walks = league_bb_rate * 108

        # Remaining walks go on batter's card
        walk_chances = total_walks - pitcher_walks

        return max(0.0, walk_chances)

    @staticmethod
    def calculate_hbp_chances(stats: Dict, pa_eff: int) -> float:
        """
        Calculate hit-by-pitch chances on batter's card.

        HBP only appears on batter's card (not pitcher's card).

        Args:
            stats: Dictionary with batting stats
            pa_eff: Effective plate appearances

        Returns:
            HBP chances out of 108
        """
        if pa_eff == 0:
            return 0.0

        hbp = stats.get('HBP', 0)

        # All HBP goes on batter's card
        hbp_chances = (hbp / pa_eff) * 108

        return max(0.0, hbp_chances)

    @staticmethod
    def calculate_strikeout_chances(stats: Dict, pa_eff: int, league_k_rate: float = 0.20) -> float:
        """
        Calculate strikeout chances on batter's card.

        Similar to walks, only the deviation from league average goes on batter's card.

        Args:
            stats: Dictionary with batting stats
            pa_eff: Effective plate appearances
            league_k_rate: League strikeout rate

        Returns:
            Strikeout chances out of 108
        """
        if pa_eff == 0:
            return 0.0

        so = stats.get('SO', 0)

        # Batter's strikeout rate
        batter_k_rate = so / pa_eff

        # Total strikeouts at batter's rate
        total_k = batter_k_rate * 216

        # Strikeouts from average pitcher
        pitcher_k = league_k_rate * 108

        # Remaining strikeouts on batter's card
        k_chances = total_k - pitcher_k

        return max(0.0, k_chances)

    @staticmethod
    def calculate_homerun_chances(stats: Dict, pa_eff: int, league_hr_rate: float = 0.025) -> float:
        """
        Calculate home run chances on batter's card.

        Args:
            stats: Dictionary with batting stats
            pa_eff: Effective plate appearances
            league_hr_rate: League HR per PA

        Returns:
            Home run chances out of 108
        """
        if pa_eff == 0:
            return 0.0

        hr = stats.get('HR', 0)

        batter_hr_rate = hr / pa_eff
        total_hr = batter_hr_rate * 216
        pitcher_hr = league_hr_rate * 108

        hr_chances = total_hr - pitcher_hr

        return max(0.0, hr_chances)

    @staticmethod
    def calculate_triple_chances(stats: Dict, pa_eff: int, league_3b_rate: float = 0.005) -> float:
        """
        Calculate triple chances on batter's card.

        Args:
            stats: Dictionary with batting stats
            pa_eff: Effective plate appearances
            league_3b_rate: League 3B per PA

        Returns:
            Triple chances out of 108
        """
        if pa_eff == 0:
            return 0.0

        triples = stats.get('3B', 0)

        batter_3b_rate = triples / pa_eff
        total_3b = batter_3b_rate * 216
        pitcher_3b = league_3b_rate * 108

        triple_chances = total_3b - pitcher_3b

        return max(0.0, triple_chances)

    @staticmethod
    def calculate_double_chances(stats: Dict, pa_eff: int, league_2b_rate: float = 0.04) -> float:
        """
        Calculate double chances on batter's card.

        Args:
            stats: Dictionary with batting stats
            pa_eff: Effective plate appearances
            league_2b_rate: League 2B per PA

        Returns:
            Double chances out of 108
        """
        if pa_eff == 0:
            return 0.0

        doubles = stats.get('2B', 0)

        batter_2b_rate = doubles / pa_eff
        total_2b = batter_2b_rate * 216
        pitcher_2b = league_2b_rate * 108

        double_chances = total_2b - pitcher_2b

        return max(0.0, double_chances)

    @staticmethod
    def calculate_single_chances(stats: Dict, pa_eff: int, league_ba: float = 0.250,
                                 hr_chances: float = 0, triple_chances: float = 0,
                                 double_chances: float = 0, league_hr_rate: float = 0.025,
                                 league_2b_rate: float = 0.04, league_3b_rate: float = 0.005) -> float:
        """
        Calculate single chances on batter's card.

        Singles = Total hits - (HR + 3B + 2B)

        Args:
            stats: Dictionary with batting stats
            pa_eff: Effective plate appearances
            league_ba: League batting average
            hr_chances, triple_chances, double_chances: Already calculated
            league_hr_rate, league_2b_rate, league_3b_rate: League XBH rates

        Returns:
            Single chances out of 108
        """
        if pa_eff == 0:
            return 0.0

        h = stats.get('H', 0)
        hr = stats.get('HR', 0)
        triples = stats.get('3B', 0)
        doubles = stats.get('2B', 0)

        # Calculate singles
        singles = h - hr - triples - doubles

        # Rate and chances
        batter_1b_rate = singles / pa_eff if pa_eff > 0 else 0
        total_1b = batter_1b_rate * 216

        # League singles rate (hits per PA minus XBH per PA)
        # BA = H/AB, and AB ≈ PA * 0.85
        league_hits_per_pa = league_ba * 0.85
        league_1b_rate = league_hits_per_pa - league_hr_rate - league_2b_rate - league_3b_rate
        pitcher_1b = league_1b_rate * 108

        single_chances = total_1b - pitcher_1b

        return max(0.0, single_chances)

    @classmethod
    def calculate_batter_card_chances(cls, stats: Dict, league_avg: Dict = None) -> Dict:
        """
        Calculate all outcome chances for a batter's card.

        Args:
            stats: Dictionary of batting stats from StatsFetcher
            league_avg: Optional dict with league averages (BA, HR_rate, etc.)
                       If not provided, uses default/typical values

        Returns:
            Dictionary with chances for each outcome (out of 108)
        """
        # Use default league averages if not provided
        if league_avg is None:
            league_avg = {
                'BA': 0.250,
                'HR_per_PA': 0.025,
                'BB_per_PA': 0.085,
                'K_per_PA': 0.20,
                '2B_per_PA': 0.04,
                '3B_per_PA': 0.005,
            }

        # Calculate effective PA
        pa_eff = cls.calculate_pa_effective(stats)

        # Calculate chances for each outcome
        walk_chances = cls.calculate_walk_chances(stats, pa_eff, league_avg['BB_per_PA'])
        hbp_chances = cls.calculate_hbp_chances(stats, pa_eff)
        strikeout_chances = cls.calculate_strikeout_chances(stats, pa_eff, league_avg['K_per_PA'])
        homerun_chances = cls.calculate_homerun_chances(stats, pa_eff, league_avg['HR_per_PA'])
        triple_chances = cls.calculate_triple_chances(stats, pa_eff, league_avg['3B_per_PA'])
        double_chances = cls.calculate_double_chances(stats, pa_eff, league_avg['2B_per_PA'])
        single_chances = cls.calculate_single_chances(stats, pa_eff, league_avg['BA'],
                                                      homerun_chances, triple_chances, double_chances,
                                                      league_avg['HR_per_PA'], league_avg['2B_per_PA'],
                                                      league_avg['3B_per_PA'])

        # Total hit chances
        hit_total = homerun_chances + triple_chances + double_chances + single_chances

        # Total outcome chances
        outcome_chances = walk_chances + hbp_chances + strikeout_chances + hit_total

        # Remaining chances are outs
        out_chances = 108.0 - outcome_chances

        return {
            'pa_eff': pa_eff,
            'walk': walk_chances,
            'hbp': hbp_chances,
            'strikeout': strikeout_chances,
            'homerun': homerun_chances,
            'triple': triple_chances,
            'double': double_chances,
            'single': single_chances,
            'hit_total': hit_total,
            'outs': out_chances,
            'total': outcome_chances,
            'warnings': cls._generate_warnings(stats, out_chances)
        }

    @staticmethod
    def _generate_warnings(stats: Dict, out_chances: float) -> list:
        """Generate warnings about the card generation."""
        warnings = []

        year = stats.get('year', 0)
        pa = stats.get('PA', 0)

        # Historical data warnings
        if year < 1955:
            warnings.append('IBB not tracked before 1955 (treated as 0)')
        if year < 1954:
            warnings.append('SF not tracked before 1954 (may affect PA calculation)')

        # Sample size
        if pa < 150:
            warnings.append(f'Small sample size ({pa} PA) - card may be unreliable')

        # Out chances warning
        if out_chances < 0:
            warnings.append(f'Negative out chances ({out_chances:.1f}) - too many outcome chances!')
        elif out_chances < 20:
            warnings.append(f'Very few out chances ({out_chances:.1f}) - extreme stat line')

        return warnings


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
    print("=" * 60)
    print("Testing Bundy Formulas - BATTERS")
    print("=" * 60)

    # Test 1: Babe Ruth 1927 - power hitter
    ruth_1927 = {
        'year': 1927,
        'PA': 692,
        'AB': 540,
        'H': 192,
        '2B': 29,
        '3B': 8,
        'HR': 60,
        'BB': 137,
        'IBB': 0,  # Not tracked in 1927
        'SO': 89,
        'HBP': 4,
        'SF': 0,  # Not tracked in 1927
    }

    print("\n1. Babe Ruth 1927 (60 HR, .356 BA)")
    print("-" * 60)
    chances = BatterCardFormulas.calculate_batter_card_chances(ruth_1927)
    print(f"Effective PA: {chances['pa_eff']}")
    print(f"\nChances (out of 108):")
    print(f"  Walks:      {chances['walk']:6.2f}  (high - great eye)")
    print(f"  HBP:        {chances['hbp']:6.2f}")
    print(f"  Strikeouts: {chances['strikeout']:6.2f}")
    print(f"  Home Runs:  {chances['homerun']:6.2f}  (legendary power)")
    print(f"  Triples:    {chances['triple']:6.2f}")
    print(f"  Doubles:    {chances['double']:6.2f}")
    print(f"  Singles:    {chances['single']:6.2f}")
    print(f"  Outs:       {chances['outs']:6.2f}")
    print(f"  TOTAL:      {chances['total'] + chances['outs']:6.2f}")

    # Test 2: Tony Gwynn 1994 - contact hitter
    gwynn_1994 = {
        'year': 1994,
        'PA': 475,
        'AB': 419,
        'H': 165,
        '2B': 35,
        '3B': 1,
        'HR': 12,
        'BB': 48,
        'IBB': 19,
        'SO': 19,  # Very low!
        'HBP': 3,
        'SF': 3,
    }

    print("\n\n2. Tony Gwynn 1994 (.394 BA, 19 SO)")
    print("-" * 60)
    chances = BatterCardFormulas.calculate_batter_card_chances(gwynn_1994)
    print(f"Effective PA: {chances['pa_eff']}")
    print(f"\nChances (out of 108):")
    print(f"  Walks:      {chances['walk']:6.2f}")
    print(f"  Strikeouts: {chances['strikeout']:6.2f}  (very low - contact hitter)")
    print(f"  Home Runs:  {chances['homerun']:6.2f}")
    print(f"  Triples:    {chances['triple']:6.2f}")
    print(f"  Doubles:    {chances['double']:6.2f}")
    print(f"  Singles:    {chances['single']:6.2f}  (high - singles hitter)")
    print(f"  Outs:       {chances['outs']:6.2f}")
    print(f"  TOTAL:      {chances['total'] + chances['outs']:6.2f}")

    print("\n\n" + "=" * 60)
    print("Testing Bundy Formulas - PITCHERS")
    print("=" * 60)

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

    print("\n1. Sandy Koufax 1965 (26-8, 2.04 ERA, 382 SO)")
    print("-" * 60)
    chances = PitcherCardFormulas.calculate_pitcher_card_chances(koufax_1965)
    print(f"Total Batters Faced: {chances['tbf']:.0f}")
    print(f"\nChances (out of 108):")
    print(f"  Walks:      {chances['walk']:6.2f}")
    print(f"  Strikeouts: {chances['strikeout']:6.2f}  (dominant)")
    print(f"  Home Runs:  {chances['homerun']:6.2f}")
    print(f"  Hits:       {chances['hit_total']:6.2f}  (very low)")
    print(f"  Outs:       {chances['outs']:6.2f}")
    print(f"  TOTAL:      {chances['total'] + chances['outs']:6.2f}")
