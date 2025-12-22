"""Card generation engine - converts player stats to Strat-O-Matic card."""

import math
from typing import Dict, List, Tuple

import config


class CardEngine:
    """Generates Strat-O-Matic cards from player statistics."""

    def __init__(self):
        """Initialize card engine."""
        pass

    def generate_card(self, player_stats: Dict, league_avg: Dict) -> Dict:
        """
        Generate a complete Strat-O-Matic card from player statistics.

        Args:
            player_stats: Player's season statistics
            league_avg: League average statistics for the year

        Returns:
            Complete card data including grid, ratings, and metadata
        """
        # Calculate card chances for each outcome
        chances = self.calculate_chances(player_stats, league_avg)

        # Place results on the card grid
        grid = self.create_card_grid(chances)

        # Calculate ratings
        ratings = self.calculate_ratings(player_stats)

        # Determine confidence level
        confidence = self.assess_confidence(player_stats, chances)

        return {
            'player_name': player_stats.get('player_name', 'Unknown'),
            'player_id': player_stats.get('player_id', ''),
            'year': player_stats.get('year', 0),
            'team': player_stats.get('team', ''),
            'league': player_stats.get('league', ''),
            'stats': {
                'AVG': player_stats.get('BA', 0.0),
                'HR': player_stats.get('HR', 0),
                'RBI': player_stats.get('RBI', 0),
                'R': player_stats.get('R', 0),
                'H': player_stats.get('H', 0),
                'PA': player_stats.get('PA', 0),
            },
            'positions': player_stats.get('positions', ['Unknown']),
            'bats': player_stats.get('bats', 'R'),
            'throws': player_stats.get('throws', 'R'),
            'grid': grid,
            'ratings': ratings,
            'chances': chances,
            'confidence': confidence,
            'warnings': player_stats.get('warnings', [])
        }

    def calculate_chances(self, stats: Dict, league_avg: Dict) -> Dict:
        """
        Calculate the number of chances (out of 108) for each outcome on batter's card.

        This implements a modified Bundy formula approach that accounts for:
        - Player's performance relative to league average
        - The 50/50 split between batter and pitcher cards
        - Era-appropriate adjustments
        """
        # Calculate effective PA (exclude IBB as they bypass the card)
        ibb = stats.get('IBB') or 0
        pa_eff = stats['PA'] - ibb

        if pa_eff <= 0:
            return self._get_empty_chances()

        # Initialize chances dictionary
        chances = {}

        # HOME RUNS
        # HR appear on both batter and pitcher cards
        # Batter card gets the player's share above average
        player_hr_rate = stats['HR'] / pa_eff
        league_hr_rate = league_avg.get('HR_per_PA', 0.025)

        # Total HR in full cycle = player_hr_rate * 216
        # Pitcher contribution ≈ league_hr_rate * 108
        # Batter contribution = remaining
        hr_chances = (player_hr_rate * config.TOTAL_CYCLE_CHANCES) - (league_hr_rate * config.TOTAL_BATTER_CHANCES)
        chances['HOMERUN'] = max(0, hr_chances)

        # TRIPLES
        player_3b_rate = stats['3B'] / pa_eff
        league_3b_rate = league_avg.get('3B_per_PA', 0.005)
        triple_chances = (player_3b_rate * config.TOTAL_CYCLE_CHANCES) - (league_3b_rate * config.TOTAL_BATTER_CHANCES)
        chances['TRIPLE'] = max(0, triple_chances)

        # DOUBLES
        player_2b_rate = stats['2B'] / pa_eff
        league_2b_rate = league_avg.get('2B_per_PA', 0.040)
        double_chances = (player_2b_rate * config.TOTAL_CYCLE_CHANCES) - (league_2b_rate * config.TOTAL_BATTER_CHANCES)
        chances['DOUBLE'] = max(0, double_chances)

        # SINGLES
        # Calculate from total hits minus extra base hits
        singles = stats['H'] - stats['2B'] - stats['3B'] - stats['HR']
        player_1b_rate = singles / pa_eff
        league_1b_rate = league_avg.get('BA', 0.250) - league_2b_rate - league_3b_rate - league_hr_rate
        single_chances = (player_1b_rate * config.TOTAL_CYCLE_CHANCES) - (league_1b_rate * config.TOTAL_BATTER_CHANCES)
        chances['SINGLE'] = max(0, single_chances)

        # WALKS (non-intentional)
        bb_non_int = stats['BB'] - ibb
        player_bb_rate = bb_non_int / pa_eff
        league_bb_rate = league_avg.get('BB_per_PA', 0.085)
        walk_chances = (player_bb_rate * config.TOTAL_CYCLE_CHANCES) - (league_bb_rate * config.TOTAL_BATTER_CHANCES)
        chances['WALK'] = max(0, walk_chances)

        # HBP (only appears on batter card)
        hbp = stats.get('HBP') or 0
        hbp_chances = (hbp / pa_eff) * config.TOTAL_BATTER_CHANCES
        chances['HBP'] = max(0, hbp_chances)

        # STRIKEOUTS
        player_k_rate = stats['SO'] / pa_eff
        league_k_rate = league_avg.get('K_per_PA', 0.200)
        k_chances = (player_k_rate * config.TOTAL_CYCLE_CHANCES) - (league_k_rate * config.TOTAL_BATTER_CHANCES)
        chances['STRIKEOUT'] = max(0, k_chances)

        # OUTS (everything else)
        # Total positive outcomes
        positive_chances = (
            chances['HOMERUN'] + chances['TRIPLE'] + chances['DOUBLE'] +
            chances['SINGLE'] + chances['WALK'] + chances['HBP']
        )

        # Outs = 108 - positive outcomes - strikeouts
        out_chances = config.TOTAL_BATTER_CHANCES - positive_chances - chances['STRIKEOUT']
        chances['OUT'] = max(0, out_chances)

        # Normalize to ensure we have exactly 108 chances
        chances = self._normalize_chances(chances)

        return chances

    def _get_empty_chances(self) -> Dict:
        """Return a default card with all outs."""
        return {
            'HOMERUN': 0,
            'TRIPLE': 0,
            'DOUBLE': 0,
            'SINGLE': 0,
            'WALK': 0,
            'HBP': 0,
            'STRIKEOUT': 0,
            'OUT': 108
        }

    def _normalize_chances(self, chances: Dict) -> Dict:
        """Ensure chances sum to exactly 108."""
        total = sum(chances.values())

        if abs(total - config.TOTAL_BATTER_CHANCES) < 0.01:
            return chances

        # If total is off, adjust outs proportionally
        difference = config.TOTAL_BATTER_CHANCES - total

        # Add difference to outs
        chances['OUT'] = max(0, chances['OUT'] + difference)

        # If still not right, do proportional adjustment
        total = sum(chances.values())
        if abs(total - config.TOTAL_BATTER_CHANCES) > 0.01:
            factor = config.TOTAL_BATTER_CHANCES / total
            for key in chances:
                chances[key] = chances[key] * factor

        return chances

    def create_card_grid(self, chances: Dict) -> Dict:
        """
        Place results on a 3×11 card grid respecting dice probabilities.

        Args:
            chances: Dictionary of outcome chances

        Returns:
            Grid dictionary with structure {column: {dice_sum: result}}
        """
        # Create allocation list weighted by dice probabilities
        allocations = []

        for dice_sum in range(2, 13):
            weight = config.DICE_WEIGHTS[dice_sum]
            allocations.extend([dice_sum] * weight)

        # We have 36 weighted slots per column, 3 columns = 108 total
        # Build a list of 108 results based on chances

        results_list = []
        for outcome, chance_count in chances.items():
            count = int(round(chance_count))
            results_list.extend([outcome] * count)

        # Pad or trim to exactly 108
        while len(results_list) < 108:
            results_list.append('OUT')
        results_list = results_list[:108]

        # Sort results by value (best results on rare rolls)
        result_value = {
            'HOMERUN': 7,
            'TRIPLE': 6,
            'DOUBLE': 5,
            'SINGLE': 4,
            'WALK': 3,
            'HBP': 2,
            'OUT': 1,
            'STRIKEOUT': 0
        }
        results_list.sort(key=lambda x: result_value.get(x, 0), reverse=True)

        # Create grid: 3 identical columns (Basic game)
        # Each column maps dice sum (2-12) to result
        grid = {1: {}, 2: {}, 3: {}}

        # Assign results to dice positions
        # Strategy: rare rolls (2, 12) get best results, common rolls (7) get worst
        dice_rarity_order = [2, 12, 3, 11, 4, 10, 5, 9, 6, 8, 7]

        result_idx = 0
        for col in [1, 2, 3]:
            for dice_sum in dice_rarity_order:
                weight = config.DICE_WEIGHTS[dice_sum]
                # Assign 'weight' results to this dice position
                if result_idx < len(results_list):
                    # For simplicity in basic version, just assign the first available result
                    # In reality, we'd assign multiple results per position based on weight
                    grid[col][dice_sum] = self._format_result(results_list[result_idx])
                    result_idx += weight
                else:
                    grid[col][dice_sum] = self._format_result('OUT')

        return grid

    def _format_result(self, outcome: str) -> str:
        """Format outcome for card display."""
        result_formats = {
            'HOMERUN': 'HOMERUN',
            'TRIPLE': 'TRIPLE',
            'DOUBLE': 'DOUBLE',
            'SINGLE': 'SINGLE',
            'WALK': 'WALK',
            'HBP': 'HBP',
            'STRIKEOUT': 'STRIKEOUT',
            'OUT': 'gb(A)'  # Default out type
        }
        return result_formats.get(outcome, 'OUT')

    def calculate_ratings(self, stats: Dict) -> Dict:
        """
        Calculate auxiliary ratings (stealing, power, etc.).

        Args:
            stats: Player statistics

        Returns:
            Dictionary of ratings
        """
        ratings = {}

        # STEALING RATING
        sb = stats.get('SB', 0)
        cs = stats.get('CS', 0)
        attempts = sb + cs

        if attempts == 0:
            ratings['steal'] = 'E'
        else:
            success_rate = sb / attempts
            if success_rate >= 0.85 and attempts >= 20:
                ratings['steal'] = 'AAA'
            elif success_rate >= 0.80 and attempts >= 15:
                ratings['steal'] = 'AA'
            elif success_rate >= 0.75 and attempts >= 10:
                ratings['steal'] = 'A'
            elif success_rate >= 0.70:
                ratings['steal'] = 'B'
            elif success_rate >= 0.60:
                ratings['steal'] = 'C'
            elif success_rate >= 0.50:
                ratings['steal'] = 'D'
            else:
                ratings['steal'] = 'E'

        # POWER RATING
        hr = stats.get('HR', 0)
        ratings['power'] = 'N' if hr >= config.POWER_THRESHOLD_HR else 'W'

        # SPEED RATING (based on triples and steals)
        triples = stats.get('3B', 0)
        speed_score = (sb * 2) + (triples * 3)
        if speed_score >= 30:
            ratings['speed'] = 'A'
        elif speed_score >= 20:
            ratings['speed'] = 'B'
        elif speed_score >= 10:
            ratings['speed'] = 'C'
        else:
            ratings['speed'] = 'D'

        # BUNTING (placeholder - would need more sophisticated analysis)
        ratings['bunt'] = 'B'  # Default

        # HIT AND RUN (placeholder)
        ratings['hit_and_run'] = 'B'  # Default

        return ratings

    def assess_confidence(self, stats: Dict, chances: Dict) -> Dict:
        """
        Assess confidence in the generated card.

        Args:
            stats: Player statistics
            chances: Calculated chances

        Returns:
            Confidence assessment dictionary
        """
        warnings = []
        clamped_values = []

        # Check for clamped values (negative chances set to 0)
        for outcome, chance in chances.items():
            if outcome != 'OUT' and chance == 0:
                # Could be legitimately 0 or could be clamped
                pass

        # Check sample size
        pa = stats.get('PA', 0)
        if pa < 100:
            warnings.append(f'Very small sample size ({pa} PA)')
        elif pa < 200:
            warnings.append(f'Limited sample size ({pa} PA)')

        # Check for missing data
        missing_data = []
        if stats.get('IBB') is None:
            missing_data.append('IBB')
        if stats.get('SF') is None:
            missing_data.append('SF')
        if stats.get('CS', 0) == 0:
            missing_data.append('CS')

        # Determine overall confidence
        if len(warnings) == 0 and len(missing_data) == 0 and pa >= 300:
            overall = 'HIGH'
        elif len(warnings) <= 1 and pa >= 150:
            overall = 'MEDIUM'
        else:
            overall = 'LOW'

        return {
            'overall': overall,
            'warnings': warnings,
            'clamped_values': clamped_values,
            'missing_data': missing_data
        }
