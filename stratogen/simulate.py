"""Statistical tester: what stats does a card actually produce?

The central idea: a Strat-O-Matic plate appearance reads the batter's card
half the time and the pitcher's card half the time. Since the dice and d20
probabilities are known exactly, the expected outcome distribution of a
(batter card, pitcher card) pairing can be computed in closed form — no
Monte Carlo noise. Cards are judged by how closely their implied rates
match the player's actual season rates.

X-chart chances (pitcher cards only) resolve through the fielding chart, so
their outcome depends on the defense, not the card. With league-average
defense they yield roughly 4.9 singles per 30 chances (Bundy's analysis);
everything else is an out or an error, and errors behave like outs for
rate-stat purposes (batter reaches but gets no hit, pitcher is charged no
hit). X_SINGLE_RATE captures this; see its comment for the check against
the real pitcher cards.

A Monte Carlo season simulator is also provided for demos and sanity
checks; the exact computation is what the tests use.
"""

from __future__ import annotations

import random

from .model import (
    Card, DICE_WEIGHTS, CHANCES_PER_CARD, CHANCES_PER_CYCLE,
    HR, TRIPLE, DOUBLE, SINGLE, WALK, HBP, SO, OUT, XCHANCE, CATEGORIES,
)

# Fraction of X-chart chances that become singles with average defense:
# 4.1 per 30, fitted to the real cards (Bundy's community figure was 4.9).
#
# Solving each official real pitcher card with a real season (4 .txt
# fixtures + the JSON basic sides; tests/test_benchmark.py::
# test_x_single_rate_is_consistent_with_real_pitcher_cards) for the X rate
# that reproduces his hits allowed: over 15 cards the mean is 4.15 per 30
# (median 4.02, SE 0.36; Bruney 2008 and Kirby 1975 1.9, Colon 2016 8.2),
# so 4.9 sat 2.1 SE high, past the 2-SE bar set for refitting. Held out,
# the rate fitted on the other 14 cards predicts each card's hits allowed
# better than 4.9 on 13 of 15 (mean |H/PA error| .0056 -> .0038). 4.1 sits
# between the mean and median. Generated cards keep their hit totals (the
# X block's singles come out of the singles), and the game engine's
# calibration held (see game.py / README).
X_SINGLE_RATE = 4.1 / 30.0

RATE_CATEGORIES = (HR, TRIPLE, DOUBLE, SINGLE, WALK, HBP, SO, OUT)


def card_chances(card_or_chances) -> dict[str, float]:
    """Accept a Card or a {category: chances} dict; return chances dict."""
    if isinstance(card_or_chances, Card):
        return card_or_chances.chances()
    chances = {cat: 0.0 for cat in CATEGORIES}
    chances.update(card_or_chances)
    return chances


def resolve_x(chances: dict[str, float],
              x_single_rate: float = X_SINGLE_RATE) -> dict[str, float]:
    """Fold X-chart chances into singles/outs assuming average defense."""
    resolved = {cat: chances.get(cat, 0.0) for cat in CATEGORIES}
    x = resolved.pop(XCHANCE, 0.0)
    resolved[SINGLE] += x * x_single_rate
    resolved[OUT] += x * (1.0 - x_single_rate)
    return resolved


def combined_rates(batter, pitcher,
                   x_single_rate: float = X_SINGLE_RATE,
                   batter_power: str = "N") -> dict[str, float]:
    """Exact per-PA outcome probabilities for a batter/pitcher card pairing.

    Either argument may be a laid-out Card or a {category: chances} dict
    (out of 108). Each card supplies half the 216-chance cycle.

    `batter_power` is the batter's advanced Power rating: against a
    Power-W batter the pitcher card's home runs (printed N-HR on advanced
    cards) read as SINGLE**. Every HR chance on the pitcher card is taken
    to be an N-HR (a chances dict can't tell them apart, and basic-game
    cards have no power ratings). The batter's own homers always count.
    """
    b = resolve_x(card_chances(batter), x_single_rate)
    p = resolve_x(card_chances(pitcher), x_single_rate)
    if batter_power == "W":
        p[SINGLE] += p[HR]
        p[HR] = 0.0
    elif batter_power != "N":
        raise ValueError(f"batter_power must be 'N' or 'W', got {batter_power!r}")
    return {cat: (b[cat] + p[cat]) / CHANCES_PER_CYCLE for cat in RATE_CATEGORIES}


def derived_stats(rates: dict[str, float]) -> dict[str, float]:
    """BA / OBP / SLG and component rates implied by per-PA probabilities.

    Per effective PA (AB + BB - IBB + HBP + SF): AB per PA here is
    1 - BB - HBP, so a sacrifice fly counts as a hitless at-bat, and on a
    basic card (no HBP results) so does every hit-by-pitch. Errors are
    folded into outs, so ROE counts as a hitless AB, as official scoring
    has it. To compare with a real season use implied_batting_line, which
    puts the card's rates over the season's own AB and PA.
    """
    hit = rates[HR] + rates[TRIPLE] + rates[DOUBLE] + rates[SINGLE]
    ab = 1.0 - rates[WALK] - rates[HBP]
    total_bases = (rates[SINGLE] + 2 * rates[DOUBLE]
                   + 3 * rates[TRIPLE] + 4 * rates[HR])
    return {
        "BA": hit / ab if ab else 0.0,
        "OBP": hit + rates[WALK] + rates[HBP],
        "SLG": total_bases / ab if ab else 0.0,
        "H_per_PA": hit,
        **{cat: rates[cat] for cat in RATE_CATEGORIES},
    }


# --- actual season rates ---------------------------------------------------

def effective_pa(stats: dict) -> float:
    """PA that interact with the cards: AB + (BB - IBB) + HBP + SF.

    Intentional walks bypass the dice entirely, so they're excluded.
    Missing components (old seasons, printed card stat lines) count as 0.
    """
    return (stats.get("AB", 0) + stats.get("BB", 0) - stats.get("IBB", 0)
            + stats.get("HBP", 0) + stats.get("SF", 0))


def hits_from_stats(stats: dict) -> float:
    if "H" in stats and stats["H"]:
        return stats["H"]
    return round(stats.get("BA", 0.0) * stats.get("AB", 0))


def actual_batting_rates(stats: dict) -> dict[str, float]:
    """Per-PA outcome rates from a real batting line.

    Works with full Lahman lines or the partial stat lines printed on
    cards (H reconstructed from AVG x AB; IBB/HBP/SF default to 0).
    """
    pa = effective_pa(stats)
    if pa <= 0:
        raise ValueError("no plate appearances")
    h = hits_from_stats(stats)
    doubles = stats.get("2B", 0)
    triples = stats.get("3B", 0)
    hr = stats.get("HR", 0)
    singles = h - doubles - triples - hr
    rates = {
        HR: hr / pa,
        TRIPLE: triples / pa,
        DOUBLE: doubles / pa,
        SINGLE: singles / pa,
        WALK: (stats.get("BB", 0) - stats.get("IBB", 0)) / pa,
        HBP: stats.get("HBP", 0) / pa,
        SO: stats.get("SO", 0) / pa,
    }
    rates[OUT] = 1.0 - sum(rates.values())
    return rates


def _pitching_batters_faced(stats: dict) -> tuple[float, bool]:
    """(batters faced, estimated?): Lahman BFP, or when it wasn't tracked
    3 per inning + hits + walks + hit batsmen (calibrated per league in
    pitcher_effective_pa)."""
    tbf = stats.get("TBF") or 0
    if tbf:
        return tbf, False
    return (round(stats.get("IP", 0) * 3) + stats.get("H", 0)
            + stats.get("BB", 0) + (stats.get("HBP") or 0)), True


def _league_pitching_sums(year, lg) -> tuple[float, float] | None:
    """(sum of BFP - IBB, sum of the IP/H/BB/HBP estimate - IBB) over a
    league-season's pitchers, from LahmanDB.league_pitching_totals (which
    drops implausible partial BFP counts, as pitching_season does)."""
    from .lahman import default_db
    try:
        t = default_db().league_pitching_totals(year, lg)
    except KeyError:
        return None
    ibb = t["IBB"].total
    batters_faced = t["BFP"].total - ibb
    estimate = (t["IPouts"].total + t["H"].total + t["BB"].total
                + t["HBP"].total - ibb)
    return batters_faced, estimate


def _resolve_league(stats: dict, league: dict | None) -> dict | None:
    if league is not None:
        return league
    year, lg = stats.get("year"), stats.get("league")
    if not year or not lg:
        return None
    from .lahman import default_db
    try:
        return default_db().league_batting(year, lg)
    except KeyError:
        return None


def pitcher_effective_pa(stats: dict, league: dict | None = None) -> float:
    """Batters faced that interact with the cards, on the same footing as
    the league's effective PA (AB + BB - IBB + HBP + SF): Lahman BFP minus
    intentional walks and sacrifice hits. A sacrifice bunt is a manager's
    decision, not a card result (game.py plays bunts separately), and
    league and batter rates leave them out, so a pitcher's rates must too.

    - Player SH tracked (pitching SH is complete from 1970, and in the
      Negro Leagues): BFP - IBB - SH, exact.
    - SH not tracked: (BFP - IBB) times the league-season's factor
      PA_eff / sum(BFP - IBB) over its pitchers, which also absorbs the
      seasons whose SH included sacrifice flies (1908-1930) and the early
      seasons whose BFP already left sacrifices out.
    - BFP not tracked (essentially 1925 NNL/ECL): estimated as 3 per
      inning + H + BB + HBP, scaled by the league's PA_eff / sum of the
      same estimate (the raw estimate runs 3-5% high: IP outs include
      caught stealing and the second out of double plays).

    `league` is LahmanDB.league_batting(year, lg); when omitted it's looked
    up from stats['year'] / stats['league'] if present. Without a league
    the uncorrected BFP - IBB (or estimate - IBB) is returned.
    """
    tbf, estimated = _pitching_batters_faced(stats)
    pa = tbf - (stats.get("IBB") or 0)
    missing = stats.get("missing") or ()
    if not estimated and "SH" in stats and "SH" not in missing:
        return pa - (stats.get("SH") or 0)
    league = _resolve_league(stats, league)
    if not league or not league.get("PA_eff"):
        return pa
    sums = _league_pitching_sums(league.get("year"), league.get("league"))
    if not sums:
        return pa
    total = sums[1] if estimated else sums[0]
    return pa * (league["PA_eff"] / total) if total > 0 else pa


def actual_pitching_rates(stats: dict, league: dict | None = None,
                          ) -> dict[str, float]:
    """Per-batter outcome rates from a real pitching line, per effective
    batter faced (pitcher_effective_pa; `league` as there).

    2B/3B allowed aren't tracked, so only H (total), HR, BB, SO and OUT
    are meaningful; doubles/triples are reported as part of H only.
    """
    tbf_eff = pitcher_effective_pa(stats, league)
    if tbf_eff <= 0:
        raise ValueError("no batters faced")
    h = stats.get("H", 0)
    hr = stats.get("HR", 0)
    return {
        "H_per_PA": h / tbf_eff,
        HR: hr / tbf_eff,
        WALK: (stats.get("BB", 0) - stats.get("IBB", 0)) / tbf_eff,
        SO: stats.get("SO", 0) / tbf_eff,
    }


def implied_batting_line(implied: dict[str, float], stats: dict) -> dict:
    """A card's implied rates (derived_stats) as the season's line: hits,
    walks and HBP over the season's effective PA, BA over its actual AB and
    OBP over AB + BB + HBP + SF (intentional walks, which bypass the cards,
    added as drawn), next to the same figures from the real line. Both
    sides share denominators, so matching hits means matching BA (the
    per-PA BA of derived_stats counts sacrifice flies, and on basic cards
    HBP, as at-bats)."""
    pa = effective_pa(stats)
    ab = stats.get("AB", 0)
    bb, ibb = stats.get("BB", 0), stats.get("IBB") or 0
    hbp, sf = stats.get("HBP") or 0, stats.get("SF") or 0
    obp_den = ab + bb + hbp + sf
    h = implied["H_per_PA"] * pa
    walks = implied[WALK] * pa + ibb
    hbps = implied[HBP] * pa
    actual_h = hits_from_stats(stats)
    return {
        "H": h, "BB": walks, "HBP": hbps,
        "BA": h / ab if ab else 0.0,
        "OBP": (h + walks + hbps) / obp_den if obp_den else 0.0,
        "actual_BA": actual_h / ab if ab else 0.0,
        "actual_OBP": (actual_h + bb + hbp) / obp_den if obp_den else 0.0,
    }


def batting_errors(implied: dict[str, float],
                   actual: dict[str, float]) -> dict[str, float]:
    """Absolute rate errors between card-implied and actual batting rates.
    BA is compared on one denominator (the actual line's AB per PA), so it
    is the hit-rate miss scaled to at-bats: a card that matches hits
    matches BA."""
    actual_hit = actual[HR] + actual[TRIPLE] + actual[DOUBLE] + actual[SINGLE]
    actual_ab = 1.0 - actual[WALK] - actual[HBP]
    errors = {cat: abs(implied[cat] - actual[cat])
              for cat in (HR, TRIPLE, DOUBLE, SINGLE, WALK, SO)}
    errors["H_per_PA"] = abs(implied["H_per_PA"] - actual_hit)
    errors["BA"] = errors["H_per_PA"] / actual_ab if actual_ab > 0 else 0.0
    return errors


def pitching_errors(implied: dict[str, float],
                    actual: dict[str, float]) -> dict[str, float]:
    return {key: abs(implied[key] - actual[key])
            for key in ("H_per_PA", HR, WALK, SO)}


# --- Monte Carlo (demo / sanity only) --------------------------------------

_DICE_SUMS = [d1 + d2 for d1 in range(1, 7) for d2 in range(1, 7)]


def simulate_pa(batter: Card, pitcher: Card, rng: random.Random,
                x_single_rate: float = X_SINGLE_RATE) -> str:
    """Play one plate appearance; returns an outcome category."""
    white = rng.randint(1, 6)
    card = batter if white <= 3 else pitcher
    column = card.column_numbers[(white - 1) % 3]
    dice_sum = rng.choice(_DICE_SUMS)
    roll20 = rng.randint(1, 20)
    for split in card.columns[column][dice_sum]:
        if split.lo <= roll20 <= split.hi:
            cat = split.category
            if cat == XCHANCE:
                return SINGLE if rng.random() < x_single_rate else OUT
            return cat
    raise AssertionError("d20 ranges must cover 1-20")


def simulate_season(batter: Card, pitcher: Card, num_pa: int = 50000,
                    seed: int = 0) -> dict[str, int]:
    """Monte Carlo season; returns counting stats per category."""
    rng = random.Random(seed)
    counts = {cat: 0 for cat in RATE_CATEGORIES}
    for _ in range(num_pa):
        counts[simulate_pa(batter, pitcher, rng)] += 1
    counts["PA"] = num_pa
    return counts
