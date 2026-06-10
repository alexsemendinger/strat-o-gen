"""Card data model and chance accounting.

A Strat-O-Matic card has three columns (1-3 for batters, 4-6 for pitchers).
Each column has eleven rows for the 2d6 sums 2-12. A row holds one or more
d20 splits: e.g. "HOMERUN 1-12 / DOUBLE 13-20" means roll a d20 when this
row comes up; 1-12 is a homerun, 13-20 a double.

"Chances" are probability units out of 36 per column (108 per card): a row
for dice sum 7 is worth 6 chances, dice sum 2 is worth 1 chance, per the 2d6
distribution. A split occupying d20 range 1-12 of a 6-chance row is worth
6 * 12/20 = 3.6 chances.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

DICE_WEIGHTS = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 8: 5, 9: 4, 10: 3, 11: 2, 12: 1}
CHANCES_PER_COLUMN = 36
CHANCES_PER_CARD = 108
CHANCES_PER_CYCLE = 216  # batter card + pitcher card
BATTER_COLUMNS = (1, 2, 3)
PITCHER_COLUMNS = (4, 5, 6)
X_CHANCES_PER_PITCHER_CARD = 30

# Outcome categories
HR, TRIPLE, DOUBLE, SINGLE, WALK, HBP, SO, OUT, XCHANCE = (
    "HR", "3B", "2B", "1B", "BB", "HBP", "SO", "OUT", "X")
CATEGORIES = (HR, TRIPLE, DOUBLE, SINGLE, WALK, HBP, SO, OUT, XCHANCE)
HIT_CATEGORIES = (HR, TRIPLE, DOUBLE, SINGLE)


def categorize(text: str) -> str:
    """Map an outcome's display text to its statistical category.

    X-chance readings (pitcher cards only) are kept separate because their
    resolution depends on the defense, not the card alone.
    """
    t = text.strip()
    upper = t.upper()
    if upper.endswith(" X") or upper.endswith(")X") or "CATCHER'S CARD" in upper:
        return XCHANCE
    if upper.startswith("SINGLE"):
        return SINGLE
    if upper.startswith("DOUBLE"):
        return DOUBLE
    if upper.startswith("TRIPLE"):
        return TRIPLE
    if upper.startswith("HOMERUN") or upper.startswith("HOME RUN"):
        return HR
    if upper.startswith("WALK"):
        return WALK
    if upper.startswith("HIT BY PITCH") or upper == "HBP":
        return HBP
    if upper.startswith("STRIKEOUT"):
        return SO
    if upper.startswith(("GROUNDBALL", "FLYBALL", "LINEOUT", "POPOUT", "FOULOUT")):
        return OUT
    raise ValueError(f"Unrecognized card outcome: {text!r}")


@dataclass
class Split:
    """One d20 segment of a row. lo == 1 and hi == 20 means the whole row."""
    lo: int
    hi: int
    text: str
    injury: bool = False

    @property
    def fraction(self) -> float:
        return (self.hi - self.lo + 1) / 20.0

    @property
    def category(self) -> str:
        return categorize(self.text)


@dataclass
class Card:
    name: str
    card_type: str  # 'batter' or 'pitcher'
    team: str | None = None
    year: int | None = None
    header_lines: list[str] = field(default_factory=list)  # ratings as printed
    stats: dict = field(default_factory=dict)  # printed season stat line
    # columns[col][dice_sum] -> list of Splits covering 1-20
    columns: dict[int, dict[int, list[Split]]] = field(default_factory=dict)

    @property
    def column_numbers(self) -> tuple[int, ...]:
        return PITCHER_COLUMNS if self.card_type == "pitcher" else BATTER_COLUMNS

    def iter_splits(self) -> Iterator[tuple[int, int, Split]]:
        """Yield (column, dice_sum, split) for every split on the card."""
        for col in sorted(self.columns):
            for dice_sum in sorted(self.columns[col]):
                for split in self.columns[col][dice_sum]:
                    yield col, dice_sum, split

    def chances(self) -> dict[str, float]:
        """Total chances (out of 108) per outcome category."""
        totals = {cat: 0.0 for cat in CATEGORIES}
        for _col, dice_sum, split in self.iter_splits():
            totals[split.category] += DICE_WEIGHTS[dice_sum] * split.fraction
        return totals

    def validate(self) -> list[str]:
        """Return a list of structural problems (empty list = valid)."""
        problems = []
        expected_cols = set(self.column_numbers)
        actual_cols = set(self.columns)
        if actual_cols != expected_cols:
            problems.append(
                f"expected columns {sorted(expected_cols)}, got {sorted(actual_cols)}")
        for col, rows in self.columns.items():
            missing = set(DICE_WEIGHTS) - set(rows)
            if missing:
                problems.append(f"column {col} missing dice rows {sorted(missing)}")
            for dice_sum, splits in rows.items():
                covered = []
                for s in splits:
                    if not (1 <= s.lo <= s.hi <= 20):
                        problems.append(
                            f"column {col} row {dice_sum}: bad range {s.lo}-{s.hi}")
                    covered.extend(range(s.lo, s.hi + 1))
                if sorted(covered) != list(range(1, 21)):
                    problems.append(
                        f"column {col} row {dice_sum}: d20 ranges don't cover 1-20 "
                        f"exactly (got {sorted(set(covered))})")
                for s in splits:
                    try:
                        categorize(s.text)
                    except ValueError as e:
                        problems.append(f"column {col} row {dice_sum}: {e}")
        return problems
