"""
Card validation through simulation.

This module simulates plate appearances using generated cards and verifies
that the simulated statistics match the original player statistics.

This is the most important validation - if cards don't reproduce stats in
simulation, the formulas are wrong regardless of what they look like.
"""

import random
from typing import Dict, Tuple
from card_formulas import BatterCardFormulas, PitcherCardFormulas


class CardSimulator:
    """Simulates Strat-O-Matic gameplay to validate card accuracy."""

    def __init__(self):
        """Initialize the simulator."""
        self.reset_stats()

    def reset_stats(self):
        """Reset accumulated statistics."""
        self.stats = {
            'PA': 0,
            'AB': 0,
            'H': 0,
            '1B': 0,
            '2B': 0,
            '3B': 0,
            'HR': 0,
            'BB': 0,
            'HBP': 0,
            'SO': 0,
            'outs': 0,
        }

    def roll_dice(self) -> Tuple[int, int]:
        """
        Roll the Strat-O-Matic dice.

        Returns:
            (control_die, result_die) where:
            - control_die: 1-6 (1-3 = batter card, 4-6 = pitcher card)
            - result_die: 2-12 (sum of two dice)
        """
        control = random.randint(1, 6)
        die1 = random.randint(1, 6)
        die2 = random.randint(1, 6)
        result = die1 + die2

        return control, result

    def simulate_pa_from_chances(self, batter_chances: Dict, pitcher_chances: Dict) -> str:
        """
        Simulate one plate appearance given batter and pitcher card chances.

        This is a simplified simulation that uses the calculated chances directly,
        without needing the full card layout.

        Args:
            batter_chances: Dict from BatterCardFormulas.calculate_batter_card_chances()
            pitcher_chances: Dict from PitcherCardFormulas.calculate_pitcher_card_chances()

        Returns:
            Outcome string: 'HR', '3B', '2B', '1B', 'BB', 'HBP', 'SO', 'OUT'
        """
        control, _ = self.roll_dice()

        # Determine which card to use
        if control <= 3:
            # Use batter's card
            return self._get_outcome_from_chances(batter_chances)
        else:
            # Use pitcher's card
            return self._get_outcome_from_chances(pitcher_chances)

    def _get_outcome_from_chances(self, chances: Dict) -> str:
        """
        Pick an outcome based on the probability distribution in chances.

        Args:
            chances: Dictionary with chances for each outcome (out of 108)

        Returns:
            Outcome string
        """
        # Build probability distribution
        outcomes = []
        weights = []

        # Add each outcome with its weight
        if chances.get('homerun', 0) > 0:
            outcomes.append('HR')
            weights.append(chances['homerun'])

        if chances.get('triple', 0) > 0:
            outcomes.append('3B')
            weights.append(chances['triple'])

        if chances.get('double', 0) > 0:
            outcomes.append('2B')
            weights.append(chances['double'])

        if chances.get('single', 0) > 0:
            outcomes.append('1B')
            weights.append(chances['single'])

        if chances.get('walk', 0) > 0:
            outcomes.append('BB')
            weights.append(chances['walk'])

        if chances.get('hbp', 0) > 0:
            outcomes.append('HBP')
            weights.append(chances['hbp'])

        if chances.get('strikeout', 0) > 0:
            outcomes.append('SO')
            weights.append(chances['strikeout'])

        if chances.get('outs', 0) > 0:
            outcomes.append('OUT')
            weights.append(chances['outs'])

        # Random weighted choice
        if not outcomes:
            return 'OUT'

        return random.choices(outcomes, weights=weights, k=1)[0]

    def simulate_season(self, batter_chances: Dict, pitcher_chances: Dict,
                       num_pa: int = 10000) -> Dict:
        """
        Simulate a season's worth of plate appearances.

        Args:
            batter_chances: Batter's card chances
            pitcher_chances: Pitcher's card chances (average pitcher)
            num_pa: Number of plate appearances to simulate

        Returns:
            Dictionary of accumulated statistics
        """
        self.reset_stats()

        for _ in range(num_pa):
            outcome = self.simulate_pa_from_chances(batter_chances, pitcher_chances)

            # Update stats
            self.stats['PA'] += 1

            if outcome == 'HR':
                self.stats['AB'] += 1
                self.stats['H'] += 1
                self.stats['HR'] += 1
            elif outcome == '3B':
                self.stats['AB'] += 1
                self.stats['H'] += 1
                self.stats['3B'] += 1
            elif outcome == '2B':
                self.stats['AB'] += 1
                self.stats['H'] += 1
                self.stats['2B'] += 1
            elif outcome == '1B':
                self.stats['AB'] += 1
                self.stats['H'] += 1
                self.stats['1B'] += 1
            elif outcome == 'BB':
                self.stats['BB'] += 1
            elif outcome == 'HBP':
                self.stats['HBP'] += 1
            elif outcome == 'SO':
                self.stats['AB'] += 1
                self.stats['SO'] += 1
            elif outcome == 'OUT':
                self.stats['AB'] += 1
                self.stats['outs'] += 1

        return self.stats

    def calculate_rate_stats(self, stats: Dict) -> Dict:
        """
        Calculate rate statistics from counting stats.

        Args:
            stats: Dictionary of counting stats

        Returns:
            Dictionary with added rate stats
        """
        result = stats.copy()

        if stats['AB'] > 0:
            result['BA'] = stats['H'] / stats['AB']
        else:
            result['BA'] = 0.0

        if stats['PA'] > 0:
            result['HR_rate'] = stats['HR'] / stats['PA']
            result['BB_rate'] = stats['BB'] / stats['PA']
            result['SO_rate'] = stats['SO'] / stats['PA']
        else:
            result['HR_rate'] = 0.0
            result['BB_rate'] = 0.0
            result['SO_rate'] = 0.0

        return result


class CardValidator:
    """Validates generated cards by comparing simulated vs actual stats."""

    def __init__(self, num_simulations: int = 10000):
        """
        Initialize the validator.

        Args:
            num_simulations: Number of PAs to simulate (more = more accurate)
        """
        self.simulator = CardSimulator()
        self.num_simulations = num_simulations

    def validate_batter_card(self, original_stats: Dict, batter_chances: Dict,
                           pitcher_chances: Dict = None, tolerance: float = 0.015) -> Dict:
        """
        Validate a batter's card by simulation.

        Args:
            original_stats: The player's actual statistics
            batter_chances: Generated card chances from BatterCardFormulas
            pitcher_chances: Average pitcher card chances (or None to generate default)
            tolerance: Acceptable difference in rate stats (e.g., 0.015 = 1.5%)

        Returns:
            Validation results dictionary
        """
        # Generate average pitcher card if not provided
        if pitcher_chances is None:
            pitcher_chances = self._get_average_pitcher_chances()

        # Run simulation
        sim_stats = self.simulator.simulate_season(
            batter_chances, pitcher_chances, self.num_simulations
        )

        # Calculate rate stats
        sim_with_rates = self.simulator.calculate_rate_stats(sim_stats)

        # Compare to original
        pa_eff = batter_chances.get('pa_eff', original_stats.get('PA', 0))

        # Calculate original rates
        orig_ba = original_stats.get('BA', 0.0)
        orig_hr_rate = original_stats.get('HR', 0) / pa_eff if pa_eff > 0 else 0
        orig_bb = original_stats.get('BB', 0) - original_stats.get('IBB', 0)
        orig_bb_rate = orig_bb / pa_eff if pa_eff > 0 else 0
        orig_so_rate = original_stats.get('SO', 0) / pa_eff if pa_eff > 0 else 0

        # Calculate differences
        ba_diff = abs(sim_with_rates['BA'] - orig_ba)
        hr_diff = abs(sim_with_rates['HR_rate'] - orig_hr_rate)
        bb_diff = abs(sim_with_rates['BB_rate'] - orig_bb_rate)
        so_diff = abs(sim_with_rates['SO_rate'] - orig_so_rate)

        # Check if within tolerance
        ba_ok = ba_diff <= tolerance
        hr_ok = hr_diff <= tolerance
        bb_ok = bb_diff <= tolerance
        so_ok = so_diff <= tolerance

        all_ok = ba_ok and hr_ok and bb_ok and so_ok

        return {
            'passed': all_ok,
            'simulated_stats': sim_with_rates,
            'original_stats': {
                'BA': orig_ba,
                'HR_rate': orig_hr_rate,
                'BB_rate': orig_bb_rate,
                'SO_rate': orig_so_rate,
            },
            'differences': {
                'BA': ba_diff,
                'HR_rate': hr_diff,
                'BB_rate': bb_diff,
                'SO_rate': so_diff,
            },
            'checks': {
                'BA': ba_ok,
                'HR_rate': hr_ok,
                'BB_rate': bb_ok,
                'SO_rate': so_ok,
            },
            'tolerance': tolerance,
        }

    def _get_average_pitcher_chances(self) -> Dict:
        """
        Generate chances for a league-average pitcher.

        This is a simplified average pitcher using default league rates.
        """
        # Create average pitcher stats
        avg_pitcher_stats = {
            'year': 2000,  # Doesn't matter for average
            'IP': 200.0,
            'TBF': 850,
            'H': 212,  # ~.250 BA
            'BB': 72,  # ~8.5% walk rate
            'IBB': 5,
            'SO': 170,  # ~20% K rate
            'HR': 21,  # ~2.5% HR rate
            '2B': 0,
            '3B': 0,
        }

        return PitcherCardFormulas.calculate_pitcher_card_chances(avg_pitcher_stats)

    def print_validation_report(self, validation_result: Dict, player_name: str = "Player"):
        """
        Print a formatted validation report.

        Args:
            validation_result: Result from validate_batter_card()
            player_name: Name to display in report
        """
        print("=" * 70)
        print(f"VALIDATION REPORT: {player_name}")
        print("=" * 70)

        sim = validation_result['simulated_stats']
        orig = validation_result['original_stats']
        diff = validation_result['differences']
        checks = validation_result['checks']
        tol = validation_result['tolerance']

        print(f"\nSimulated {sim['PA']} plate appearances")
        print(f"Tolerance: ±{tol:.3f} ({tol*100:.1f}%)\n")

        print(f"{'Stat':<15} {'Original':>10} {'Simulated':>10} {'Diff':>10} {'Status':>10}")
        print("-" * 70)

        def format_row(stat_name, orig_val, sim_val, diff_val, passed):
            status = "✓ PASS" if passed else "✗ FAIL"
            return f"{stat_name:<15} {orig_val:>10.3f} {sim_val:>10.3f} {diff_val:>10.3f} {status:>10}"

        print(format_row("BA", orig['BA'], sim['BA'], diff['BA'], checks['BA']))
        print(format_row("HR rate", orig['HR_rate'], sim['HR_rate'], diff['HR_rate'], checks['HR_rate']))
        print(format_row("BB rate", orig['BB_rate'], sim['BB_rate'], diff['BB_rate'], checks['BB_rate']))
        print(format_row("SO rate", orig['SO_rate'], sim['SO_rate'], diff['SO_rate'], checks['SO_rate']))

        print("\n" + "=" * 70)
        if validation_result['passed']:
            print("✓ VALIDATION PASSED - Card reproduces player stats")
        else:
            print("✗ VALIDATION FAILED - Card does not reproduce player stats")
        print("=" * 70)


# Test the validator
if __name__ == "__main__":
    print("Testing Card Validator with Babe Ruth 1927\n")

    # Babe Ruth 1927 stats
    ruth_stats = {
        'year': 1927,
        'PA': 692,
        'AB': 540,
        'H': 192,
        '2B': 29,
        '3B': 8,
        'HR': 60,
        'BB': 137,
        'IBB': 0,
        'SO': 89,
        'HBP': 4,
        'SF': 0,
        'BA': 0.356,
    }

    # Generate card
    batter_chances = BatterCardFormulas.calculate_batter_card_chances(ruth_stats)

    # Validate
    validator = CardValidator(num_simulations=50000)  # Use 50k for better accuracy
    result = validator.validate_batter_card(ruth_stats, batter_chances)

    # Print report
    validator.print_validation_report(result, "Babe Ruth 1927")
