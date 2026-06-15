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


def _spread_cells(columns: tuple[int, ...], phase: int) -> list[tuple[int, int]]:
    """Round-robin cells across columns with staggered row order.

    The placement loop breaks weight ties by list order, so an order that
    rotates columns spreads a category over the whole card instead of
    stacking it in one column (real cards mix strikeouts/walks/outs across
    all three columns).
    """
    rotated = []
    for i, col in enumerate(columns):
        offset = (phase + i * 4) % len(_CENTER_OUT)
        seq = _CENTER_OUT[offset:] + _CENTER_OUT[:offset]
        rotated.append([(col, d) for d in seq])
    return [cell for trio in zip(*rotated) for cell in trio]


def _preferred_cells(columns: tuple[int, ...]) -> dict[str, list[tuple[int, int]]]:
    """Cell preference order per category (column, dice_sum).

    Hits stay clustered in one column (real cards do this — Mays's HRs all
    sit in column 3); strikeouts and walks spread across columns.
    """
    a, b, c = columns
    hits = ([(b, d) for d in _CENTER_OUT] + [(c, d) for d in _CENTER_OUT]
            + [(a, d) for d in _CENTER_OUT])
    return {HR: hits, TRIPLE: hits, DOUBLE: hits, SINGLE: hits,
            WALK: _spread_cells((c, a, b), 2),
            SO: _spread_cells((a, c, b), 0)}


# League-typical fallback when no player profile is available
_DEFAULT_PROFILE = {"single_2star": 0.30, "single_star": 0.17,
                    "double_2star": 0.32, "gb_a": 0.45, "plus_plus": 1}


def hit_profile(stats: dict, pa: float | None = None) -> dict:
    """How this player's hits and outs should read, beyond raw frequencies.

    In play, ** means runners automatically advance two bases, * pins them
    to one, and no asterisk allows a running gamble — so the mix matters.
    Hard contact (isolated power) drives the ** share; soft contact drives
    the * share; GIDP tendency drives the groundball-A (double play) share;
    speed drives the count of ++ groundouts (which favor the offense when
    the infield is in or a runner is held).
    """
    ab = stats.get("AB", 0) or 1
    iso = (stats.get("2B", 0) + 2 * stats.get("3B", 0)
           + 3 * stats.get("HR", 0)) / ab
    pa = pa or effective_pa(stats) or 1

    def clamp(v, lo, hi):
        return max(lo, min(hi, v))

    gidp = stats.get("GIDP", 0) or 0
    gidp_missing = "GIDP" in (stats.get("missing") or []) or (
        gidp == 0 and "GIDP" not in stats)
    speed = ratings.running_rating(stats)  # 8 (slow) .. 17 (fast)
    return {
        "single_2star": clamp(0.10 + 1.6 * iso, 0.10, 0.55),
        "single_star": clamp(0.32 - 1.1 * iso, 0.05, 0.32),
        "double_2star": clamp(0.15 + 1.2 * iso, 0.15, 0.55),
        "gb_a": _DEFAULT_PROFILE["gb_a"] if gidp_missing
                else clamp(0.20 + 16.0 * gidp / pa, 0.18, 0.75),
        "plus_plus": 3 if speed >= 15 else (2 if speed >= 13 else 1),
    }


def pitcher_hit_profile(stats: dict, league: dict) -> dict:
    """Hits allowed read like league-average contact; ++ never appears on
    pitcher cards (rulebook 6.1: batters' cards only)."""
    raw = league.get("raw") or {}
    ab = raw.get("AB", 0) or 1
    iso = (raw.get("2B", 0) + 2 * raw.get("3B", 0) + 3 * raw.get("HR", 0)) / ab
    tbf = stats.get("TBF", 0) or 1
    gidp = stats.get("GIDP", 0) or 0
    profile = dict(_DEFAULT_PROFILE)
    profile["single_2star"] = max(0.10, min(0.55, 0.10 + 1.6 * iso))
    profile["single_star"] = max(0.05, min(0.32, 0.32 - 1.1 * iso))
    profile["double_2star"] = max(0.15, min(0.55, 0.15 + 1.2 * iso))
    if gidp:
        profile["gb_a"] = max(0.18, min(0.75, 0.20 + 16.0 * gidp / tbf))
    profile["plus_plus"] = 0
    return profile


class _OutFlavors:
    """Deterministic out-text generator in the style of real cards."""

    _GB_POS = ["ss", "3b", "2b", "1b", "p"]
    _FB_POS = ["lf", "cf", "rf"]

    def __init__(self, rng: random.Random, card_type: str, profile: dict):
        self.rng = rng
        self.card_type = card_type
        self.profile = profile

    def next(self) -> str:
        roll = self.rng.random()
        if roll < 0.45:
            pos = self.rng.choice(self._GB_POS)
            gb_a = self.profile["gb_a"]
            rating = self.rng.choices(
                ["A", "B", "C"],
                weights=[gb_a, 0.78 * (1 - gb_a), 0.22 * (1 - gb_a)])[0]
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
    """Player-aware */** mix on hit texts (see hit_profile).

    Variants are allocated by largest-deficit quota over the chances
    actually placed, so the card's realized mix matches the profile even
    when a player has only a couple of single chances to spread around.
    """

    def __init__(self, rng: random.Random, profile: dict):
        p = profile
        self._shares = {
            SINGLE: {"SINGLE**": p["single_2star"], "SINGLE*": p["single_star"],
                     "SINGLE": 1.0 - p["single_2star"] - p["single_star"]},
            DOUBLE: {"DOUBLE**": p["double_2star"],
                     "DOUBLE": 1.0 - p["double_2star"]},
        }
        self._placed = {SINGLE: {t: 0.0 for t in self._shares[SINGLE]},
                        DOUBLE: {t: 0.0 for t in self._shares[DOUBLE]}}

    def text(self, cat: str, amount: float = 1.0) -> str:
        if cat in self._shares:
            placed = self._placed[cat]
            total = sum(placed.values()) + amount
            deficit = {t: self._shares[cat][t] * total - placed[t]
                       for t in placed}
            choice = max(deficit, key=deficit.get)
            placed[choice] += amount
            return choice
        return {HR: "HOMERUN", TRIPLE: "TRIPLE", WALK: "WALK", SO: "strikeout"}[cat]


def layout_card(targets: dict[str, float], *, card_type: str, name: str,
                year: int | None, team: str | None, stats: dict,
                header_lines: list[str], profile: dict | None = None,
                seed_extra: str = "") -> Card:
    """Place chance targets on a 3x11 grid deterministically.

    The same player/year always produces the same card (the RNG that picks
    cosmetic out locations is seeded from name+year). `profile` (see
    hit_profile) controls the */**/++/DP-letter mix.
    """
    profile = profile or dict(_DEFAULT_PROFILE)
    rng = random.Random(f"{name}|{year}|{card_type}|{seed_extra}")
    flavors = _OutFlavors(rng, card_type, profile)
    variants = _HitVariants(rng, profile)
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
            assign_full(cell, variants.text(cat, best_w))
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
                amount = DICE_WEIGHTS[cell[1]] * min(r, 20) / 20.0
                if r >= 20:
                    assign_full(cell, variants.text(cat, amount))
                else:
                    assign_split(cell, variants.text(cat, amount), r)
                t -= amount
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
                amount = w * want_slots / 20.0
                placed[cell].append(
                    (variants.text(cat, amount), start, start + want_slots - 1))
                t -= amount

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
    _decorate(card, rng, profile)
    return card


def _decorate(card: Card, rng: random.Random, profile: dict) -> None:
    """Batter-card flourishes seen on every real card: exactly one
    'plus injury' result, one max-effort lineout, and a speed-dependent
    number of ++ groundouts (which favor the offense when the infield is
    in or a runner is being held)."""
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
    gb_splits = [s for _, _, s in card.iter_splits()
                 if s.text.startswith("groundball") and not s.text.endswith("++")]
    rng.shuffle(gb_splits)
    for split in gb_splits[: profile.get("plus_plus", 0)]:
        split.text += "++"


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
    notable = {"IBB", "SF", "HBP", "SO", "TBF", "IP"}
    warnings = [f"{f} not tracked for this season (treated as 0)"
                for f in stats.get("missing", []) if f in notable]
    if "CS" in stats.get("missing", []) and (stats.get("SB") or 0) > 0:
        warnings.append(
            "caught-stealing not tracked this season: stealing rating "
            "estimated from steal volume (capped at A)")
    return warnings


def generate_batter_card(stats: dict, league: dict,
                         position_ratings: list[tuple[str, int, int]] | None = None,
                         ) -> tuple[Card, list[str]]:
    """Generate a batter card. Returns (card, warnings).

    `position_ratings` is [(position, fielding rating, games)] from
    stratogen.fielding.position_ratings().
    """
    targets, warnings = batter_chance_targets(stats, league)
    warnings = (list(league.get("warnings", []))
                + _missing_data_warnings(stats) + warnings)
    card = layout_card(
        targets, card_type="batter",
        name=stats.get("name", "UNKNOWN").upper(),
        year=stats.get("year"), team=stats.get("team"),
        stats=_batting_display_stats(stats),
        header_lines=ratings.batter_header_lines(stats, position_ratings or []),
        profile=hit_profile(stats),
    )
    return card, warnings


def generate_pitcher_card(stats: dict, league: dict,
                          fielding_rating: int = 3) -> tuple[Card, list[str]]:
    targets, warnings = pitcher_chance_targets(stats, league)
    warnings = (list(league.get("warnings", []))
                + _missing_data_warnings(stats) + warnings)
    card = layout_card(
        targets, card_type="pitcher",
        name=stats.get("name", "UNKNOWN").upper(),
        year=stats.get("year"), team=stats.get("team"),
        stats=_pitching_display_stats(stats),
        header_lines=ratings.pitcher_header_lines(stats, fielding_rating),
        profile=pitcher_hit_profile(stats, league),
    )
    return card, warnings
