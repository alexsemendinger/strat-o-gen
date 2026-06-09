"""Card generation: season stats -> chance targets -> laid-out card.

The chance model (validated against the real-card fixtures, e.g. Bonds 2001
carries 22 HR / 41 BB chances and Ryan 1972 carries 47 K chances, all within
~1 chance of this formula):

    card_chances(outcome) = (2 * player_rate - league_rate) * 108

where rates are per effective PA (AB + BB - IBB + HBP + SF). The opposing
average card supplies `league_rate * 108`, so a full 216-chance cycle
reproduces the player's rate exactly. The same formula applies to batter
and pitcher cards; pitcher cards additionally carry exactly 30 X-chart
chances whose hit content depends on the defense.

When a player is *below* league average in a category the formula goes
negative and must be clamped at zero (a card can't carry negative chances).
The lost deficit is redistributed within hit categories to preserve the
total hit rate (and therefore BA); deficits in BB/SO can't be compensated
and are warned about — official SOM cards have the same limitation (a
never-strikes-out player still eats the pitcher card's strikeouts).
"""

from __future__ import annotations

import random

from .model import (
    Card, Split, DICE_WEIGHTS, CHANCES_PER_CARD,
    BATTER_COLUMNS, PITCHER_COLUMNS, X_CHANCES_PER_PITCHER_CARD,
    HR, TRIPLE, DOUBLE, SINGLE, WALK, SO, OUT, XCHANCE,
)
from .simulate import X_SINGLE_RATE, effective_pa, hits_from_stats
from . import ratings

# Smallest chance worth placing: a 1-in-20 split of a weight-1 row is 0.05.
_EPSILON = 0.026


def _deviation(player_rate: float, league_rate: float) -> tuple[float, float]:
    """(clamped chances, deficit). Deficit > 0 when the formula went negative."""
    raw = (2.0 * player_rate - league_rate) * 108.0
    return (raw, 0.0) if raw >= 0 else (0.0, -raw)


# --- chance targets ---------------------------------------------------------

def batter_chance_targets(stats: dict, league: dict) -> tuple[dict, list[str]]:
    warnings = []
    pa = effective_pa(stats)
    if pa <= 0:
        raise ValueError("player has no effective plate appearances")
    if pa < 100:
        warnings.append(f"small sample: only {pa:.0f} effective PA")

    h = hits_from_stats(stats)
    singles = h - stats.get("2B", 0) - stats.get("3B", 0) - stats.get("HR", 0)
    rate = {
        WALK: (stats.get("BB", 0) - stats.get("IBB", 0)) / pa,
        SO: stats.get("SO", 0) / pa,
        HR: stats.get("HR", 0) / pa,
        TRIPLE: stats.get("3B", 0) / pa,
        DOUBLE: stats.get("2B", 0) / pa,
        SINGLE: singles / pa,
    }
    league_rate = {
        WALK: league["BB_per_PA"], SO: league["K_per_PA"], HR: league["HR_per_PA"],
        TRIPLE: league["3B_per_PA"], DOUBLE: league["2B_per_PA"],
        SINGLE: league["1B_per_PA"],
    }
    targets, deficits = {}, {}
    for cat in (WALK, SO, HR, TRIPLE, DOUBLE, SINGLE):
        targets[cat], deficits[cat] = _deviation(rate[cat], league_rate[cat])

    # Redistribute clamped hit deficits to preserve the total hit rate:
    # an excess of league HR/3B/2B coming from the pitcher card is paid for
    # by removing singles from this card (and vice versa).
    xbh_deficit = deficits[HR] + deficits[TRIPLE] + deficits[DOUBLE]
    if xbh_deficit > 0:
        take = min(targets[SINGLE], xbh_deficit)
        targets[SINGLE] -= take
        if take < xbh_deficit - _EPSILON:
            warnings.append(
                "hit total runs high: below-average XBH deficit couldn't be fully "
                "absorbed by singles")
    if deficits[SINGLE] > 0:
        remaining = deficits[SINGLE]
        for cat in (DOUBLE, TRIPLE, HR):
            take = min(targets[cat], remaining)
            targets[cat] -= take
            remaining -= take
        if remaining > _EPSILON:
            warnings.append(
                "hit total runs high: player far below league average; "
                "the average pitcher card supplies more hits than the player earned")
    for cat, label in ((WALK, "walks"), (SO, "strikeouts")):
        if deficits[cat] > _EPSILON:
            warnings.append(
                f"{label} will run ~{deficits[cat] / 216:.1%} of PA high: player is "
                f"below league average and the card can't go negative")

    non_out = sum(targets.values())
    if non_out > CHANCES_PER_CARD:
        scale = CHANCES_PER_CARD / non_out
        targets = {cat: t * scale for cat, t in targets.items()}
        warnings.append("extreme stat line: chances scaled to fit the card")
        non_out = CHANCES_PER_CARD
    targets[OUT] = CHANCES_PER_CARD - non_out
    return targets, warnings


def pitcher_chance_targets(stats: dict, league: dict) -> tuple[dict, list[str]]:
    warnings = []
    tbf = stats.get("TBF", 0)
    if not tbf:
        tbf = stats.get("IP", 0) * 3 + stats.get("H", 0) + stats.get("BB", 0)
        warnings.append("batters faced estimated from IP/H/BB")
    tbf_eff = tbf - stats.get("IBB", 0)
    if tbf_eff <= 0:
        raise ValueError("pitcher has no batters faced")
    if tbf_eff < 100:
        warnings.append(f"small sample: only {tbf_eff:.0f} batters faced")

    rate_bb = (stats.get("BB", 0) - stats.get("IBB", 0)) / tbf_eff
    rate_k = stats.get("SO", 0) / tbf_eff
    rate_hr = stats.get("HR", 0) / tbf_eff
    rate_h = stats.get("H", 0) / tbf_eff

    targets = {}
    targets[WALK], d_bb = _deviation(rate_bb, league["BB_per_PA"])
    targets[SO], d_k = _deviation(rate_k, league["K_per_PA"])
    targets[HR], d_hr = _deviation(rate_hr, league["HR_per_PA"])
    for deficit, label in ((d_bb, "walks"), (d_k, "strikeouts")):
        if deficit > _EPSILON:
            warnings.append(
                f"{label} will run ~{deficit / 216:.1%} of PA high: pitcher is "
                f"better than league average and the card can't go negative")

    # Total hits the card must yield, X-chart singles included.
    total_hits, d_h = _deviation(rate_h, league["H_per_PA"])
    if d_h > _EPSILON:
        warnings.append(
            "hits allowed will run high: pitcher allows far fewer hits than "
            "league average and the card can't go negative")

    # The X block is normally 30 chances, but an extreme card (e.g. a modern
    # strikeout reliever) may not have room; shrink it before resorting to
    # scaling. Each X chance costs (1 - X_SINGLE_RATE) of capacity beyond the
    # hit total it absorbs.
    committed = targets[WALK] + targets[SO] + total_hits
    x_room = (CHANCES_PER_CARD - committed) / (1.0 - X_SINGLE_RATE)
    x_block = max(0, min(X_CHANCES_PER_PITCHER_CARD, int(x_room)))
    if x_block < X_CHANCES_PER_PITCHER_CARD:
        warnings.append(
            f"extreme stat line: X-chart block reduced to {x_block} chances "
            f"(normally {X_CHANCES_PER_PITCHER_CARD}) to fit the card")
    x_hits = x_block * X_SINGLE_RATE
    regular_hits = total_hits - x_hits
    if regular_hits < 0:
        warnings.append("dominant pitcher: X-chart hits alone exceed the hit "
                        "target; hits allowed will run slightly high")
        regular_hits = 0.0
    if targets[HR] > regular_hits:
        targets[HR] = regular_hits
        warnings.append("HR chances trimmed to fit hit total")
    # 2B/3B allowed aren't tracked historically; use the league's non-HR hit mix.
    non_hr = regular_hits - targets[HR]
    lg_non_hr = league["1B_per_PA"] + league["2B_per_PA"] + league["3B_per_PA"]
    targets[SINGLE] = non_hr * (league["1B_per_PA"] / lg_non_hr)
    targets[DOUBLE] = non_hr * (league["2B_per_PA"] / lg_non_hr)
    targets[TRIPLE] = non_hr * (league["3B_per_PA"] / lg_non_hr)

    targets[XCHANCE] = float(x_block)
    non_out = sum(targets.values())
    if non_out > CHANCES_PER_CARD:
        scale = (CHANCES_PER_CARD - targets[XCHANCE]) / (non_out - targets[XCHANCE])
        targets = {cat: (t * scale if cat != XCHANCE else t)
                   for cat, t in targets.items()}
        warnings.append("extreme stat line: chances scaled to fit the card")
        non_out = CHANCES_PER_CARD
    targets[OUT] = CHANCES_PER_CARD - non_out
    return targets, warnings


def average_batter_chances(league: dict) -> dict:
    """Chance content of a league-average batter card (no layout needed)."""
    targets = {
        WALK: league["BB_per_PA"] * 108,
        SO: league["K_per_PA"] * 108,
        HR: league["HR_per_PA"] * 108,
        TRIPLE: league["3B_per_PA"] * 108,
        DOUBLE: league["2B_per_PA"] * 108,
        SINGLE: league["1B_per_PA"] * 108,
    }
    targets[OUT] = CHANCES_PER_CARD - sum(targets.values())
    return targets


def average_pitcher_chances(league: dict) -> dict:
    """Chance content of a league-average pitcher card, X block included."""
    x_hits = X_CHANCES_PER_PITCHER_CARD * X_SINGLE_RATE
    targets = {
        WALK: league["BB_per_PA"] * 108,
        SO: league["K_per_PA"] * 108,
        HR: league["HR_per_PA"] * 108,
        TRIPLE: league["3B_per_PA"] * 108,
        DOUBLE: league["2B_per_PA"] * 108,
        SINGLE: max(0.0, league["1B_per_PA"] * 108 - x_hits),
        XCHANCE: float(X_CHANCES_PER_PITCHER_CARD),
    }
    targets[OUT] = CHANCES_PER_CARD - sum(targets.values())
    return targets


# --- layout -----------------------------------------------------------------

# Row orders: center-out (common rows first) and edge-in (rare rows first).
_CENTER_OUT = (7, 6, 8, 5, 9, 4, 10, 3, 11, 2, 12)
_EDGE_IN = tuple(reversed(_CENTER_OUT))

# X-chart cells for pitcher cards: full cells summing to exactly 30 chances,
# spread over all three columns like real cards.
_X_CELLS = [(4, 7), (4, 9), (5, 6), (5, 10), (5, 12), (6, 8), (6, 5), (6, 3)]
assert sum(DICE_WEIGHTS[d] for _, d in _X_CELLS) == X_CHANCES_PER_PITCHER_CARD


def _preferred_cells(columns: tuple[int, ...]) -> dict[str, list[tuple[int, int]]]:
    """Cell preference order per category (column, dice_sum)."""
    a, b, c = columns
    hits = ([(b, d) for d in _CENTER_OUT] + [(c, d) for d in _CENTER_OUT]
            + [(a, d) for d in _CENTER_OUT])
    walks = ([(c, d) for d in _CENTER_OUT] + [(a, d) for d in _CENTER_OUT]
             + [(b, d) for d in _CENTER_OUT])
    strikeouts = ([(a, d) for d in _CENTER_OUT] + [(c, d) for d in _CENTER_OUT]
                  + [(b, d) for d in _CENTER_OUT])
    return {HR: hits, TRIPLE: hits, DOUBLE: hits, SINGLE: hits,
            WALK: walks, SO: strikeouts}


class _OutFlavors:
    """Deterministic out-text generator in the style of real cards."""

    _GB_POS = ["ss", "3b", "2b", "1b", "p"]
    _FB_POS = ["lf", "cf", "rf"]

    def __init__(self, rng: random.Random, card_type: str):
        self.rng = rng
        self.card_type = card_type

    def next(self) -> str:
        roll = self.rng.random()
        if roll < 0.45:
            pos = self.rng.choice(self._GB_POS)
            rating = self.rng.choices(["A", "A++", "B", "C"],
                                      weights=[40, 12, 38, 10])[0]
            return f"groundball ({pos}){rating}"
        if roll < 0.75:
            pos = self.rng.choice(self._FB_POS)
            rating = self.rng.choices(["A", "B", "C"], weights=[15, 65, 20])[0]
            return f"flyball ({pos}){rating}"
        if roll < 0.85:
            return f"lineout ({self.rng.choice(self._GB_POS[:4])})"
        if roll < 0.95:
            return f"popout ({self.rng.choice(['ss', '2b', '3b', '1b'])})"
        return "foulout (c)"

    def x_chance(self) -> str:
        if self.rng.random() < 0.6:
            return f"GROUNDBALL ({self.rng.choice(self._GB_POS)}) X"
        return f"FLYBALL ({self.rng.choice(self._FB_POS)}) X"


class _HitVariants:
    """Cycle hit texts through */** variants like real cards."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self._singles = ["SINGLE", "SINGLE*", "SINGLE**"]
        self._doubles = ["DOUBLE", "DOUBLE**", "DOUBLE"]
        self._i1 = self._i2 = 0

    def text(self, cat: str) -> str:
        if cat == SINGLE:
            self._i1 += 1
            return self._singles[(self._i1 - 1) % 3]
        if cat == DOUBLE:
            self._i2 += 1
            return self._doubles[(self._i2 - 1) % 3]
        return {HR: "HOMERUN", TRIPLE: "TRIPLE", WALK: "WALK", SO: "strikeout"}[cat]


def layout_card(targets: dict[str, float], *, card_type: str, name: str,
                year: int | None, team: str | None, stats: dict,
                header_lines: list[str], seed_extra: str = "") -> Card:
    """Place chance targets on a 3x11 grid deterministically.

    The same player/year always produces the same card (the RNG that picks
    cosmetic out locations is seeded from name+year).
    """
    rng = random.Random(f"{name}|{year}|{card_type}|{seed_extra}")
    flavors = _OutFlavors(rng, card_type)
    variants = _HitVariants(rng)
    columns = PITCHER_COLUMNS if card_type == "pitcher" else BATTER_COLUMNS
    prefs = _preferred_cells(columns)

    free: dict[tuple[int, int], None] = {
        (col, d): None for col in columns for d in DICE_WEIGHTS}
    # cell -> list of (text, lo, hi) segments; partially used cells keep
    # their unused d20 tail open until the final out-filling pass.
    placed: dict[tuple[int, int], list[tuple[str, int, int]]] = {}

    def assign_full(cell, text):
        placed[cell] = [(text, 1, 20)]
        free.pop(cell)

    def assign_split(cell, text, upto):
        placed[cell] = [(text, 1, upto)]  # tail filled later
        free.pop(cell)

    def open_tail(cell) -> int:
        """First unused d20 slot of a partially used cell (21 = none)."""
        return placed[cell][-1][2] + 1

    # X block first (pitcher only): full cells summing exactly to the target.
    if card_type == "pitcher":
        x_target = int(round(targets.get(XCHANCE, 0)))
        if x_target == X_CHANCES_PER_PITCHER_CARD:
            x_cells = list(_X_CELLS)
        else:  # extreme card with a reduced block: greedy exact-sum pick
            x_cells = []
            remaining = x_target
            pool = sorted(free, key=lambda cd: -DICE_WEIGHTS[cd[1]])
            for cell in pool:
                w = DICE_WEIGHTS[cell[1]]
                if w <= remaining:
                    x_cells.append(cell)
                    remaining -= w
                if remaining == 0:
                    break
        if x_cells:
            catcher_cell = rng.choice(x_cells)
            for cell in x_cells:
                text = ("CATCHER'S CARD X" if cell == catcher_cell
                        else flavors.x_chance())
                assign_full(cell, text)

    order = [HR, TRIPLE, DOUBLE, SINGLE, WALK, SO]
    for cat in order:
        t = targets.get(cat, 0.0)
        # Full cells, largest usable weight first, following preference order.
        while t > _EPSILON:
            cell = None
            best_w = 0
            for cand in prefs[cat]:
                if cand in free:
                    w = DICE_WEIGHTS[cand[1]]
                    if w <= t + _EPSILON and w > best_w:
                        cell = cand
                        best_w = w
            if cell is None:
                break
            assign_full(cell, variants.text(cat))
            t -= best_w
        if t > _EPSILON:
            # One d20 split; among cells that approximate the remainder
            # equally well, prefer the lightest so the unused tail wastes
            # as little capacity as possible.
            best = None
            for cand in prefs[cat]:
                if cand not in free:
                    continue
                w = DICE_WEIGHTS[cand[1]]
                r = max(1, min(20, round(20.0 * t / w)))
                err = abs(w * r / 20.0 - t)
                key = (round(err * 20), w, err)
                if best is None or key < best[0]:
                    best = (key, cand, r)
            if best is not None:
                _key, cell, r = best
                if r >= 20:
                    assign_full(cell, variants.text(cat))
                else:
                    assign_split(cell, variants.text(cat), r)
                t -= DICE_WEIGHTS[cell[1]] * min(r, 20) / 20.0
        if t > _EPSILON:
            # Safety net for very crowded cards: continue this category in
            # the unused d20 tails of earlier splits.
            tails = sorted((c for c in placed if open_tail(c) <= 20),
                           key=lambda c: DICE_WEIGHTS[c[1]])
            for cell in tails:
                if t <= _EPSILON:
                    break
                w = DICE_WEIGHTS[cell[1]]
                start = open_tail(cell)
                avail_slots = 21 - start
                want_slots = min(avail_slots, max(1, round(20.0 * t / w)))
                placed[cell].append(
                    (variants.text(cat), start, start + want_slots - 1))
                t -= w * want_slots / 20.0

    # Outs fill every remaining cell and every open tail.
    for cell in list(free):
        assign_full(cell, flavors.next())
    for cell, entries in placed.items():
        text, lo, hi = entries[-1]
        if hi < 20:
            entries.append((flavors.next(), hi + 1, 20))

    # Build columns dict
    card_columns: dict[int, dict[int, list[Split]]] = {c: {} for c in columns}
    for (col, dice), entries in placed.items():
        card_columns[col][dice] = [
            Split(lo=lo, hi=hi, text=text) for text, lo, hi in entries]

    card = Card(name=name, card_type=card_type, team=team, year=year,
                header_lines=header_lines, stats=stats, columns=card_columns)
    _decorate(card, rng)
    return card


def _decorate(card: Card, rng: random.Random) -> None:
    """Batter-card flourishes seen on every real card: exactly one
    'plus injury' result and one max-effort lineout."""
    if card.card_type != "batter":
        return
    out_cells = [(col, d) for col, d, s in card.iter_splits()
                 if s.category == OUT and s.lo == 1 and s.hi == 20]
    if out_cells:
        rare = min(out_cells, key=lambda cd: (DICE_WEIGHTS[cd[1]], cd[0]))
        for split in card.columns[rare[0]][rare[1]]:
            split.injury = True
        remaining = [c for c in out_cells if c != rare]
        if remaining:
            col, d = rng.choice(remaining)
            pos = rng.choice(["2b", "3b", "ss", "1b"])
            card.columns[col][d] = [
                Split(lo=1, hi=20,
                      text=f"lineout ({pos}) into as many outs as possible")]


# --- top-level API -----------------------------------------------------------

def _batting_display_stats(stats: dict) -> dict:
    h = hits_from_stats(stats)
    ab = stats.get("AB", 0)
    out = {"BA": round(h / ab, 3) if ab else 0.0, "AB": ab}
    for key in ("2B", "3B", "HR", "RBI", "BB", "SO", "SB", "CS"):
        out[key] = stats.get(key, 0)
    tb = (h - stats.get("2B", 0) - stats.get("3B", 0) - stats.get("HR", 0)
          + 2 * stats.get("2B", 0) + 3 * stats.get("3B", 0) + 4 * stats.get("HR", 0))
    obp_den = ab + stats.get("BB", 0) + stats.get("HBP", 0) + stats.get("SF", 0)
    out["SLG"] = round(tb / ab, 3) if ab else 0.0
    out["OBP"] = round((h + stats.get("BB", 0) + stats.get("HBP", 0)) / obp_den, 3) \
        if obp_den else 0.0
    return out


def _pitching_display_stats(stats: dict) -> dict:
    out = {}
    for key in ("W", "L", "ERA", "GS", "SV", "IP", "H", "BB", "SO", "HR"):
        if key in stats:
            out[key] = stats[key]
    return out


def _missing_data_warnings(stats: dict) -> list[str]:
    notable = {"IBB", "SF", "HBP", "CS", "SO", "TBF", "IP"}
    return [f"{f} not tracked for this season (treated as 0)"
            for f in stats.get("missing", []) if f in notable]


def generate_batter_card(stats: dict, league: dict,
                         positions: list[tuple[str, int]] | None = None,
                         ) -> tuple[Card, list[str]]:
    """Generate a batter card. Returns (card, warnings)."""
    targets, warnings = batter_chance_targets(stats, league)
    warnings = (list(league.get("warnings", []))
                + _missing_data_warnings(stats) + warnings)
    card = layout_card(
        targets, card_type="batter",
        name=stats.get("name", "UNKNOWN").upper(),
        year=stats.get("year"), team=stats.get("team"),
        stats=_batting_display_stats(stats),
        header_lines=ratings.batter_header_lines(stats, positions or []),
    )
    return card, warnings


def generate_pitcher_card(stats: dict, league: dict) -> tuple[Card, list[str]]:
    targets, warnings = pitcher_chance_targets(stats, league)
    warnings = (list(league.get("warnings", []))
                + _missing_data_warnings(stats) + warnings)
    card = layout_card(
        targets, card_type="pitcher",
        name=stats.get("name", "UNKNOWN").upper(),
        year=stats.get("year"), team=stats.get("team"),
        stats=_pitching_display_stats(stats),
        header_lines=ratings.pitcher_header_lines(stats),
    )
    return card, warnings
