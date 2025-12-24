"""
Card layout generator - converts outcome chances to dice roll assignments.

SOM cards have:
- 3 columns (for control die results 1-2, 3-4, 5-6)
- Each column has 11 dice results (2-12 from 2d6)
- 2d6 probability weights: 2=1, 3=2, 4=3, 5=4, 6=5, 7=6, 8=5, 9=4, 10=3, 11=2, 12=1
- Total: 36 chances per column × 3 columns = 108 total chances
- Can use d20 splits to subdivide a single result (e.g., "HR 1-12, 2B 13-20")
"""

from typing import Dict, List, Tuple
from dataclasses import dataclass
from fielding_locations import FieldingLocationAssigner


# 2d6 probability distribution - how many chances each dice sum has per column
DICE_WEIGHTS = {
    2: 1,
    3: 2,
    4: 3,
    5: 4,
    6: 5,
    7: 6,
    8: 5,
    9: 4,
    10: 3,
    11: 2,
    12: 1,
}


@dataclass
class CardResult:
    """A single result on the card (can include d20 splits)."""
    outcome: str  # 'single', 'double', 'triple', 'homerun', 'walk', 'strikeout', 'out', or specific fielding result
    d20_range: Tuple[int, int] = (1, 20)  # (start, end) inclusive, or None for no split

    def __str__(self):
        if self.d20_range == (1, 20):
            # Full result, no d20 split
            return self._outcome_name()
        else:
            # d20 split
            return f"{self._outcome_name()} {self.d20_range[0]}-{self.d20_range[1]}"

    def _outcome_name(self) -> str:
        """Format outcome name for display."""
        # Check if it's already a specific fielding result (e.g., "gb(2B)A")
        if '(' in self.outcome or self.outcome.startswith('gb') or self.outcome.startswith('fly') or \
           self.outcome.startswith('line') or self.outcome.startswith('popup'):
            return self.outcome

        # Standard outcomes
        names = {
            'single': '1B',
            'double': '2B',
            'triple': '3B',
            'homerun': 'HR',
            'walk': 'BB',
            'strikeout': 'SO',
            'out': 'OUT',
            'hbp': 'HBP',
        }
        return names.get(self.outcome, self.outcome.upper())

    def get_chances(self, dice_weight: int) -> float:
        """Calculate how many chances this result represents."""
        range_size = self.d20_range[1] - self.d20_range[0] + 1
        return dice_weight * (range_size / 20.0)


@dataclass
class DiceRoll:
    """A single dice roll (2-12) with potentially multiple results via d20 splits."""
    dice: int  # 2-12
    results: List[CardResult]

    def __str__(self):
        if not self.results:
            return f"{self.dice}: [EMPTY]"
        elif len(self.results) == 1 and self.results[0].d20_range == (1, 20):
            return f"{self.dice}: {self.results[0]}"
        else:
            # Multiple results or splits
            result_strs = [str(r) for r in self.results]
            return f"{self.dice}: {', '.join(result_strs)}"

    def get_total_chances(self) -> float:
        """Get total chances for this dice roll."""
        return sum(r.get_chances(DICE_WEIGHTS[self.dice]) for r in self.results)


@dataclass
class CardColumn:
    """One column of a SOM card (36 chances)."""
    column_num: int  # 1, 2, or 3
    rolls: List[DiceRoll]  # One for each dice value 2-12

    def __str__(self):
        lines = [f"Column {self.column_num} (Control Die {2*self.column_num-1}-{2*self.column_num}):"]
        for roll in self.rolls:
            lines.append(f"  {roll}")
        return '\n'.join(lines)

    def get_total_chances(self) -> float:
        """Get total chances across all rolls in this column."""
        return sum(roll.get_total_chances() for roll in self.rolls)


@dataclass
class CardLayout:
    """Complete SOM card layout with 3 columns."""
    player_name: str
    year: int
    columns: List[CardColumn]

    def __str__(self):
        lines = [
            "=" * 70,
            f"{self.player_name} - {self.year}",
            "=" * 70,
        ]
        for col in self.columns:
            lines.append("")
            lines.append(str(col))
        return '\n'.join(lines)

    def get_outcome_totals(self) -> Dict[str, float]:
        """Calculate total chances for each outcome across all columns."""
        totals = {}
        for col in self.columns:
            for roll in col.rolls:
                for result in roll.results:
                    outcome = result.outcome
                    # Normalize fielding results to 'out' for counting
                    if outcome.startswith('gb') or outcome.startswith('fly') or \
                       outcome.startswith('line') or outcome.startswith('popup'):
                        outcome = 'out'
                    chances = result.get_chances(DICE_WEIGHTS[roll.dice])
                    totals[outcome] = totals.get(outcome, 0) + chances
        return totals


class CardLayoutGenerator:
    """Generates card layouts from calculated chances."""

    # Priority order for assigning outcomes to dice rolls
    # Rarer/more valuable outcomes get priority on favorable dice rolls
    OUTCOME_PRIORITY = [
        'homerun',
        'triple',
        'double',
        'single',
        'walk',
        'hbp',
        'strikeout',
        'out',
    ]

    @classmethod
    def generate_layout(cls, chances: Dict[str, float], player_name: str, year: int) -> CardLayout:
        """
        Generate a card layout from calculated outcome chances.

        Args:
            chances: Dictionary of outcome -> chances (out of 108)
            player_name: Player name for display
            year: Season year

        Returns:
            CardLayout object with assigned dice rolls
        """
        # Initialize columns with empty dice rolls
        columns = cls._create_empty_columns()

        # Track how many chances we've assigned for each outcome
        remaining = chances.copy()

        # PHASE 1: Pre-process rare outcomes with strategic d20 splits
        # This ensures HR/3B don't disappear due to rounding
        cls._assign_rare_outcomes(columns, remaining)

        # Assign outcomes in priority order (except outs and already-handled rare outcomes)
        for outcome in cls.OUTCOME_PRIORITY:
            if outcome == 'out':
                continue  # Handle outs last
            if outcome not in remaining or remaining[outcome] <= 0.01:
                continue

            # Assign this outcome across the columns
            cls._assign_outcome(columns, outcome, remaining[outcome])
            remaining[outcome] = 0

        # Fill any remaining space with outs (up to the specified amount)
        out_chances = remaining.get('out', remaining.get('outs', 0))
        cls._fill_remaining_with_outs(columns, out_chances)

        return CardLayout(
            player_name=player_name,
            year=year,
            columns=columns
        )

    @staticmethod
    def _create_empty_columns() -> List[CardColumn]:
        """Create 3 empty columns with unassigned dice rolls."""
        columns = []
        for col_num in range(1, 4):
            rolls = []
            for dice in range(2, 13):
                rolls.append(DiceRoll(dice=dice, results=[]))
            columns.append(CardColumn(column_num=col_num, rolls=rolls))
        return columns

    @classmethod
    def _assign_rare_outcomes(cls, columns: List[CardColumn], remaining: Dict[str, float]):
        """
        Pre-assign rare outcomes using strategic d20 splits.

        Rare outcomes (HR < 3 chances, 3B < 3 chances) need special handling:
        - HOMERUN 1, flyball 2-20 (gives ~0.2 chances for HR)
        - TRIPLE 1, SINGLE 2-20 (gives ~0.2 chances for 3B)

        This prevents rare outcomes from disappearing due to rounding.
        Uses column 2 (middle, offensive column) dice 9 and 10.

        Args:
            columns: Card columns to assign to
            remaining: Dictionary of remaining chances (will be modified)
        """
        assigner = FieldingLocationAssigner()
        column_2 = columns[1]  # Middle column (index 1)

        hr_chances = remaining.get('homerun', 0)
        triple_chances = remaining.get('triple', 0)

        # Handle rare home runs (< 3 chances)
        if 0 < hr_chances < 3:
            # Use dice 9 in column 2 (weight = 4)
            # HOMERUN 1, flyball 2-20
            dice_9 = next(r for r in column_2.rolls if r.dice == 9)

            # Calculate d20 range for HR (round to nearest)
            hr_d20_size = max(1, round(hr_chances / 4 * 20))  # 4 is dice weight

            # Add HOMERUN result
            dice_9.results.append(CardResult(
                outcome='homerun',
                d20_range=(1, hr_d20_size)
            ))

            # Add flyball fallback for rest of d20
            flyball_result = assigner.generate_out_result()
            # Ensure it's a flyball (regenerate if not)
            while not flyball_result.startswith('fly'):
                flyball_result = assigner.generate_out_result()

            dice_9.results.append(CardResult(
                outcome=flyball_result,
                d20_range=(hr_d20_size + 1, 20)
            ))

            # Deduct from remaining
            actual_hr = (hr_d20_size / 20.0) * 4
            remaining['homerun'] = max(0, remaining.get('homerun', 0) - actual_hr)

        # Handle rare triples (< 3 chances)
        if 0 < triple_chances < 3:
            # Use dice 10 in column 2 (weight = 3)
            # TRIPLE 1, SINGLE 2-20
            dice_10 = next(r for r in column_2.rolls if r.dice == 10)

            # Calculate d20 range for 3B (round to nearest)
            triple_d20_size = max(1, round(triple_chances / 3 * 20))  # 3 is dice weight

            # Add TRIPLE result
            dice_10.results.append(CardResult(
                outcome='triple',
                d20_range=(1, triple_d20_size)
            ))

            # Add SINGLE fallback for rest of d20
            dice_10.results.append(CardResult(
                outcome='single',
                d20_range=(triple_d20_size + 1, 20)
            ))

            # Deduct from remaining
            actual_triple = (triple_d20_size / 20.0) * 3
            remaining['triple'] = max(0, remaining.get('triple', 0) - actual_triple)

            # Credit the single chances we added
            single_chances = ((20 - triple_d20_size) / 20.0) * 3
            remaining['single'] = remaining.get('single', 0) - single_chances

    @classmethod
    def _assign_outcome(cls, columns: List[CardColumn], outcome: str, total_chances: float):
        """
        Assign an outcome across the three columns.

        PHASE 2: Strategic column distribution to match real SOM cards.

        Column 1 (Defensive): 70-80% outs/strikeouts, 20-30% offensive
        Column 2 (Offensive): 60-70% walks/hits, 30-40% outs (already has rare HR/3B)
        Column 3 (Mixed): 50/50 balance
        """
        # Categorize outcomes
        offensive_outcomes = {'homerun', 'triple', 'double', 'single', 'walk', 'hbp'}
        defensive_outcomes = {'strikeout', 'out'}

        if outcome in offensive_outcomes:
            # Offensive outcomes: heavily favor Column 2
            # Column 1: 15%, Column 2: 60%, Column 3: 25%
            column_weights = [0.15, 0.60, 0.25]
        elif outcome in defensive_outcomes:
            # Defensive outcomes: heavily favor Column 1
            # Column 1: 60%, Column 2: 15%, Column 3: 25%
            column_weights = [0.60, 0.15, 0.25]
        else:
            # Unknown outcome type: distribute evenly
            column_weights = [0.33, 0.34, 0.33]

        for col, weight in zip(columns, column_weights):
            chances_for_col = total_chances * weight
            if chances_for_col > 0.01:
                cls._assign_to_column(col, outcome, chances_for_col)

    @staticmethod
    def _assign_to_column(column: CardColumn, outcome: str, target_chances: float):
        """
        Assign an outcome to dice rolls within a single column.

        PHASE 3: Prefer whole dice rolls, avoid d20 splits except strategically.

        Strategy:
        - If remaining >= 75% of dice weight: use whole dice roll (accept rounding)
        - If remaining < 0.5: skip (too small, let it round away)
        - Only use d20 splits when necessary to combine outcomes on same dice
        """
        remaining = target_chances

        # Prefer dice rolls near 7 (most common)
        dice_order = [7, 6, 8, 5, 9, 4, 10, 3, 11, 2, 12]

        for dice in dice_order:
            if remaining < 0.5:  # Too small, let it round away
                break

            # Find the roll for this dice value
            roll = next(r for r in column.rolls if r.dice == dice)

            # Skip if this roll is already reserved (from rare outcomes)
            if roll.results:
                continue

            # How many chances does this dice value have?
            dice_weight = DICE_WEIGHTS[dice]

            # Decision: use whole dice roll or skip?
            if remaining >= dice_weight * 0.75:
                # Use entire dice roll (accept rounding error)
                roll.results.append(CardResult(outcome=outcome))
                remaining -= dice_weight
            elif remaining >= dice_weight * 0.3:
                # Partial fill: use what we need, round to whole dice
                # This will leave remainder for next iteration
                # Only use d20 if we can get at least 30% of the dice
                roll.results.append(CardResult(outcome=outcome))
                remaining -= dice_weight
            # else: skip this dice, remaining carries forward

    @staticmethod
    def _fill_remaining_with_outs(columns: List[CardColumn], out_chances: float):
        """
        Fill remaining space with outs, but only up to the specified amount.
        Uses FieldingLocationAssigner to generate specific fielding locations.

        PHASE 3: Prefer whole dice rolls for outs too.

        Args:
            columns: Card columns to fill
            out_chances: How many out chances we should have total (out of 108)
        """
        assigner = FieldingLocationAssigner()

        # Calculate how many outs we already have from partial fills
        current_outs = 0
        for col in columns:
            for roll in col.rolls:
                for result in roll.results:
                    # Count any fielding result as an out
                    if result.outcome == 'out' or result.outcome.startswith('gb') or \
                       result.outcome.startswith('fly') or result.outcome.startswith('line') or \
                       result.outcome.startswith('popup'):
                        current_outs += result.get_chances(DICE_WEIGHTS[roll.dice])

        remaining_outs = out_chances - current_outs

        # Fill empty dice rolls with outs (prefer whole dice rolls)
        for col in columns:
            if remaining_outs < 0.5:  # Close enough
                break

            for roll in col.rolls:
                if remaining_outs < 0.5:
                    break

                if not roll.results:
                    # Entire dice roll is empty - assign a fielding location
                    dice_weight = DICE_WEIGHTS[roll.dice]

                    # Prefer using whole dice roll (accept rounding)
                    if remaining_outs >= dice_weight * 0.5:
                        # Use whole dice roll for outs
                        fielding_result = assigner.generate_out_result()
                        roll.results.append(CardResult(outcome=fielding_result))
                        remaining_outs -= dice_weight
                    # else: skip, too small


if __name__ == "__main__":
    # Test with simple example
    print("Testing card layout data structures")
    print("=" * 70)

    # Create a simple test column
    test_column = CardColumn(column_num=1, rolls=[])

    # Dice 7 has 6 chances - split between HR (3 chances) and OUT (3 chances)
    test_column.rolls.append(DiceRoll(
        dice=7,
        results=[
            CardResult(outcome='homerun', d20_range=(1, 10)),   # 10/20 * 6 = 3 chances
            CardResult(outcome='out', d20_range=(11, 20)),      # 10/20 * 6 = 3 chances
        ]
    ))

    # Dice 8 has 5 chances - all strikeouts
    test_column.rolls.append(DiceRoll(
        dice=8,
        results=[CardResult(outcome='strikeout')]
    ))

    print(test_column)
    print(f"\nTotal chances in column: {test_column.get_total_chances():.2f}")
