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
        # Check if it's already a specific fielding result (e.g., "groundball (2b)A")
        if '(' in self.outcome or self.outcome.startswith('groundball') or self.outcome.startswith('flyball') or \
           self.outcome.startswith('lineout') or self.outcome.startswith('popout'):
            return self.outcome

        # Standard outcomes - match real SOM card formatting
        names = {
            'single': 'SINGLE',
            'single*': 'SINGLE*',
            'single**': 'SINGLE**',
            'double': 'DOUBLE',
            'double*': 'DOUBLE*',
            'double**': 'DOUBLE**',
            'triple': 'TRIPLE',
            'homerun': 'HOMERUN',
            'walk': 'WALK',
            'strikeout': 'strikeout',
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
        lines = [f"Column {self.column_num}:"]
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
    card_type: str = 'batter'  # 'batter' or 'pitcher'
    player_stats: Dict = None  # Original stats for display

    def __str__(self):
        """Format card to look like a real Strat-O-Matic card."""
        lines = []
        col_width = 20  # Width for each column

        # === HEADER SECTION ===
        if self.card_type == 'pitcher':
            lines.extend(self._format_pitcher_header())
        else:
            lines.extend(self._format_batter_header())

        # === COLUMN HEADERS ===
        col_nums = [str(col.column_num) for col in self.columns]
        header_line = "".join(c.center(col_width) for c in col_nums)
        lines.append(header_line)
        lines.append("-" * (col_width * 3))

        # === DICE ROLL RESULTS (side by side) ===
        # For each dice value 2-12, show all three columns
        for dice_idx in range(11):  # 11 dice values (2-12)
            dice_val = dice_idx + 2

            # Get the formatted lines for each column's dice roll
            col_lines = []
            max_lines = 1

            for col in self.columns:
                roll = col.rolls[dice_idx]
                formatted = self._format_dice_roll(roll)
                col_lines.append(formatted)
                max_lines = max(max_lines, len(formatted))

            # Pad shorter columns to match the longest
            for i in range(len(col_lines)):
                while len(col_lines[i]) < max_lines:
                    col_lines[i].append("")

            # Print each line across all columns
            for line_idx in range(max_lines):
                row = ""
                for col_idx in range(3):
                    cell = col_lines[col_idx][line_idx]
                    row += cell.ljust(col_width)
                lines.append(row.rstrip())

        # === STATS SECTION ===
        lines.append("")
        lines.extend(self._format_stats_section())

        return '\n'.join(lines)

    def _format_pitcher_header(self) -> List[str]:
        """Format header for pitcher cards."""
        lines = []
        stats = self.player_stats or {}

        # Line 1: Name, position rating, type
        name = self.player_name.upper()
        pos_rating = f"pitcher-{stats.get('pitcher_rating', '?')}" if stats.get('pitcher_rating') else "pitcher"
        pitcher_type = "relief" if stats.get('GS', 0) < stats.get('G', 1) / 2 else "starter"

        lines.append(f"{name:<30} {pos_rating:<15} {pitcher_type}")
        lines.append("")

        # Line 2: PITCHING CARD with team
        team = stats.get('team', 'TEAM')
        league = stats.get('league', '')
        team_str = f"{team} ({league})" if league else team
        lines.append(f"PITCHING CARD{' ' * 20}{team_str}")
        lines.append("")

        return lines

    def _format_batter_header(self) -> List[str]:
        """Format header for batter cards."""
        lines = []
        stats = self.player_stats or {}

        # Line 1: Name with positions and ratings
        name = self.player_name.upper()
        lines.append(name)

        # Team line
        team = stats.get('team', 'TEAM')
        league = stats.get('league', '')
        team_str = f"{team} ({league})" if league else team
        lines.append(team_str)
        lines.append("")

        return lines

    def _format_dice_roll(self, roll: DiceRoll) -> List[str]:
        """Format a dice roll result for display, returns list of lines."""
        if not roll.results:
            return [f"{roll.dice}-[EMPTY]"]

        lines = []
        first = True

        for result in roll.results:
            outcome_name = result._outcome_name()

            if result.d20_range == (1, 20):
                # No split - single result for this dice
                if first:
                    lines.append(f"{roll.dice}-{outcome_name}")
                else:
                    lines.append(f"  {outcome_name}")
            else:
                # d20 split - show range
                start, end = result.d20_range
                if start == end:
                    range_str = str(start)
                else:
                    range_str = f"{start}-{end}"

                if first:
                    lines.append(f"{roll.dice}-{outcome_name}")
                    lines.append(f"  {range_str}")
                else:
                    lines.append(f"  {outcome_name}")
                    lines.append(f"  {range_str}")

            first = False

        return lines

    def _format_stats_section(self) -> List[str]:
        """Format the stats section at the bottom of the card."""
        lines = []
        stats = self.player_stats or {}

        if self.card_type == 'pitcher':
            lines.append(f"{self.year} PITCHING RECORD")
            lines.append("-" * 54)

            # Row 1: W, L, ERA, STARTS, SAVES
            w = stats.get('W', 0)
            l = stats.get('L', 0)
            era = stats.get('ERA', 0)
            gs = stats.get('GS', 0)
            sv = stats.get('SV', 0)

            lines.append(f"{'W':^9}{'L':^9}{'ERA':^9}{'STARTS':^9}{'SAVES':^9}")
            lines.append(f"{w:^9}{l:^9}{era:^9.2f}{gs:^9}{sv:^9}")
            lines.append("")

            # Row 2: IP, HITS ALLOWED, BB, SO, HOMERUNS ALLOWED
            ip = stats.get('IP', 0)
            h = stats.get('H', 0)
            bb = stats.get('BB', 0)
            so = stats.get('SO', 0)
            hr = stats.get('HR', 0)

            lines.append(f"{'IP':^9}{'HITS':^9}{'BB':^9}{'SO':^9}{'HR':^9}")
            lines.append(f"{ip:^9.0f}{h:^9}{bb:^9}{so:^9}{hr:^9}")

        else:  # batter
            lines.append(f"{self.year} BATTING RECORD")
            lines.append("-" * 54)

            # Row 1: AVG, AB, 2B, 3B, HR, RBI
            avg = stats.get('AVG', stats.get('BA', 0))
            ab = stats.get('AB', 0)
            doubles = stats.get('2B', 0)
            triples = stats.get('3B', 0)
            hr = stats.get('HR', 0)
            rbi = stats.get('RBI', 0)

            lines.append(f"{'AVG':^9}{'AB':^9}{'2B':^9}{'3B':^9}{'HR':^9}{'RBI':^9}")
            if isinstance(avg, float):
                lines.append(f"{avg:^9.3f}{ab:^9}{doubles:^9}{triples:^9}{hr:^9}{rbi:^9}")
            else:
                lines.append(f"{avg:^9}{ab:^9}{doubles:^9}{triples:^9}{hr:^9}{rbi:^9}")
            lines.append("")

            # Row 2: BB, SO, SB, CS, SLG%, ON BASE%
            bb = stats.get('BB', 0)
            so = stats.get('SO', 0)
            sb = stats.get('SB', 0)
            cs = stats.get('CS', 0)
            slg = stats.get('SLG', 0)
            obp = stats.get('OBP', 0)

            lines.append(f"{'BB':^9}{'SO':^9}{'SB':^9}{'CS':^9}{'SLG%':^9}{'OBP%':^9}")
            lines.append(f"{bb:^9}{so:^9}{sb:^9}{cs:^9}{slg:^9.3f}{obp:^9.3f}")

        return lines

    def get_outcome_totals(self) -> Dict[str, float]:
        """Calculate total chances for each outcome across all columns."""
        totals = {}
        for col in self.columns:
            for roll in col.rolls:
                for result in roll.results:
                    outcome = result.outcome
                    # Normalize fielding results to 'out' for counting
                    if outcome.startswith('groundball') or outcome.startswith('flyball') or \
                       outcome.startswith('lineout') or outcome.startswith('popout'):
                        outcome = 'out'
                    chances = result.get_chances(DICE_WEIGHTS[roll.dice])
                    totals[outcome] = totals.get(outcome, 0) + chances
        return totals

    def to_html(self) -> str:
        """Generate HTML formatted card that looks like a real Strat-O-Matic card."""
        stats = self.player_stats or {}

        # Build the HTML
        html = ['<div class="som-card">']

        # === HEADER SECTION ===
        html.append('<div class="som-header">')
        if self.card_type == 'pitcher':
            html.extend(self._html_pitcher_header())
        else:
            html.extend(self._html_batter_header())
        html.append('</div>')

        # === CARD LABEL ===
        card_label = "PITCHING CARD" if self.card_type == 'pitcher' else "BATTING CARD"
        team = stats.get('team', '')
        league = stats.get('league', '')
        team_str = f"{team} ({league})" if league else team

        html.append('<div class="som-card-label">')
        html.append(f'<span class="label-left">{card_label}</span>')
        html.append(f'<span class="label-right">{team_str}</span>')
        html.append('</div>')

        # === COLUMN HEADERS ===
        html.append('<div class="som-columns-header">')
        for col in self.columns:
            html.append(f'<div class="som-col-header">{col.column_num}</div>')
        html.append('</div>')

        # === DICE RESULTS TABLE ===
        html.append('<div class="som-columns">')

        # Create three column divs
        for col_idx, col in enumerate(self.columns):
            html.append('<div class="som-column">')
            for roll in col.rolls:
                html.append(self._html_dice_roll(roll))
            html.append('</div>')

        html.append('</div>')

        # === STATS SECTION ===
        html.append('<div class="som-stats">')
        html.extend(self._html_stats_section())
        html.append('</div>')

        html.append('</div>')

        return '\n'.join(html)

    def _html_pitcher_header(self) -> List[str]:
        """Generate HTML for pitcher card header."""
        stats = self.player_stats or {}
        html = []

        name = self.player_name.upper()
        pitcher_type = "relief" if stats.get('GS', 0) < stats.get('G', 1) / 2 else "starter"

        html.append('<div class="som-name-row">')
        html.append(f'<span class="som-player-name">{name}</span>')
        html.append(f'<span class="som-position">pitcher</span>')
        html.append(f'<span class="som-type">{pitcher_type}</span>')
        html.append('</div>')

        return html

    def _html_batter_header(self) -> List[str]:
        """Generate HTML for batter card header."""
        stats = self.player_stats or {}
        html = []

        name = self.player_name.upper()

        # Determine speed rating for display
        sb = stats.get('SB', 0)
        if sb >= 20:
            stealing = "stealing-A"
            running = f"running 1-{min(20, sb)}"
        elif sb >= 10:
            stealing = "stealing-B"
            running = f"running 1-{min(15, sb)}"
        elif sb >= 5:
            stealing = "stealing-C"
            running = ""
        else:
            stealing = ""
            running = ""

        html.append('<div class="som-name-row">')
        html.append(f'<span class="som-player-name">{name}</span>')
        if stealing:
            html.append(f'<span class="som-rating">{stealing}</span>')
        if running:
            html.append(f'<span class="som-rating">{running}</span>')
        html.append('</div>')

        return html

    def _html_dice_roll(self, roll: DiceRoll) -> str:
        """Generate HTML for a single dice roll result."""
        if not roll.results:
            return f'<div class="som-roll"><span class="dice">{roll.dice}</span>-[EMPTY]</div>'

        lines = []
        first = True

        for result in roll.results:
            outcome_name = result._outcome_name()

            # Determine if this is an "out" type result (lowercase) or hit (uppercase)
            is_positive = outcome_name.isupper() and outcome_name not in ['OUT']
            outcome_class = "positive" if is_positive else "negative"

            if result.d20_range == (1, 20):
                # No split
                if first:
                    lines.append(
                        f'<div class="som-roll">'
                        f'<span class="dice">{roll.dice}</span>-'
                        f'<span class="{outcome_class}">{outcome_name}</span>'
                        f'</div>'
                    )
                else:
                    lines.append(
                        f'<div class="som-roll-cont">'
                        f'<span class="{outcome_class}">{outcome_name}</span>'
                        f'</div>'
                    )
            else:
                # d20 split
                start, end = result.d20_range
                range_str = str(start) if start == end else f"{start}-{end}"

                if first:
                    lines.append(
                        f'<div class="som-roll">'
                        f'<span class="dice">{roll.dice}</span>-'
                        f'<span class="{outcome_class}">{outcome_name}</span>'
                        f'</div>'
                    )
                    lines.append(f'<div class="som-roll-split">{range_str}</div>')
                else:
                    lines.append(
                        f'<div class="som-roll-cont">'
                        f'<span class="{outcome_class}">{outcome_name}</span>'
                        f'</div>'
                    )
                    lines.append(f'<div class="som-roll-split">{range_str}</div>')

            first = False

        return '\n'.join(lines)

    def _html_stats_section(self) -> List[str]:
        """Generate HTML for stats section."""
        html = []
        stats = self.player_stats or {}

        if self.card_type == 'pitcher':
            html.append(f'<div class="som-stats-title">{self.year} PITCHING RECORD</div>')
            html.append('<table class="som-stats-table">')

            # Row 1 headers
            html.append('<tr class="stat-header">')
            for h in ['W', 'L', 'ERA', 'STARTS', 'SAVES']:
                html.append(f'<th>{h}</th>')
            html.append('</tr>')

            # Row 1 values
            w = stats.get('W', 0)
            l = stats.get('L', 0)
            era = stats.get('ERA', 0)
            gs = stats.get('GS', 0)
            sv = stats.get('SV', 0)

            html.append('<tr>')
            html.append(f'<td>{w}</td><td>{l}</td><td>{era:.2f}</td><td>{gs}</td><td>{sv}</td>')
            html.append('</tr>')

            # Row 2 headers
            html.append('<tr class="stat-header">')
            for h in ['IP', 'HITS', 'BB', 'SO', 'HR']:
                html.append(f'<th>{h}</th>')
            html.append('</tr>')

            # Row 2 values
            ip = stats.get('IP', 0)
            h_val = stats.get('H', 0)
            bb = stats.get('BB', 0)
            so = stats.get('SO', 0)
            hr = stats.get('HR', 0)

            html.append('<tr>')
            html.append(f'<td>{ip:.0f}</td><td>{h_val}</td><td>{bb}</td><td>{so}</td><td>{hr}</td>')
            html.append('</tr>')

            html.append('</table>')

        else:  # batter
            html.append(f'<div class="som-stats-title">{self.year} BATTING RECORD</div>')
            html.append('<table class="som-stats-table">')

            # Row 1 headers
            html.append('<tr class="stat-header">')
            for h in ['AVG', 'AB', '2B', '3B', 'HR', 'RBI']:
                html.append(f'<th>{h}</th>')
            html.append('</tr>')

            # Row 1 values
            avg = stats.get('AVG', stats.get('BA', 0))
            ab = stats.get('AB', 0)
            doubles = stats.get('2B', 0)
            triples = stats.get('3B', 0)
            hr = stats.get('HR', 0)
            rbi = stats.get('RBI', 0)

            avg_str = f"{avg:.3f}" if isinstance(avg, float) else str(avg)
            html.append('<tr>')
            html.append(f'<td>{avg_str}</td><td>{ab}</td><td>{doubles}</td><td>{triples}</td><td>{hr}</td><td>{rbi}</td>')
            html.append('</tr>')

            # Row 2 headers
            html.append('<tr class="stat-header">')
            for h in ['BB', 'SO', 'SB', 'CS', 'SLG%', 'OBP%']:
                html.append(f'<th>{h}</th>')
            html.append('</tr>')

            # Row 2 values
            bb = stats.get('BB', 0)
            so = stats.get('SO', 0)
            sb = stats.get('SB', 0)
            cs = stats.get('CS', 0)
            slg = stats.get('SLG', 0)
            obp = stats.get('OBP', 0)

            html.append('<tr>')
            html.append(f'<td>{bb}</td><td>{so}</td><td>{sb}</td><td>{cs}</td><td>{slg:.3f}</td><td>{obp:.3f}</td>')
            html.append('</tr>')

            html.append('</table>')

        return html


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

    @staticmethod
    def _determine_speed_rating(stats: Dict) -> str:
        """
        Determine player speed rating from stolen base stats.

        Returns:
            'fast' (SB >= 15), 'average' (SB 5-14), or 'slow' (SB < 5)
        """
        sb = stats.get('SB', 0)
        if sb >= 15:
            return 'fast'
        elif sb >= 5:
            return 'average'
        else:
            return 'slow'

    @classmethod
    def generate_layout(cls, chances: Dict[str, float], player_name: str, year: int,
                       player_stats: Dict = None, card_type: str = 'batter') -> CardLayout:
        """
        Generate a card layout from calculated outcome chances.

        Args:
            chances: Dictionary of outcome -> chances (out of 108)
            player_name: Player name for display
            year: Season year
            player_stats: Optional player stats for baserunning modifiers
            card_type: 'batter' (columns 1-2-3) or 'pitcher' (columns 4-5-6)

        Returns:
            CardLayout object with assigned dice rolls
        """
        # Initialize columns with empty dice rolls
        columns = cls._create_empty_columns(card_type)

        # Track how many chances we've assigned for each outcome
        remaining = chances.copy()

        # PHASE 1: Pre-process rare outcomes with strategic d20 splits
        # This ensures HR/3B don't disappear due to rounding
        cls._assign_rare_outcomes(columns, remaining, card_type)

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
        cls._fill_remaining_with_outs(columns, out_chances, card_type)

        # PHASE 4: Add baserunning modifiers based on speed (batters only)
        if player_stats and card_type == 'batter':
            cls._add_baserunning_modifiers(columns, player_stats)

        return CardLayout(
            player_name=player_name,
            year=year,
            columns=columns,
            card_type=card_type,
            player_stats=player_stats
        )

    @classmethod
    def _add_baserunning_modifiers(cls, columns: List[CardColumn], player_stats: Dict):
        """
        Add baserunning modifiers (* and **) to singles and doubles based on speed.

        Fast players (SB >= 15): 50% of singles get **, 50% of doubles get **
        Average players (SB 5-14): 30% of singles get *
        Slow players (SB < 5): No modifiers
        """
        import random

        speed = cls._determine_speed_rating(player_stats)

        if speed == 'slow':
            return  # No modifiers for slow players

        # Collect all single and double results
        single_results = []
        double_results = []

        for col in columns:
            for roll in col.rolls:
                for result in roll.results:
                    if result.outcome == 'single':
                        single_results.append(result)
                    elif result.outcome == 'double':
                        double_results.append(result)

        # Apply modifiers based on speed
        if speed == 'fast':
            # 50% of singles get **
            num_singles_to_modify = len(single_results) // 2
            for result in random.sample(single_results, min(num_singles_to_modify, len(single_results))):
                result.outcome = 'single**'

            # 50% of doubles get **
            num_doubles_to_modify = len(double_results) // 2
            for result in random.sample(double_results, min(num_doubles_to_modify, len(double_results))):
                result.outcome = 'double**'

        elif speed == 'average':
            # 30% of singles get *
            num_singles_to_modify = int(len(single_results) * 0.3)
            for result in random.sample(single_results, min(num_singles_to_modify, len(single_results))):
                result.outcome = 'single*'

    @staticmethod
    def _create_empty_columns(card_type: str = 'batter') -> List[CardColumn]:
        """Create 3 empty columns with unassigned dice rolls.

        Args:
            card_type: 'batter' for columns 1-2-3, 'pitcher' for columns 4-5-6
        """
        columns = []
        # Batter cards use columns 1-2-3, pitcher cards use 4-5-6
        start_col = 4 if card_type == 'pitcher' else 1
        for col_num in range(start_col, start_col + 3):
            rolls = []
            for dice in range(2, 13):
                rolls.append(DiceRoll(dice=dice, results=[]))
            columns.append(CardColumn(column_num=col_num, rolls=rolls))
        return columns

    @classmethod
    def _assign_rare_outcomes(cls, columns: List[CardColumn], remaining: Dict[str, float],
                              card_type: str = 'batter'):
        """
        Pre-assign rare outcomes using strategic d20 splits.

        Rare outcomes (HR < 3 chances, 3B < 3 chances) need special handling:
        - HOMERUN 1, flyball 2-20 (gives ~0.2 chances for HR)
        - TRIPLE 1, SINGLE 2-20 (gives ~0.2 chances for 3B)

        This prevents rare outcomes from disappearing due to rounding.
        Uses column 2/5 (middle, offensive column) dice 9 and 10.

        Args:
            columns: Card columns to assign to
            remaining: Dictionary of remaining chances (will be modified)
            card_type: 'batter' or 'pitcher' (affects out format)
        """
        assigner = FieldingLocationAssigner()
        is_pitcher = card_type == 'pitcher'
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
            flyball_result = assigner.generate_out_result(for_pitcher=is_pitcher)
            # Ensure it's a flyball (regenerate if not)
            flyball_prefix = 'FLYBALL' if is_pitcher else 'flyball'
            while not flyball_result.startswith(flyball_prefix):
                flyball_result = assigner.generate_out_result(for_pitcher=is_pitcher)

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

        Strategy:
        - Only assign a whole dice roll if remaining >= dice_weight
          (never overassign - this prevents the massive error we saw before)
        - If remaining < dice_weight for all remaining dice, stop
        - Leftover chances will be absorbed by outs or other rounding
        """
        remaining = target_chances

        # Order dice from largest to smallest weight for greedy assignment
        # This minimizes leftover remainder
        dice_order = [7, 6, 8, 5, 9, 4, 10, 3, 11, 2, 12]

        for dice in dice_order:
            if remaining < 1:  # Less than 1 chance left, stop
                break

            # Find the roll for this dice value
            roll = next(r for r in column.rolls if r.dice == dice)

            # Skip if this roll is already reserved
            if roll.results:
                continue

            dice_weight = DICE_WEIGHTS[dice]

            # Only assign if we have enough chances to fill this dice
            # (no overassignment allowed)
            if remaining >= dice_weight:
                roll.results.append(CardResult(outcome=outcome))
                remaining -= dice_weight

    @staticmethod
    def _fill_remaining_with_outs(columns: List[CardColumn], out_chances: float,
                                  card_type: str = 'batter'):
        """
        Fill ALL remaining empty dice slots with outs.

        A SOM card must have exactly 108 chances total. After assigning hits,
        walks, strikeouts etc., we fill every remaining empty slot with an out.
        The out_chances parameter is informational but we don't cap at it.

        Args:
            columns: Card columns to fill
            out_chances: Target out chances (informational, not a hard cap)
            card_type: 'batter' or 'pitcher' (affects out format)
        """
        assigner = FieldingLocationAssigner()
        is_pitcher = card_type == 'pitcher'

        # Fill ALL empty dice rolls with outs to complete the card
        for col in columns:
            for roll in col.rolls:
                if not roll.results:
                    # Empty slot - fill with a fielding out
                    fielding_result = assigner.generate_out_result(for_pitcher=is_pitcher)
                    roll.results.append(CardResult(outcome=fielding_result))


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
