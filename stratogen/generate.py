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

Advanced (platoon) cards apply the same formula per matchup grid, with
matchup rates and the player's split from stratogen.platoon, plus two
advanced-game rules: Power-W batters read the pitcher grid's N-HR as
singles (their own grid carries all their homers, so W never clamps), and
batter grids carry HBP as whole chances. The same target code serves
both: batter_targets_from_rates / pitcher_targets_from_rates.
"""

from __future__ import annotations

import random
import re

from .model import (
    AdvancedCard, Card, PlatoonSide, Split, DICE_WEIGHTS, CHANCES_PER_CARD,
    BATTER_COLUMNS, PITCHER_COLUMNS, X_CHANCES_PER_PITCHER_CARD,
    HR, TRIPLE, DOUBLE, SINGLE, WALK, HBP, SO, OUT, XCHANCE,
)
from .simulate import (
    X_SINGLE_RATE, actual_batting_rates, effective_pa, hits_from_stats,
)
from . import platoon, ratings

# Smallest chance worth placing: a 1-in-20 split of a weight-1 row is 0.05.
_EPSILON = 0.026
# Smallest miss worth a warning, per PA: anything less prints as "~0.0%".
_WARN_PER_PA = 0.001


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
    return batter_targets_from_rates(rate, league_rate, warnings), warnings


def batter_targets_from_rates(rate: dict, league_rate: dict, warnings: list[str],
                              *, weak_power: bool = False,
                              hbp_chances: int = 0,
                              overflow: list | None = None) -> dict:
    """Chance targets for one batter grid from per-PA rates.

    Shared by the basic card and each advanced platoon side. `rate` and
    `league_rate` map WALK/SO/HR/TRIPLE/DOUBLE/SINGLE to per-PA rates
    (league_rate = what the opposing average pitcher grid supplies).
    Warnings are appended to `warnings`; if the line overflows the card,
    the excess chances are appended to `overflow` (when given).

    `weak_power` (advanced Power-W): the opposing pitcher grid's N-HR
    chances read as SINGLE** for this batter, so his own grid carries all
    his home runs (2 * rate * 108, no league subtraction — never clamps)
    and the pitcher's HR chances count against his singles.
    `hbp_chances` (advanced batter sides): whole HBP chances placed as-is.
    """
    if weak_power:
        league_rate = dict(league_rate)
        league_rate[SINGLE] = league_rate[SINGLE] + league_rate[HR]
        league_rate[HR] = 0.0
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

    if hbp_chances:
        targets[HBP] = float(hbp_chances)  # whole chances
    non_out = sum(targets.values())
    if non_out > CHANCES_PER_CARD:
        if overflow is not None:
            overflow.append(non_out - CHANCES_PER_CARD)
        if HBP in targets:  # scaled too, but kept whole
            targets[HBP] = float(int(targets[HBP] * CHANCES_PER_CARD / non_out))
        fixed = targets.get(HBP, 0)
        rest = non_out - hbp_chances
        scale = (CHANCES_PER_CARD - fixed) / rest if rest else 0.0
        targets = {cat: (t * scale if cat != HBP else t)
                   for cat, t in targets.items()}
        warnings.append("extreme stat line: chances scaled to fit the card")
        non_out = CHANCES_PER_CARD
    targets[OUT] = CHANCES_PER_CARD - non_out
    return targets


def pitcher_chance_targets(stats: dict, league: dict) -> tuple[dict, list[str]]:
    warnings = []
    rate_bb, rate_k, rate_hr, rate_h = _pitching_rates(stats, league, warnings)
    targets = pitcher_targets_from_rates(rate_bb, rate_k, rate_hr, rate_h,
                                         league, warnings)
    return targets, warnings


def _pitching_rates(stats: dict, league: dict,
                    warnings: list[str]) -> tuple[float, ...]:
    """(BB, SO, HR, H) per effective batter faced; warns about estimated
    or small samples."""
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
    return rate_bb, rate_k, rate_hr, rate_h


def pitcher_targets_from_rates(rate_bb: float, rate_k: float, rate_hr: float,
                               rate_h: float, league: dict, warnings: list[str],
                               *, weak_share: float = 0.0,
                               overflow: list | None = None) -> dict:
    """Chance targets for one pitcher grid from per-batter rates.

    Shared by the basic card and each advanced platoon side. `league`
    holds the rates the opposing average batter grid supplies (the keys
    of LahmanDB.league_batting). Warnings are appended to `warnings`; if
    the line overflows the card, the excess chances are appended to
    `overflow` (when given).

    `weak_share` (advanced sides): the share of this matchup's PA taken by
    Power-W batters, against whom this grid's N-HR chances read as
    singles. See _amplify_n_hr for the exact accounting.
    """
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
    if d_h / 216 >= _WARN_PER_PA:
        warnings.append(
            f"hits allowed will run ~{d_h / 216:.1%} of PA high: pitcher allows "
            f"far fewer hits than league average and the card can't go negative")

    # The X block is normally 30 chances, but an extreme card may not have
    # room for it: a modern strikeout reliever's line can overflow the card
    # (each X chance costs 1 - X_SINGLE_RATE of capacity beyond the hits it
    # absorbs), and a pitcher who allowed fewer hits than the block's own
    # X_SINGLE_RATE singles can't carry all 30 without allowing hits he
    # never did. Shrink it before resorting to scaling.
    committed = targets[WALK] + targets[SO] + total_hits
    x_room = int((CHANCES_PER_CARD - committed) / (1.0 - X_SINGLE_RATE))
    x_hit_room = int(total_hits / X_SINGLE_RATE + 1e-9)
    x_block = max(0, min(X_CHANCES_PER_PITCHER_CARD, x_room, x_hit_room))
    if x_block < X_CHANCES_PER_PITCHER_CARD:
        why = ("to fit the card" if x_room <= x_hit_room else
               "so its singles don't exceed the hits he allowed")
        warnings.append(
            f"extreme stat line: X-chart block reduced to {x_block} chances "
            f"(normally {X_CHANCES_PER_PITCHER_CARD}) {why}")
    x_hits = x_block * X_SINGLE_RATE
    regular_hits = total_hits - x_hits          # >= 0 by the cap above
    if targets[HR] > regular_hits:
        trimmed = targets[HR] - regular_hits
        targets[HR] = regular_hits
        if trimmed / 216 >= _WARN_PER_PA:
            warnings.append(
                f"home runs allowed will run ~{trimmed / 216:.1%} of PA low: "
                f"the card's hit total can't hold them all")
    # 2B/3B allowed aren't tracked historically, so every non-HR hit the
    # card yields (X-chart singles included) follows the league's 1B/2B/3B
    # mix; the X block only ever yields singles, so its hits come out of
    # the singles share alone (a league-average line reproduces
    # average_pitcher_chances exactly).
    non_hr = total_hits - targets[HR]
    lg_non_hr = league["1B_per_PA"] + league["2B_per_PA"] + league["3B_per_PA"]
    targets[SINGLE] = non_hr * (league["1B_per_PA"] / lg_non_hr) - x_hits
    targets[DOUBLE] = non_hr * (league["2B_per_PA"] / lg_non_hr)
    targets[TRIPLE] = non_hr * (league["3B_per_PA"] / lg_non_hr)
    for cat in (DOUBLE, TRIPLE):   # too few singles for the X block's hits
        take = min(targets[cat], max(0.0, -targets[SINGLE]))
        targets[cat] -= take
        targets[SINGLE] += take
    targets[SINGLE] = max(0.0, targets[SINGLE])
    if weak_share > 0:
        _amplify_n_hr(targets, rate_hr, league, weak_share, warnings)

    targets[XCHANCE] = float(x_block)
    non_out = sum(targets.values())
    if non_out > CHANCES_PER_CARD:
        if overflow is not None:
            overflow.append(non_out - CHANCES_PER_CARD)
        scale = (CHANCES_PER_CARD - targets[XCHANCE]) / (non_out - targets[XCHANCE])
        targets = {cat: (t * scale if cat != XCHANCE else t)
                   for cat, t in targets.items()}
        warnings.append("extreme stat line: chances scaled to fit the card")
        non_out = CHANCES_PER_CARD
    targets[OUT] = CHANCES_PER_CARD - non_out
    return targets


# Largest Power-W share the N-HR amplification honors (1/(1-w) <= 4). In
# dead-ball leagues nearly every hitter is Power-W, so exactness would
# need absurd N-HR counts that only the rare N hitter ever sees; past
# this point pitcher home runs mostly come off batter cards (warned).
MAX_WEAK_SHARE = 0.75
_HR_WARN = 0.0005  # per PA; smaller misses round to "0.0%" and aren't news


def _amplify_n_hr(targets: dict, rate_hr: float, league: dict,
                  weak_share: float, warnings: list[str]) -> None:
    """Exact HR accounting for a pitcher grid against Power-W batters.

    A pitcher grid's N-HR chances are homers only against Power-N
    batters (share 1 - w); against Power-W batters they read as singles.
    Power-W batters' own grids carry all of their home runs, so the
    average batter grid in this matchup carries 108 * lg_HR * (1 + w) HR
    chances (N batters (2r - lg) * 108, W batters 2r * 108, PA-weighted),
    while the average pitcher grid keeps 108 * lg_HR N-HR — the reference
    batter grids are built against, so the league closes exactly. The
    pitcher's HR rate against that population is reproduced when

        N-HR = 108 * lg_HR + 216 * (rate_hr - lg_HR) / (1 - w)

    i.e. his deviation from the average pitcher is amplified by 1/(1-w)
    because only N batters can read it. Total hits stay those of the
    basic formula: N-HR chances above the basic HR target come out of
    singles (they are the singles W batters read off them), and N-HR
    below it go back to singles. The amplification is capped at
    MAX_WEAK_SHARE.
    """
    lg_hr = league["HR_per_PA"]
    w = min(weak_share, MAX_WEAK_SHARE)
    want = max(0.0, (lg_hr + 2.0 * (rate_hr - lg_hr) / (1.0 - w)) * 108.0)
    extra = want - targets[HR]
    if extra <= 0:
        targets[HR] += extra
        targets[SINGLE] -= extra
    else:  # if singles run out, doubles/triples pay; beyond that it's lost
        for cat in (SINGLE, DOUBLE, TRIPLE):
            take = min(targets[cat], extra)
            targets[cat] -= take
            targets[HR] += take
            extra -= take
    # What this grid actually yields against the matchup's batters:
    effective = (108.0 * lg_hr * (1.0 + weak_share)
                 + (1.0 - weak_share) * targets[HR]) / 216.0
    off = effective - rate_hr
    if off >= _HR_WARN:
        warnings.append(
            f"home runs allowed will run ~{off:.1%} of PA high: Power-W hitters "
            f"carry their own homers and the card can't go negative")
    elif -off >= _HR_WARN:
        warnings.append(
            f"home runs allowed will run ~{-off:.1%} of PA low: most of this "
            f"league's hitters are Power-W, so few batters can read the "
            f"pitcher card's N-HR")


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


def average_advanced_batter_chances(cell_league: dict,
                                    weak_share: float = 0.0) -> dict:
    """Average advanced batter grid in one matchup (cell_league from
    PlatoonContext.cell_league), as the PA-weighted mean of the grids the
    advanced generator builds: Power-N grids carry (2r - lg) * 108 HR,
    Power-W grids 2r * 108 HR with the pitcher's N-HR taken out of their
    singles, so the mean carries 108 * lg_HR * (1 + w) HR and
    108 * (lg_1B - w * lg_HR) singles. Pitcher grids carry no HBP, so the
    batter grids supply all of it (2 * lg_HBP * 108)."""
    lg = cell_league
    targets = {
        WALK: lg["BB_per_PA"] * 108,
        SO: lg["K_per_PA"] * 108,
        HR: lg["HR_per_PA"] * 108 * (1.0 + weak_share),
        TRIPLE: lg["3B_per_PA"] * 108,
        DOUBLE: lg["2B_per_PA"] * 108,
        SINGLE: (lg["1B_per_PA"] - weak_share * lg["HR_per_PA"]) * 108,
        HBP: 2.0 * lg.get("HBP_per_PA", 0.0) * 108,
    }
    targets[OUT] = CHANCES_PER_CARD - sum(targets.values())
    return targets


def average_advanced_pitcher_chances(cell_league: dict) -> dict:
    """Average advanced pitcher grid in one matchup: the basic average
    pitcher card at the matchup's rates (its HR chances print as N-HR)."""
    return average_pitcher_chances(cell_league)


# --- advanced (platoon) cards --------------------------------------------------

def _lahman_hand(stats: dict, key: str) -> str | None:
    pid = stats.get("player_id")
    if not pid:
        return None
    from .lahman import default_db
    return default_db().player_info(pid).get(key)


_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def merge_side_warnings(by_side: dict[str, list[str]]) -> list[str]:
    """Label per-side warnings with their side and merge the ones both
    sides share: "vs LHP/RHP: walks will run ~1.2%/0.8% of PA high ..."."""
    groups: dict[str, dict[str, str]] = {}
    for side, msgs in by_side.items():
        for msg in msgs:
            groups.setdefault(_NUMBER.sub("#", msg), {}).setdefault(side, msg)
    out = []
    for per_side in groups.values():
        sides = "/".join(per_side)
        msgs = list(per_side.values())
        slots = iter(zip(*(_NUMBER.findall(m) for m in msgs)))
        merged = _NUMBER.sub(
            lambda _m: "/".join(dict.fromkeys(next(slots))), msgs[0])
        out.append(f"vs {sides}: {merged}")
    return out


# Split strengths tried, strongest first, when an extreme stat line won't
# fit one grid (the same-handed grid of a 52%-strikeout reliever needs more
# than 108 chances). Narrowing the split (factors ** strength) moves the
# excess to the other grid while the share-weighted line stays exact.
_SPLIT_STRENGTHS = (1.0, 0.75, 0.5, 0.25, 0.0)


def _fit_split(build):
    """Pick the strongest split that loses the fewest chances to card
    overflow. build(strength) -> (targets by side, warnings by side,
    share-weighted overflow in chances)."""
    best = None
    for strength in _SPLIT_STRENGTHS:
        result = build(strength)
        if best is None or result[2] < best[1][2] - 1e-9:
            best = (strength, result)
        if result[2] <= 0:
            break
    strength, (targets, side_warnings, _overflow) = best
    notes = []
    if strength < 1.0:
        notes.append(f"platoon split narrowed to {strength:.0%} of the league "
                     f"norm so the grids fit 108 chances")
    return targets, side_warnings, notes


def generate_advanced_batter_card(
        stats: dict, league: dict,
        position_ratings: list[tuple[str, int, int]] | None = None,
        *, bats: str | None = None, context=None,
        ) -> tuple[AdvancedCard, list[str]]:
    """Generate the advanced (platoon) side of a batter card.

    Each grid reproduces the batter's estimated rate in its matchup
    exactly against the matchup's average pitcher grid (see
    stratogen.platoon): `bats` defaults to the Lahman People record,
    `context` to platoon.league_context(league). Power-W grids carry all
    of the batter's homers; both grids carry his HBP as whole chances.
    Returns (card, warnings).
    """
    warnings = []
    pa = effective_pa(stats)
    if pa <= 0:
        raise ValueError("player has no effective plate appearances")
    if pa < 100:
        warnings.append(f"small sample: only {pa:.0f} effective PA")
    ctx = context or platoon.league_context(league)
    hand = platoon.batting_hand(bats or _lahman_hand(stats, "bats"))
    if hand == "?":
        warnings.append("batting hand unknown: treated as right-handed")
        hand = "R"

    rates = actual_batting_rates(stats)
    s_lhp = platoon.printed_share(platoon.batter_lhp_share(hand, pa, ctx))
    shares = {"L": s_lhp, "R": 1.0 - s_lhp}
    # Pitcher grids carry no HBP, so the batter's grids carry all of his:
    # 2 * rate * 108, whole chances, the same on both grids.
    hbp = int(round(2.0 * rates[HBP] * 108))
    cells = {p: ctx.cell_league(p, platoon.effective_hand(hand, p))
             for p in platoon.HANDS}
    power: dict[str, str] = {}

    def build(strength):
        split = platoon.split_rates(
            {c: rates[c] for c in platoon.PLATOON_CATEGORIES},
            platoon.soften(ctx.batter_factors(hand), strength), shares)
        targets, side_warnings, lost = {}, {}, 0.0
        for p in platoon.HANDS:
            cell, r = cells[p], split[p]
            power[p] = platoon.power_rating(r[HR], cell["HR_per_PA"])
            league_rate = {WALK: cell["BB_per_PA"], SO: cell["K_per_PA"],
                           HR: cell["HR_per_PA"], TRIPLE: cell["3B_per_PA"],
                           DOUBLE: cell["2B_per_PA"], SINGLE: cell["1B_per_PA"]}
            side_warnings[f"{p}HP"], overflow = [], []
            targets[p] = batter_targets_from_rates(
                r, league_rate, side_warnings[f"{p}HP"],
                weak_power=(power[p] == "W"), hbp_chances=hbp,
                overflow=overflow)
            lost += shares[p] * sum(overflow)
        return targets, side_warnings, lost

    targets, side_warnings, notes = _fit_split(build)
    name = stats.get("name", "UNKNOWN").upper()
    display = _batting_display_stats(stats)
    header = ratings.batter_header_lines(stats, position_ratings or [])
    profile = hit_profile(stats)
    sides = []
    for p in platoon.HANDS:
        card = layout_card(
            targets[p], card_type="batter", name=name, year=stats.get("year"),
            team=stats.get("team"), stats=display, header_lines=header,
            profile=profile, seed_extra=f"advanced vs {p}HP")
        sides.append(PlatoonSide(vs=f"{p}HP", share=shares[p], card=card,
                                 power=power[p]))
    warnings = (list(league.get("warnings", [])) + _missing_data_warnings(stats)
                + list(ctx.warnings) + warnings + notes
                + merge_side_warnings(side_warnings))
    return AdvancedCard(name=name, card_type="batter", hand=hand,
                        team=stats.get("team"), year=stats.get("year"),
                        header_lines=header, stats=display,
                        sides=sides), warnings


def generate_advanced_pitcher_card(
        stats: dict, league: dict, fielding_rating: int = 3,
        *, throws: str | None = None, context=None,
        ) -> tuple[AdvancedCard, list[str]]:
    """Generate the advanced (platoon) side of a pitcher card.

    One grid per batter hand (switch hitters bat opposite the pitcher),
    each with the usual 30-chance X block and home runs printed N-HR.
    N-HR chances are amplified for the Power-W hitters who can't read
    them (see _amplify_n_hr), so the pitcher's line is reproduced against
    the matchup's real mix of N and W batters. Returns (card, warnings).
    """
    warnings = []
    rate_bb, rate_k, rate_hr, rate_h = _pitching_rates(stats, league, warnings)
    ctx = context or platoon.league_context(league)
    hand = platoon.throwing_hand(throws or _lahman_hand(stats, "throws"))
    if hand == "?":
        warnings.append("throwing hand unknown: treated as right-handed")
        hand = "R"

    s_lhb = platoon.printed_share(platoon.pitcher_lhb_share(hand, ctx))
    shares = {"L": s_lhb, "R": 1.0 - s_lhb}

    def build(strength):
        split = platoon.split_rates(
            {WALK: rate_bb, SO: rate_k, HR: rate_hr, "H": rate_h},
            platoon.soften(ctx.pitcher_factors(hand), strength), shares)
        targets, side_warnings, lost = {}, {}, 0.0
        for h in platoon.HANDS:
            r = split[h]
            side_warnings[f"{h}HB"], overflow = [], []
            targets[h] = pitcher_targets_from_rates(
                r[WALK], r[SO], r[HR], r["H"], ctx.cell_league(hand, h),
                side_warnings[f"{h}HB"], weak_share=ctx.weak_share[(hand, h)],
                overflow=overflow)
            lost += shares[h] * sum(overflow)
        return targets, side_warnings, lost

    targets, side_warnings, notes = _fit_split(build)
    name = stats.get("name", "UNKNOWN").upper()
    display = _pitching_display_stats(stats)
    header = ratings.pitcher_header_lines(stats, fielding_rating)
    profile = pitcher_hit_profile(stats, league)
    sides = []
    for h in platoon.HANDS:
        card = layout_card(
            targets[h], card_type="pitcher", name=name, year=stats.get("year"),
            team=stats.get("team"), stats=display, header_lines=header,
            profile=profile, seed_extra=f"advanced vs {h}HB", hr_text="N-HR")
        sides.append(PlatoonSide(vs=f"{h}HB", share=shares[h], card=card))
    warnings = (list(league.get("warnings", [])) + _missing_data_warnings(stats)
                + list(ctx.warnings) + warnings + notes
                + merge_side_warnings(side_warnings))
    return AdvancedCard(name=name, card_type="pitcher", hand=hand,
                        team=stats.get("team"), year=stats.get("year"),
                        header_lines=header, stats=display,
                        sides=sides), warnings


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
                    "double_2star": 0.32, "gb_a": 0.70, "plus_plus": 1}


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
                else clamp(0.17 + 26.0 * gidp / pa, 0.15, 1.0),
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
        profile["gb_a"] = max(0.15, min(1.0, 0.17 + 26.0 * gidp / tbf))
    profile["plus_plus"] = 0
    return profile


class _OutFlavors:
    """Deterministic out-text generator in the style of real cards."""

    _GB_POS = ["ss", "3b", "2b", "1b", "p"]
    _FB_POS = ["lf", "cf", "rf"]
    # Chance-weighted from the 39 real cards in data/real_cards (non-X outs):
    # batter cards 55% groundball / 22% flyball / 9% lineout / 12% popout /
    # 1% foulout, grounders A or B only (no C), flyballs 97% B / 3% A, hit
    # mostly to ss/3b; pitcher cards 26/48/10/16/0 (their grounders are
    # mostly X chances), grounders 40% B / 60% C (no A), flyballs 83% B /
    # 17% C, hit mostly to 2b/1b.
    _MIX = {"batter": (0.55, 0.77, 0.86, 0.98), "pitcher": (0.26, 0.74, 0.84, 1.0)}
    _GB_WEIGHTS = {"batter": [38, 29, 15, 8, 10], "pitcher": [14, 11, 40, 22, 14]}
    _FB_LETTERS = {"batter": [3, 97, 0], "pitcher": [0, 83, 17]}

    def __init__(self, rng: random.Random, card_type: str, profile: dict):
        self.rng = rng
        self.card_type = card_type
        self.profile = profile

    def next(self) -> str:
        roll = self.rng.random()
        kind = "batter" if self.card_type == "batter" else "pitcher"
        gb, fb, lo, po = self._MIX[kind]
        if roll < gb:
            pos = self.rng.choices(self._GB_POS, weights=self._GB_WEIGHTS[kind])[0]
            gb_a = self.profile["gb_a"] if kind == "batter" else 0.0
            c_share = 0.0 if kind == "batter" else 0.60
            rating = self.rng.choices(
                ["A", "B", "C"],
                weights=[gb_a, (1 - c_share) * (1 - gb_a), c_share * (1 - gb_a)])[0]
            return f"groundball ({pos}){rating}"
        if roll < fb:
            pos = self.rng.choice(self._FB_POS)
            rating = self.rng.choices(["A", "B", "C"],
                                      weights=self._FB_LETTERS[kind])[0]
            return f"flyball ({pos}){rating}"
        if roll < lo:
            return f"lineout ({self.rng.choice(self._GB_POS[:4])})"
        if roll < po:
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

    def __init__(self, rng: random.Random, profile: dict,
                 hr_text: str = "HOMERUN"):
        p = profile
        self._hr_text = hr_text
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
        return {HR: self._hr_text, TRIPLE: "TRIPLE", WALK: "WALK",
                SO: "strikeout", HBP: "HBP"}[cat]


def _hbp_cells(n: int, free: dict, rng: random.Random) -> list[tuple[int, int]]:
    """Whole cells worth exactly `n` chances for HBP, on the edge rows the
    real advanced cards use (2/12, then 3/11 or 4/10): one weight-1 cell
    first, then the largest edge weight that fits (Judge 2024's 3 = 1 + 2,
    Posada 2003's 4 = 1 + 3), spread over different columns."""
    chosen: list[tuple[int, int]] = []
    used_cols: set[int] = set()
    remaining = n
    while remaining > 0:
        want = 1 if not chosen else min(3, remaining)
        pool = [c for c in free if c not in chosen]
        cands = [c for c in pool if DICE_WEIGHTS[c[1]] == want]
        if not cands:
            fits = [c for c in pool if DICE_WEIGHTS[c[1]] <= remaining]
            if not fits:
                break
            top = max(DICE_WEIGHTS[c[1]] for c in fits)
            cands = [c for c in fits if DICE_WEIGHTS[c[1]] == top]
        fresh = [c for c in cands if c[0] not in used_cols] or cands
        cell = rng.choice(sorted(fresh))
        chosen.append(cell)
        used_cols.add(cell[0])
        remaining -= DICE_WEIGHTS[cell[1]]
    return chosen


def layout_card(targets: dict[str, float], *, card_type: str, name: str,
                year: int | None, team: str | None, stats: dict,
                header_lines: list[str], profile: dict | None = None,
                seed_extra: str = "", hr_text: str = "HOMERUN") -> Card:
    """Place chance targets on a 3x11 grid deterministically.

    The same player/year always produces the same card (the RNG that picks
    cosmetic out locations is seeded from name+year). `profile` (see
    hit_profile) controls the */**/++/DP-letter mix. `hr_text` is how home
    runs print ("N-HR" on advanced pitcher grids). Whole HBP chances
    (advanced batter grids) go on edge rows before anything else.
    """
    profile = profile or dict(_DEFAULT_PROFILE)
    rng = random.Random(f"{name}|{year}|{card_type}|{seed_extra}")
    flavors = _OutFlavors(rng, card_type, profile)
    variants = _HitVariants(rng, profile, hr_text)
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

    hbp = int(round(targets.get(HBP, 0)))
    if hbp > 0:
        for cell in _hbp_cells(hbp, free, rng):
            assign_full(cell, variants.text(HBP))

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
