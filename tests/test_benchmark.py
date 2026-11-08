"""The acceptance suite: real cards set the bar, generated cards must clear it.

Real Strat-O-Matic cards don't reproduce season stats perfectly (clamped
categories, d20 granularity, X-chart variance), so "perfect" isn't the
goal — matching official-card quality is. Both real and generated cards
are scored by the same exact-expectation tester against the same average
opposing card. Generated cards are built by inverting that tester, so a
misset tester parameter (X hit rate, average cards, HBP/sacrifice
handling) counts against the real cards only: the comparison guards the
generator's own losses, and the tester's parameters get their own checks
against the real cards (see the X-rate test below).
"""

import pytest

from stratogen.benchmark import benchmark_cases, score_case
from stratogen.generate import (
    average_batter_chances, average_pitcher_chances,
    batter_chance_targets, pitcher_chance_targets,
    generate_batter_card, generate_pitcher_card,
)
from stratogen.lahman import default_db
from stratogen.model import HR, WALK, SO, XCHANCE
from stratogen.simulate import combined_rates, derived_stats

CASES = {c.stem: c for c in benchmark_cases()}
TRUSTED = {s: c for s, c in CASES.items() if not c.synthetic}


def _generated(case):
    fn = generate_pitcher_card if case.card.card_type == "pitcher" \
        else generate_batter_card
    card, _warnings = fn(case.actual_stats, case.league)
    return card


# --- the bar: real cards score well under the tester -----------------------

@pytest.mark.parametrize("stem", sorted(s for s, c in TRUSTED.items()
                                        if c.card.card_type == "batter"))
def test_real_batter_cards_reproduce_stats(stem):
    err = score_case(TRUSTED[stem])
    assert err["BA"] < 0.010, err
    assert err["H_per_PA"] < 0.010, err
    assert err[HR] < 0.010 and err[WALK] < 0.010 and err[SO] < 0.010, err


@pytest.mark.parametrize("stem", sorted(s for s, c in TRUSTED.items()
                                        if c.card.card_type == "pitcher"))
def test_real_pitcher_cards_reproduce_stats(stem):
    err = score_case(TRUSTED[stem])
    assert err["H_per_PA"] < 0.020, err
    assert err[HR] < 0.010 and err[WALK] < 0.010 and err[SO] < 0.010, err


# --- generated cards must be at least as good as the real ones -------------

@pytest.mark.parametrize("stem", sorted(CASES))
def test_generated_card_matches_real_card_quality(stem):
    """Per category, the generated card's error may exceed the real card's
    by at most 0.002 per-PA (and the suspect synthetic cards are included:
    we must track *their printed stat line* at least as well too)."""
    case = CASES[stem]
    real_err = score_case(case)
    gen_err = score_case(case, _generated(case))
    for key, real_value in real_err.items():
        assert gen_err[key] <= real_value + 0.002, (
            f"{stem} {key}: generated {gen_err[key]:.4f} vs real {real_value:.4f}")


@pytest.mark.parametrize("stem", sorted(CASES))
def test_layout_preserves_chance_targets(stem):
    """The printed grid must carry the computed chances faithfully —
    this is where the old implementation silently lost chances."""
    case = CASES[stem]
    if case.card.card_type == "batter":
        targets, _ = batter_chance_targets(case.actual_stats, case.league)
    else:
        targets, _ = pitcher_chance_targets(case.actual_stats, case.league)
    placed = _generated(case).chances()
    for cat, t in targets.items():
        assert abs(placed.get(cat, 0.0) - t) <= 0.11, (
            f"{stem} {cat}: target {t:.2f}, placed {placed.get(cat, 0.0):.2f}")


# --- structural and convention checks ---------------------------------------

@pytest.mark.parametrize("stem", sorted(CASES))
def test_generated_card_is_structurally_valid(stem):
    card = _generated(CASES[stem])
    assert card.validate() == []


@pytest.mark.parametrize("stem", sorted(s for s, c in CASES.items()
                                        if c.card.card_type == "pitcher"))
def test_generated_pitcher_cards_carry_30_x_chances(stem):
    card = _generated(CASES[stem])
    assert card.chances()[XCHANCE] == pytest.approx(30.0)


@pytest.mark.parametrize("stem", sorted(s for s, c in CASES.items()
                                        if c.card.card_type == "batter"))
def test_generated_batter_card_conventions(stem):
    """Every real batter card has exactly one injury result and one
    max-effort lineout; generated cards follow suit."""
    card = _generated(CASES[stem])
    injuries = {(c, d) for c, d, s in card.iter_splits() if s.injury}
    assert len(injuries) == 1
    max_outs = [s for _, _, s in card.iter_splits()
                if "as many outs as possible" in s.text]
    assert len(max_outs) == 1


def test_generation_is_deterministic():
    case = CASES["mays_1965"]
    from stratogen.card_text import render_card
    a = render_card(_generated(case))
    b = render_card(_generated(case))
    assert a == b


# --- average cards -----------------------------------------------------------

def test_average_cards_reproduce_league_rates():
    """An average batter facing an average pitcher must produce
    league-average statistics — for any era."""
    db = default_db()
    for year, lg in [(1908, "NL"), (1930, "AL"), (1968, "AL"), (2001, "NL"),
                     (2024, "AL")]:
        league = db.league_batting(year, lg)
        rates = derived_stats(combined_rates(
            average_batter_chances(league), average_pitcher_chances(league)))
        assert rates[HR] == pytest.approx(league["HR_per_PA"], abs=1e-9)
        assert rates[WALK] == pytest.approx(league["BB_per_PA"], abs=1e-9)
        assert rates[SO] == pytest.approx(league["K_per_PA"], abs=1e-9)
        assert rates["H_per_PA"] == pytest.approx(league["H_per_PA"], abs=1e-9)


# --- the tester's own parameters, against the real cards ----------------------

def test_x_single_rate_is_consistent_with_real_pitcher_cards():
    """X_SINGLE_RATE is a tester parameter the generator inverts, so the
    generated-vs-real comparison can't see it; check it against the real
    cards directly. Solving each official pitcher card (basic side, real
    season) for the X rate that reproduces his hits allowed gave a mean of
    4.15 per 30 over 15 cards (SE 0.36), which put Bundy's 4.9 2.1 SE high
    and moved the constant to 4.1 (see simulate.X_SINGLE_RATE). Over 19
    cards: median 4.01, mean 3.66 (SE 0.45), pulled down by Chapman 2014
    (-2.0: his card prints no hits and still allows too many). Fails if
    new cards or scorer changes push the evidence 2 SE away again."""
    import statistics
    from stratogen.benchmark import transcription_cases
    from stratogen.model import DOUBLE, SINGLE, TRIPLE
    from stratogen.simulate import X_SINGLE_RATE, card_chances, pitcher_effective_pa
    cards = [(c.card, c.actual_stats, c.league) for c in TRUSTED.values()
             if c.card.card_type == "pitcher"]
    cards += [(c.reps["basic"], c.actual_stats, c.league)
              for c in transcription_cases()
              if c.card_type == "pitcher" and c.official and "basic" in c.reps]
    implied = []
    for card, stats, league in cards:
        ch = card_chances(card)
        hits = ch[HR] + ch[TRIPLE] + ch[DOUBLE] + ch[SINGLE]
        h_rate = stats["H"] / pitcher_effective_pa(stats, league)
        implied.append(30 * (216 * h_rate - 108 * league["H_per_PA"] - hits)
                       / ch[XCHANCE])
    assert len(implied) >= 15
    mean = statistics.mean(implied)
    se = statistics.stdev(implied) / len(implied) ** 0.5
    assert abs(30 * X_SINGLE_RATE - mean) < 2 * se, (mean, se)
