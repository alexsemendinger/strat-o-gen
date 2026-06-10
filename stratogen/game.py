"""Simplified Strat-O-Matic basic-game engine: full innings, real baserunners.

The per-PA statistical tester (simulate.py) validates outcome *frequencies*;
this module validates *game dynamics* — the things frequencies can't see:
how `*`/`**` advancement symbols, the no-asterisk running gamble, double
plays off groundball-A, sacrifice-fly tags, and X-chart errors interact to
score runs.

Rulebook-faithful pieces (1998-2020 basic rules):
- `**` = all runners automatically advance two bases; `*` = exactly one.
- No asterisk = one base (singles) / two bases (doubles), plus an optional
  gamble: d20 vs the lead runner's running rating (+2 with two outs); make
  it and every runner takes an extra base, miss it and the lead runner is
  out while the others still advance. The batter never takes the extra base.
- LINEOUT "into as many outs as possible" doubles off the lead runner.

Documented approximations (the physical Basic Strategy Chart isn't
reproduced here): groundball A = double play when forced; B = productive
out (runners move up); C = runners hold; flyball A = deep (runner tags from
second or third); B = runner tags from third; C = shallow, hold. X-chances
resolve with league-average defense: ~16% singles, ~5% one-base errors,
otherwise outs. Steals, bunts, and hit-and-run are managerial choices and
are not simulated.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from .model import (
    Card, DICE_WEIGHTS, HR, TRIPLE, DOUBLE, SINGLE, WALK, HBP, SO, OUT,
    XCHANCE, categorize,
)
from .simulate import X_SINGLE_RATE

X_ERROR_RATE = 0.05         # one-base error share of X-chart chances
GAMBLE_THRESHOLD = 14       # send the runner when effective rating >= this
DEFAULT_RUNNING = 13

_DICE_SUMS = [d1 + d2 for d1 in range(1, 7) for d2 in range(1, 7)]
_RUNNING_RE = re.compile(r"running 1-(\d+)")


def card_running_rating(card: Card) -> int:
    for line in card.header_lines:
        m = _RUNNING_RE.search(line)
        if m:
            return int(m.group(1))
    return DEFAULT_RUNNING


@dataclass
class HalfInning:
    # bases hold the occupying runner's running rating, or None
    bases: list = field(default_factory=lambda: [None, None, None])
    outs: int = 0
    runs: int = 0

    def _score_from(self, base: int):
        if self.bases[base] is not None:
            self.runs += 1
            self.bases[base] = None

    def advance_all(self, n: int):
        """Every runner moves exactly n bases."""
        for _ in range(n):
            self._score_from(2)
            self.bases[2] = self.bases[1]
            self.bases[1] = self.bases[0]
            self.bases[0] = None

    def lead_base(self) -> int | None:
        for base in (2, 1, 0):
            if self.bases[base] is not None:
                return base
        return None

    def force_advance(self):
        """Walk/HBP: only forced runners move."""
        if self.bases[0] is None:
            return
        if self.bases[1] is None:
            self.bases[1] = self.bases[0]
        elif self.bases[2] is None:
            self.bases[2] = self.bases[1]
            self.bases[1] = self.bases[0]
        else:
            self.runs += 1
            self.bases[2] = self.bases[1]
            self.bases[1] = self.bases[0]
        self.bases[0] = None


def _gb_letter(text: str) -> str:
    stripped = text.rstrip("+").rstrip()
    return stripped[-1] if stripped[-1] in "ABC" else "B"


def _maybe_gamble(state: HalfInning, rng: random.Random):
    """The no-asterisk extra-base attempt (rulebook 2.2)."""
    lead = state.lead_base()
    if lead is None:
        return
    rating = state.bases[lead] or DEFAULT_RUNNING
    effective = rating + (2 if state.outs == 2 else 0)
    if effective < GAMBLE_THRESHOLD:
        return
    if rng.randint(1, 20) <= effective:
        # every runner advances one extra base (batter stays put)
        state.advance_all(1)
    else:
        state.bases[lead] = None
        state.outs += 1
        if state.outs < 3:
            state.advance_all(1)


def apply_outcome(state: HalfInning, text: str, batter_running: int,
                  rng: random.Random) -> None:
    """Resolve one card reading against the base/out state."""
    category = categorize(text)
    stars = len(text) - len(text.rstrip("*"))

    if category == XCHANCE:
        roll = rng.random()
        if roll < X_SINGLE_RATE:
            category, stars = SINGLE, 0
        elif roll < X_SINGLE_RATE + X_ERROR_RATE:
            state.advance_all(1)
            state.bases[0] = batter_running
            return
        else:
            state.outs += 1
            return

    if category == HR:
        state.advance_all(3)
        state.runs += 1
        return
    if category == TRIPLE:
        state.advance_all(3)
        state.bases[2] = batter_running
        return
    if category == DOUBLE:
        state.advance_all(2)
        if stars >= 2:
            state.advance_all(1)
        state.bases[1] = batter_running
        if stars == 0:
            _maybe_gamble(state, rng)
        return
    if category == SINGLE:
        state.advance_all(1)
        if stars >= 2:
            state.advance_all(1)
        state.bases[0] = batter_running
        if stars == 0:
            _maybe_gamble(state, rng)
        return
    if category in (WALK, HBP):
        state.force_advance()
        state.bases[0] = batter_running
        return

    # outs ---------------------------------------------------------------
    lower = text.lower()
    if category == SO or lower.startswith(("popout", "foulout")):
        state.outs += 1
        return
    if lower.startswith("lineout"):
        state.outs += 1
        if "as many outs" in lower and state.outs < 3:
            lead = state.lead_base()
            if lead is not None:
                state.bases[lead] = None
                state.outs += 1
        return
    if lower.startswith("flyball"):
        letter = _gb_letter(text)
        state.outs += 1
        if state.outs < 3:
            if letter == "A":          # deep: tag from third and second
                state._score_from(2)
                if state.bases[1] is not None:
                    state.bases[2], state.bases[1] = state.bases[1], None
            elif letter == "B":        # medium: tag from third only
                state._score_from(2)
        return
    if lower.startswith("groundball"):
        letter = _gb_letter(text)
        if letter == "A" and state.bases[0] is not None and state.outs <= 1:
            state.outs += 2          # double play: batter + runner on first
            state.bases[0] = None
            if state.outs < 3:
                state.advance_all(1)
            return
        state.outs += 1
        if letter == "B" and state.outs < 3:
            state.advance_all(1)     # productive out
        return
    # anything unrecognized counts as a plain out
    state.outs += 1


def synthetic_average_stats(league: dict, pa: int = 600) -> dict:
    """A league-average player-season, scaled to one batter's workload —
    used to lay out average cards with realistic symbol profiles."""
    raw = league.get("raw") or {}
    pa_eff = league.get("PA_eff") or 1
    scale = pa / pa_eff

    def s(key):
        return round((raw.get(key, 0) or 0) * scale)

    return {"name": "LEAGUE AVERAGE", "year": league.get("year"),
            "AB": s("AB"), "H": s("H"), "2B": s("2B"), "3B": s("3B"),
            "HR": s("HR"), "BB": s("BB"), "SO": s("SO"), "SB": s("SB"),
            "CS": s("CS"), "HBP": s("HBP"), "SF": s("SF"), "IBB": s("IBB"),
            "GIDP": s("GIDP") if raw.get("GIDP") else 0}


def average_cards(league: dict) -> tuple[Card, Card]:
    """(average batter card, average pitcher card), fully laid out."""
    from .generate import (average_batter_chances, average_pitcher_chances,
                           hit_profile, layout_card, pitcher_hit_profile)
    stats = synthetic_average_stats(league)
    batter = layout_card(
        average_batter_chances(league), card_type="batter",
        name="LEAGUE AVERAGE", year=league.get("year"), team=None,
        stats={}, header_lines=["running 1-13"], profile=hit_profile(stats))
    pitcher = layout_card(
        average_pitcher_chances(league), card_type="pitcher",
        name="LEAGUE AVERAGE", year=league.get("year"), team=None,
        stats={}, header_lines=[],
        profile=pitcher_hit_profile({"TBF": 600}, league))
    return batter, pitcher


class GameSimulator:
    """Plays half-innings with a lineup of batter cards vs one pitcher card."""

    def __init__(self, lineup: list[Card], pitcher: Card, seed: int = 0):
        self.lineup = lineup
        self.pitcher = pitcher
        self.rng = random.Random(seed)
        self._next_batter = 0
        self._running = [card_running_rating(c) for c in lineup]

    def _read_card(self, batter: Card) -> str:
        white = self.rng.randint(1, 6)
        card = batter if white <= 3 else self.pitcher
        column = card.column_numbers[(white - 1) % 3]
        dice_sum = self.rng.choice(_DICE_SUMS)
        roll20 = self.rng.randint(1, 20)
        for split in card.columns[column][dice_sum]:
            if split.lo <= roll20 <= split.hi:
                return split.text
        raise AssertionError("d20 ranges must cover 1-20")

    def play_half_inning(self) -> int:
        state = HalfInning()
        while state.outs < 3:
            idx = self._next_batter % len(self.lineup)
            batter = self.lineup[idx]
            self._next_batter += 1
            text = self._read_card(batter)
            apply_outcome(state, text, self._running[idx], self.rng)
        return state.runs

    def runs_per_game(self, half_innings: int = 20000) -> float:
        total = sum(self.play_half_inning() for _ in range(half_innings))
        return total / half_innings * 9.0
