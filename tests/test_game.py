"""Game-dynamics tests: innings, baserunners, and symbol semantics.

The per-PA tester can't see whether `*`/`**`, double plays, or running
gambles behave sensibly — these tests can. The engine omits steals,
non-X-chart errors, HBP, and small-ball (documented in game.py), which
costs a consistent ~12-14% of real-league scoring; the assertions
therefore check a band plus *ordering* across run environments, which is
robust to that known uniform deficit.
"""

import random

import pytest

from stratogen.game import (
    GameSimulator, HalfInning, apply_outcome, average_cards,
    card_running_rating, synthetic_average_stats,
)
from stratogen.generate import average_batter_chances, layout_card, hit_profile
from stratogen.lahman import default_db

db = default_db()


# --- unit: outcome resolution ------------------------------------------------

def _state(first=None, second=None, third=None, outs=0):
    s = HalfInning()
    s.bases = [first, second, third]
    s.outs = outs
    return s


def test_grand_slam():
    s = _state(13, 13, 13)
    apply_outcome(s, "HOMERUN", 13, random.Random(0))
    assert s.runs == 4 and s.bases == [None, None, None]


def test_single_star_advances_exactly_one():
    s = _state(first=13, second=13)
    apply_outcome(s, "SINGLE*", 13, random.Random(0))
    assert s.runs == 0
    assert s.bases == [13, 13, 13]  # loaded, nobody scored


def test_single_double_star_advances_two():
    s = _state(first=13, second=13)
    apply_outcome(s, "SINGLE**", 13, random.Random(0))
    assert s.runs == 1              # runner from second scores
    assert s.bases == [13, None, 13]


def test_double_double_star_clears_bases():
    s = _state(first=13, second=13, third=13)
    apply_outcome(s, "DOUBLE**", 13, random.Random(0))
    assert s.runs == 3
    assert s.bases == [None, 13, None]


def test_walk_forces_only():
    s = _state(first=13, third=13)
    apply_outcome(s, "WALK", 13, random.Random(0))
    assert s.runs == 0
    assert s.bases == [13, 13, 13]


def test_groundball_a_double_play():
    s = _state(first=13, third=13, outs=0)
    apply_outcome(s, "groundball (ss)A", 13, random.Random(0))
    assert s.outs == 2
    assert s.bases[0] is None
    assert s.runs == 1              # runner from third comes home on the DP


def test_groundball_a_without_force_is_plain_out():
    s = _state(second=13)
    apply_outcome(s, "groundball (ss)A", 13, random.Random(0))
    assert s.outs == 1 and s.bases[1] == 13


def test_groundball_c_holds_runners():
    s = _state(third=13)
    apply_outcome(s, "groundball (2b)C", 13, random.Random(0))
    assert s.outs == 1 and s.runs == 0 and s.bases[2] == 13


def test_flyball_b_sac_fly():
    s = _state(third=13)
    apply_outcome(s, "flyball (cf)B", 13, random.Random(0))
    assert s.outs == 1 and s.runs == 1


def test_flyball_b_no_sac_with_two_outs():
    s = _state(third=13, outs=2)
    apply_outcome(s, "flyball (cf)B", 13, random.Random(0))
    assert s.outs == 3 and s.runs == 0


def test_max_lineout_doubles_off_lead_runner():
    s = _state(first=13, second=13)
    apply_outcome(s, "lineout (2b) into as many outs as possible", 13,
                  random.Random(0))
    assert s.outs == 2
    assert s.bases[1] is None and s.bases[0] == 13


def test_running_rating_parsed_from_header():
    league = db.league_batting(2001, "NL")
    card, _ = average_cards(league)
    assert card_running_rating(card) == 13


# --- emergent: league run scoring --------------------------------------------

ERAS = [(1968, "AL"), (1987, "AL"), (2001, "NL"), (1930, "AL")]


@pytest.fixture(scope="module")
def simulated_rg():
    out = {}
    for year, lg in ERAS:
        league = db.league_batting(year, lg)
        batter, pitcher = average_cards(league)
        sim = GameSimulator([batter] * 9, pitcher, seed=11)
        out[(year, lg)] = sim.runs_per_game(8000)
    return out


@pytest.mark.parametrize("year,lg", ERAS)
def test_run_scoring_in_band(simulated_rg, year, lg):
    """Simulated league R/G lands within the documented band of reality
    (low side reflects the engine's deliberate omissions)."""
    actual = db.league_runs_per_game(year, lg)
    ratio = simulated_rg[(year, lg)] / actual
    assert 0.75 <= ratio <= 1.05, (year, lg, ratio)


def test_run_scoring_orders_eras_correctly(simulated_rg):
    """1968 (year of the pitcher) < 1987 < 2001 < 1930 (the great
    offensive explosion) — dynamics must scale with the era."""
    assert (simulated_rg[(1968, "AL")] < simulated_rg[(1987, "AL")]
            < simulated_rg[(1930, "AL")])
    assert simulated_rg[(1968, "AL")] < simulated_rg[(2001, "NL")] \
        < simulated_rg[(1930, "AL")]


# --- emergent: symbols actually matter in play --------------------------------

def _lineup_with_profile(league, profile, running):
    card = layout_card(
        average_batter_chances(league), card_type="batter",
        name="TEST", year=2001, team=None, stats={},
        header_lines=[f"running 1-{running}"], profile=profile)
    return [card] * 9


def test_advancement_symbols_change_run_scoring():
    """Same outcome frequencies, different symbols: a lineup whose hits
    carry ** and few DP groundouts must outscore a lineup of soft * hits
    and DP-prone outs. This is invisible to the per-PA tester."""
    league = db.league_batting(2001, "NL")
    _, pitcher = average_cards(league)
    hard = {"single_2star": 0.60, "single_star": 0.05, "double_2star": 0.60,
            "gb_a": 0.20, "plus_plus": 2}
    soft = {"single_2star": 0.05, "single_star": 0.50, "double_2star": 0.15,
            "gb_a": 0.75, "plus_plus": 0}
    rg_hard = GameSimulator(_lineup_with_profile(league, hard, 13),
                            pitcher, seed=5).runs_per_game(6000)
    rg_soft = GameSimulator(_lineup_with_profile(league, soft, 13),
                            pitcher, seed=5).runs_per_game(6000)
    assert rg_hard > rg_soft * 1.05, (rg_hard, rg_soft)


def test_fast_lineup_gains_from_running_gambles():
    """Identical cards, different running ratings: the fast lineup takes
    (and mostly makes) the no-asterisk extra-base gamble."""
    league = db.league_batting(1968, "AL")
    _, pitcher = average_cards(league)
    profile = dict(single_2star=0.20, single_star=0.20, double_2star=0.25,
                   gb_a=0.45, plus_plus=1)
    fast = GameSimulator(_lineup_with_profile(league, profile, 17),
                         pitcher, seed=9).runs_per_game(8000)
    slow = GameSimulator(_lineup_with_profile(league, profile, 9),
                         pitcher, seed=9).runs_per_game(8000)
    assert fast > slow, (fast, slow)


# --- generated player cards behave sanely in play ------------------------------

def test_generated_slugger_outscores_generated_slap_hitter():
    from stratogen.generate import generate_batter_card
    league = db.league_batting(1998, "NL")
    _, pitcher = average_cards(league)
    mcgwire, _ = generate_batter_card(db.batting_season("mcgwima01", 1998), league)
    light = db.batting_season("vizquom01", 1998)  # Omar Vizquel, light bat
    vizquel, _ = generate_batter_card(light, league)
    rg_mac = GameSimulator([mcgwire] * 9, pitcher, seed=3).runs_per_game(6000)
    rg_viz = GameSimulator([vizquel] * 9, pitcher, seed=3).runs_per_game(6000)
    assert rg_mac > rg_viz * 1.5, (rg_mac, rg_viz)
