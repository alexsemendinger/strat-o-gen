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
hit). X_SINGLE_RATE captures this and can be recalibrated against real
pitcher cards.

A Monte Carlo season simulator is also provided for demos and sanity
checks; the exact computation is what the tests use.
"""

from __future__ import annotations

import random

from .model import (
    Card, DICE_WEIGHTS, CHANCES_PER_CARD, CHANCES_PER_CYCLE,
    HR, TRIPLE, DOUBLE, SINGLE, WALK, HBP, SO, OUT, XCHANCE, CATEGORIES,
)

# Fraction of X-chart chances that become singles with average defense
# (Bundy: ~4.9 hits per 30 X chances).
X_SINGLE_RATE = 4.9 / 30.0

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
                   x_single_rate: float = X_SINGLE_RATE) -> dict[str, float]:
    """Exact per-PA outcome probabilities for a batter/pitcher card pairing.

    Either argument may be a laid-out Card or a {category: chances} dict
    (out of 108). Each card supplies half the 216-chance cycle.
    """
    b = resolve_x(card_chances(batter), x_single_rate)
    p = resolve_x(card_chances(pitcher), x_single_rate)
    return {cat: (b[cat] + p[cat]) / CHANCES_PER_CYCLE for cat in RATE_CATEGORIES}


def derived_stats(rates: dict[str, float]) -> dict[str, float]:
    """BA / OBP / SLG and component rates implied by per-PA probabilities.

    AB per PA here is 1 - BB - HBP (sacrifices aren't modeled on cards),
    and errors are folded into outs, so ROE counts as a hitless AB —
    matching how official scoring treats it.
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


def actual_pitching_rates(stats: dict) -> dict[str, float]:
    """Per-batter outcome rates from a real pitching line.

    2B/3B allowed aren't tracked, so only H (total), HR, BB, SO and OUT
    are meaningful; doubles/triples are reported as part of H only.
    """
    tbf = stats.get("TBF", 0)
    if not tbf:
        # Estimate batters faced when not tracked: 3 outs/inning + baserunners
        tbf = stats.get("IP", 0) * 3 + stats.get("H", 0) + stats.get("BB", 0)
    tbf_eff = tbf - stats.get("IBB", 0)
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


def batting_errors(implied: dict[str, float],
                   actual: dict[str, float]) -> dict[str, float]:
    """Absolute rate errors between card-implied and actual batting rates."""
    actual_hit = actual[HR] + actual[TRIPLE] + actual[DOUBLE] + actual[SINGLE]
    actual_ab = 1.0 - actual[WALK] - actual[HBP]
    errors = {cat: abs(implied[cat] - actual[cat])
              for cat in (HR, TRIPLE, DOUBLE, SINGLE, WALK, SO)}
    errors["H_per_PA"] = abs(implied["H_per_PA"] - actual_hit)
    errors["BA"] = abs(implied["BA"] - actual_hit / actual_ab)
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
