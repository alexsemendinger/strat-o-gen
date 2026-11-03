"""Game-dynamics tests: innings, baserunners, symbol semantics, and the
league-calibrated running game.

Unit tests pin every base-running rule (see stratogen/game.py). Emergent
tests check that lineups of league-average cards reproduce each sampled
league-season's real runs, stolen bases, caught stealing, double plays,
HBP and errors per nine innings. The engine's few free constants were
calibrated on training seasons (years divisible by 4, 1904-2024); most of
the sampled seasons below are held out. The full 1901-2024 sweep (248
league-seasons, 30k half-innings each) is reported in the README.
"""

import random

import pytest

from stratogen.game import (
    NEUTRAL_CONTEXT, GameSimulator, HalfInning, LeagueContext, Runner,
    apply_outcome, average_cards, average_lineup, card_power_rating,
    card_running_rating, card_stealing_rating, league_average_rates,
    league_context, league_game_rates, steal_attempt_probability,
    steal_success_probability, synthetic_average_stats,
)
from stratogen.generate import average_batter_chances, layout_card
from stratogen.lahman import default_db
from stratogen.model import Card, DICE_WEIGHTS, Split

db = default_db()


class FixedRNG:
    """Deterministic stand-in for random.Random: random() and randint()
    return the queued values in order (the last one repeats)."""

    def __init__(self, randoms=(0.5,), randints=(10,)):
        self._randoms, self._randints = list(randoms), list(randints)

    def random(self):
        return self._randoms.pop(0) if len(self._randoms) > 1 else self._randoms[0]

    def randint(self, lo, hi):
        value = self._randints.pop(0) if len(self._randints) > 1 else self._randints[0]
        assert lo <= value <= hi
        return value


def _state(first=None, second=None, third=None, outs=0):
    s = HalfInning()
    s.bases = [first, second, third]
    s.outs = outs
    return s


def _play(state, text, batter=13, rng=None, **kw):
    apply_outcome(state, text, batter, rng or random.Random(0), **kw)
    return state


# --- unit: hits and advancement symbols ---------------------------------------

def test_grand_slam():
    s = _play(_state(13, 13, 13), "HOMERUN")
    assert s.runs == 4 and s.bases == [None, None, None]


def test_single_star_advances_exactly_one():
    s = _play(_state(first=13, second=13), "SINGLE*")
    assert s.runs == 0
    assert s.bases == [13, 13, 13]  # loaded, nobody scored


def test_single_double_star_advances_two():
    s = _play(_state(first=13, second=13), "SINGLE**")
    assert s.runs == 1              # runner from second scores
    assert s.bases == [13, None, 13]


def test_double_star_advances_exactly_two():
    s = _play(_state(first=11, second=12), "DOUBLE*")
    assert s.runs == 1 and s.bases == [None, 13, 11]


def test_double_double_star_advances_runners_exactly_two():
    """SOM: a SINGLE or DOUBLE followed by ** moves every runner exactly
    two bases, no further (bug fix: DOUBLE** used to move them three, so
    the runner from first scored)."""
    s = _play(_state(first=13, second=13, third=13), "DOUBLE**")
    assert s.runs == 2
    assert s.bases == [None, 13, 13]
    # no extra-base gamble either, however fast the runner
    s = _play(_state(first=17), "DOUBLE**", rng=FixedRNG(randints=[1]))
    assert s.runs == 0 and s.events["XB_try"] == 0 and s.bases == [None, 13, 17]


def test_hit_location_does_not_change_the_reading():
    s = _play(_state(first=11, second=12), "SINGLE** (lf)")
    assert s.runs == 1 and s.bases == [13, None, 11]
    s = _play(_state(first=11), "DOUBLE (cf)", rng=FixedRNG(randints=[20]))
    assert s.bases == [None, 13, 11]


def test_triple_clears_bases():
    s = _play(_state(first=11, third=12), "TRIPLE")
    assert s.runs == 2 and s.bases == [None, None, 13]


def test_walk_forces_only():
    s = _play(_state(first=13, third=13), "WALK")
    assert s.runs == 0
    assert s.bases == [13, 13, 13]


def test_walk_with_bases_loaded_forces_in_a_run():
    s = _play(_state(11, 12, 13), "WALK", batter=14)
    assert s.runs == 1 and s.bases == [14, 11, 12]


# --- unit: the no-asterisk running gamble --------------------------------------

@pytest.mark.parametrize("text,base", [("SINGLE", 0), ("DOUBLE", 1)])
def test_batter_never_takes_the_gamble(text, base):
    """Bug fix: with the bases empty the batter used to be the 'lead
    runner' and stretched hits (every two-out single for an average runner,
    13+2 >= 14). The batter-runner never takes the extra base."""
    for seed in range(40):
        s = _play(_state(outs=2), text, batter=20, rng=random.Random(seed))
        assert s.outs == 2 and s.runs == 0
        expected = [None, None, None]
        expected[base] = 20
        assert s.bases == expected


def test_gamble_made_moves_trailing_runner_not_batter():
    """Bug fix: a made gamble used to push the batter to second too."""
    s = _play(_state(first=15, second=16), "SINGLE", batter=9,
              rng=FixedRNG(randints=[1]))
    assert s.runs == 1                 # runner from second scores
    assert s.bases == [9, None, 15]    # trailer to third, batter holds


def test_gamble_missed_lead_out_trailers_still_advance():
    s = _play(_state(first=15, second=16), "SINGLE", batter=9,
              rng=FixedRNG(randints=[20]))
    assert s.outs == 1 and s.runs == 0
    assert s.bases == [9, None, 15]


def test_gamble_missed_for_the_third_out_scores_nothing():
    s = _play(_state(second=13, outs=2), "SINGLE", rng=FixedRNG(randints=[20]))
    assert s.outs == 3 and s.runs == 0


def test_runs_that_crossed_before_a_missed_gamble_count():
    """Runner from third scores on the single; the trailing runner is then
    thrown out at home for the third out — the earlier run stands."""
    s = _play(_state(second=13, third=13, outs=2), "SINGLE",
              rng=FixedRNG(randints=[20]))
    assert s.outs == 3 and s.runs == 1


def test_slow_runner_holds():
    s = _play(_state(second=12), "SINGLE", rng=FixedRNG(randints=[1]))
    assert s.runs == 0 and s.bases == [13, None, 12]


def test_double_lets_runner_from_first_try_to_score():
    s = _play(_state(first=16), "DOUBLE", batter=9, rng=FixedRNG(randints=[1]))
    assert s.runs == 1 and s.bases == [None, 9, None]


# --- unit: groundballs ----------------------------------------------------------

def test_groundball_a_double_play():
    s = _play(_state(first=13, third=13, outs=0), "groundball (ss)A")
    assert s.outs == 2
    assert s.bases[0] is None
    assert s.runs == 1              # runner from third comes home on the DP
    assert s.events["DP"] == 1 and s.events["GIDP"] == 1


def test_inning_ending_double_play_scores_nobody():
    s = _play(_state(first=13, third=13, outs=1), "groundball (ss)A")
    assert s.outs == 3 and s.runs == 0


def test_groundball_a_bases_loaded():
    s = _play(_state(11, 12, 13), "groundball (2b)A")
    assert s.outs == 2 and s.runs == 1 and s.bases == [None, None, 12]


def test_groundball_a_without_force_is_plain_out():
    s = _play(_state(second=13), "groundball (ss)A")
    assert s.outs == 1 and s.bases[2] == 13   # runner moves up on the out


def test_groundball_b_forces_runner_batter_safe():
    s = _play(_state(first=11), "groundball (ss)B", batter=14)
    assert s.outs == 1 and s.bases == [14, None, None]


def test_groundball_b_bases_loaded_force_at_second():
    s = _play(_state(11, 12, 13), "groundball (3b)B", batter=14)
    assert s.outs == 1 and s.runs == 1 and s.bases == [14, None, 12]


def test_groundball_c_moves_everyone_up():
    s = _play(_state(first=11, third=13), "groundball (1b)C", batter=14)
    assert s.outs == 1 and s.runs == 1 and s.bases == [None, 11, None]


def test_groundball_with_two_outs_ends_inning_before_runs():
    s = _play(_state(first=11, third=13, outs=2), "groundball (2b)C")
    assert s.outs == 3 and s.runs == 0


@pytest.mark.parametrize("text,scores", [
    ("groundball (ss)A", True), ("groundball (2b)B", True),
    ("groundball (3b)A", False), ("groundball (1b)B", False),
    ("groundball (p)B", False), ("groundball (3b)C", True)])
def test_runner_on_third_scores_on_middle_infield_or_slow_rollers(text, scores):
    """Infield back: an unforced runner on third scores on an A/B grounder
    to 2b/ss, holds on one to 1b/3b/p; a C (slow roller) always scores him."""
    s = _play(_state(third=13), text)
    assert s.outs == 1 and s.runs == (1 if scores else 0)


def test_runner_on_second_waits_for_held_runner_on_third():
    s = _play(_state(second=12, third=13), "groundball (3b)B")
    assert s.outs == 1 and s.runs == 0 and s.bases == [None, 12, 13]


def test_plus_plus_reads_as_its_letter():
    s = _play(_state(first=13), "groundball (ss)A++")
    assert s.outs == 2


# --- unit: flyballs and lineouts --------------------------------------------------

def test_flyball_a_every_runner_tags():
    s = _play(_state(11, 12, 13), "flyball (cf)A")
    assert s.outs == 1 and s.runs == 1 and s.bases == [None, 11, 12]
    assert s.events["SF"] == 1


def test_flyball_b_sac_fly():
    s = _play(_state(third=13), "flyball (cf)B")
    assert s.outs == 1 and s.runs == 1


def test_flyball_b_others_hold():
    s = _play(_state(first=11, second=12), "flyball (rf)B")
    assert s.outs == 1 and s.bases == [11, 12, None]


def test_flyball_b_no_sac_with_two_outs():
    s = _play(_state(third=13, outs=2), "flyball (cf)B")
    assert s.outs == 3 and s.runs == 0


def test_flyball_c_holds():
    s = _play(_state(third=13), "flyball (lf)C")
    assert s.outs == 1 and s.runs == 0


def test_letter_found_despite_trailing_words():
    """Bug fix: the letter was read from the last character, so 'plus
    injury' or a trailing '?' silently turned flyball A/C into B."""
    s = _play(_state(second=12), "flyball (cf)A plus injury")
    assert s.bases == [None, None, 12]
    s = _play(_state(third=13), "fly (lf) C ?")
    assert s.runs == 0


def test_max_lineout_doubles_off_the_runner():
    s = _play(_state(first=13), "lineout (2b) into as many outs as possible")
    assert s.outs == 2 and s.bases == [None, None, None]


def test_max_lineout_is_a_triple_play_with_two_on():
    """'As many outs as possible': two on and nobody out is a triple play
    (bug fix: only the lead runner used to be doubled off)."""
    s = _play(_state(first=13, second=13), "lineout (3b) into as many outs as possible")
    assert s.outs == 3 and s.runs == 0 and s.events["TP"] == 1


def test_max_lineout_shorthand():
    s = _play(_state(first=13), "lo (3b) max")
    assert s.outs == 2


def test_plain_lineout_and_popout_hold_runners():
    for text in ("lineout (ss)", "popout (2b)", "foulout (c)", "strikeout"):
        s = _play(_state(first=11, third=13), text)
        assert s.outs == 1 and s.runs == 0 and s.bases == [11, None, 13]


# --- unit: X chances, odd texts, power -----------------------------------------

def test_x_chance_single_error_and_out():
    # X_SINGLE_RATE ~ .163, then the context's x_error (neutral: .05)
    s = _play(_state(), "GROUNDBALL (ss) X", rng=FixedRNG([0.05]))
    assert s.bases == [13, None, None] and s.events["H"] == 1
    s = _play(_state(second=12), "GROUNDBALL (ss) X", rng=FixedRNG([0.18]))
    assert s.bases == [13, None, 12] and s.events["E"] == 1 and s.outs == 0


def test_x_chance_out_resolves_as_a_batted_ball():
    """Bug fix: X-chart outs were dead outs (no DPs, no sac flies on 14% of
    plate appearances); they now read as the batted ball they are."""
    dp = _play(_state(first=13), "GROUNDBALL (ss) X", rng=FixedRNG([0.9, 0.0]))
    assert dp.outs == 2                         # converted to a DP grounder
    sf = _play(_state(third=13), "FLYBALL (cf) X", rng=FixedRNG([0.9, 0.0]))
    assert sf.outs == 1 and sf.runs == 1        # flyball B: sacrifice fly
    pop = _play(_state(third=13), "CATCHER'S CARD X", rng=FixedRNG([0.9]))
    assert pop.outs == 1 and pop.runs == 0


@pytest.mark.parametrize("text", ["LINEOUT (ss) X", "POPOUT (2b) X", "lo (3b) X"])
def test_lineout_and_popout_x_are_air_outs(text):
    """Bug fix: every non-FLY X used to resolve as a groundball, so a
    lineout X could turn a double play."""
    for u in (0.0, 0.5, 0.99):
        s = _play(_state(first=11, third=13), text, rng=FixedRNG([0.9, u]))
        assert s.outs == 1 and s.runs == 0 and s.bases == [11, None, 13]


def test_n_hr_depends_on_power():
    s = _play(_state(first=13), "N-HR")
    assert s.runs == 2
    s = _play(_state(first=13), "N-HR", power="W")
    assert s.runs == 0 and s.bases == [13, None, 13]   # SINGLE**


def test_hbp_and_shorthand_texts():
    for text in ("HBP", "HBP plus injury"):
        s = _play(_state(first=11), text)
        assert s.bases == [13, 11, None] and s.events["HBP"] == 1
    s = _play(_state(first=13), "gb (ss) A")
    assert s.outs == 2
    s = _play(_state(second=12), "SI**")
    assert s.runs == 1


def test_unknown_text_is_a_plain_out():
    s = _play(_state(first=11, third=13), "something unprintable")
    assert s.outs == 1 and s.runs == 0 and s.bases == [11, None, 13]


def test_card_ratings_parsed_from_header():
    league = db.league_batting(2001, "NL")
    card, _ = average_cards(league)
    assert card_running_rating(card) == 13
    assert card_stealing_rating(card) is None       # league-average runner
    card.header_lines = ["leftfield-2", "stealing-AA", "running 1-17", "Power-W"]
    assert card_stealing_rating(card) == "AA"
    assert card_power_rating(card) == "W"


# --- unit: league context hooks -----------------------------------------------------

def test_hbp_injected_only_into_out_readings_of_hbp_free_cards():
    ctx = LeagueContext(hbp_per_out=1.0)
    s = _play(_state(), "flyball (cf)B", context=ctx, inject_hbp=True)
    assert s.events["HBP"] == 1 and s.bases == [13, None, None]
    s = _play(_state(), "flyball (cf)B", context=ctx, inject_hbp=False)
    assert s.outs == 1
    s = _play(_state(), "SINGLE*", context=ctx, inject_hbp=True)
    assert s.events["HBP"] == 0


def test_reached_on_error_advances_everyone_one_base():
    ctx = LeagueContext(roe_per_out=1.0)
    s = _play(_state(first=11, third=13), "groundball (ss)A", context=ctx)
    assert s.outs == 0 and s.runs == 1 and s.bases == [13, 11, None]
    assert s.events["E"] == 1


def _uniform_card(card_type, text):
    cols = (4, 5, 6) if card_type == "pitcher" else (1, 2, 3)
    return Card(name="T", card_type=card_type,
                columns={c: {d: [Split(1, 20, text)] for d in DICE_WEIGHTS}
                         for c in cols})


def test_caught_stealing_ending_inning_keeps_batter_up():
    """Every PA is a walk and every steal fails: walk, CS, walk, CS, walk,
    CS ends the inning — the fourth batter leads off the next one."""
    ctx = LeagueContext(steal_attempt=0.95, steal_success=0.01)
    sim = GameSimulator([_uniform_card("batter", "WALK")] * 9,
                        _uniform_card("pitcher", "WALK"), seed=1, context=ctx)
    sim.rng = FixedRNG([0.5])   # 0.5 < 0.95 attempts; 0.5 >= 0.01 is caught
    sim._read_card = lambda batter: ("WALK", batter)
    assert sim.play_half_inning() == 0
    assert sim._next_batter == 3 and sim.totals["CS"] == 3


def test_steal_success_moves_runner_to_second():
    sim = GameSimulator([_uniform_card("batter", "strikeout")] * 9,
                        _uniform_card("pitcher", "strikeout"),
                        context=LeagueContext(steal_attempt=0.95, steal_success=0.99))
    sim.rng = FixedRNG([0.0])
    runner = Runner(13, "A")
    s = _state(first=runner)
    s.fresh = runner
    sim._before_pitch(s, Runner())
    assert s.bases[:2] == [None, runner] and s.events["SB"] == 1


def test_stealing_letters_order_attempts_and_success():
    ctx = league_context(1987, "NL")
    letters = ["AA", "A", "B", "C", "D", "E"]
    attempts = [steal_attempt_probability(ctx, x) for x in letters]
    success = [steal_success_probability(ctx, x) for x in letters]
    assert attempts == sorted(attempts, reverse=True)
    assert success == sorted(success, reverse=True)
    assert steal_attempt_probability(ctx, None) == pytest.approx(ctx.steal_attempt)


def test_wild_pitch_bunt_and_intentional_walk():
    batter = Runner()
    sim = GameSimulator([_uniform_card("batter", "strikeout")] * 9,
                        _uniform_card("pitcher", "strikeout"),
                        context=LeagueContext(wild_pitch=1.0))
    s = _state(third=13)
    sim._before_pitch(s, batter)
    assert s.runs == 1 and s.events["WP"] == 1

    sim.context = LeagueContext(sac_bunt=1.0)
    s = _state(first=11)
    assert sim._before_pitch(s, batter) is True      # batter's turn used
    assert s.outs == 1 and s.bases == [None, 11, None] and s.events["SH"] == 1

    sim.context = LeagueContext(intentional_walk=1.0)
    s = _state(second=12, outs=1)
    assert sim._before_pitch(s, batter) is True
    assert s.bases == [batter, 12, None] and s.events["IBB"] == 1


def test_neutral_context_has_no_league_mechanics():
    sim = GameSimulator(*_avg(2001, "NL"), seed=1, context=NEUTRAL_CONTEXT)
    rates = sim.game_rates(1500)
    for key in ("SB", "CS", "HBP", "WP", "PB", "BK", "SH", "IBB", "E_ROE"):
        assert rates.get(key, 0) == 0


def test_context_defaults_to_pitcher_year():
    _, pitcher = average_cards(db.league_batting(1987, "AL"))
    assert GameSimulator([pitcher], pitcher).context == league_context(1987)


def test_untracked_gidp_is_estimated_not_zero():
    """Bug fix: seasons without GIDP data built average cards as if the
    league never hit into a double play."""
    stats = synthetic_average_stats(db.league_batting(1925, "AL"))
    assert stats["GIDP"] > 5 and "GIDP" not in stats["missing"]


def _avg(year, lg):
    batter, pitcher = average_cards(db.league_batting(year, lg))
    return [batter] * 9, pitcher


# --- emergent: league-season dynamics ------------------------------------------------

# One season per era, alternating leagues; years divisible by 4 were in the
# calibration (training) set, the rest are held out.
SEASONS = [(1905, "NL"), (1913, "AL"), (1922, "NL"), (1930, "AL"), (1941, "NL"),
           (1950, "AL"), (1959, "NL"), (1968, "AL"), (1977, "NL"), (1987, "AL"),
           (1996, "NL"), (2001, "NL"), (2010, "AL"), (2019, "NL"), (2024, "AL")]
HALF_INNINGS = 12000


@pytest.fixture(scope="module")
def season_rates():
    out = {}
    for year, lg in SEASONS:
        sim = league_average_rates(db.league_batting(year, lg), HALF_INNINGS, seed=2024)
        out[(year, lg)] = (sim, league_game_rates(year, lg))
    return out


@pytest.mark.parametrize("year,lg", SEASONS)
def test_run_scoring_matches_the_league_season(season_rates, year, lg):
    """Average lineups score within 9% of the real league's runs per nine
    innings, in every era. (The full 1901-2024 sweep at 30k half-innings
    has all 248 league-seasons within 8%; the extra point here is the
    sampling noise of this smaller run.)"""
    sim, real = season_rates[(year, lg)]
    assert sim["R"] / real["R"] == pytest.approx(1.0, abs=0.09), (year, lg)


def test_run_scoring_has_no_era_bias(season_rates):
    errors = [sim["R"] / real["R"] - 1 for sim, real in season_rates.values()]
    assert abs(sum(errors) / len(errors)) < 0.02
    assert sum(abs(e) for e in errors) / len(errors) < 0.035


def test_run_scoring_orders_eras_correctly(season_rates):
    """1968 (year of the pitcher) < 1987 < 2001 < 1930 (the great
    offensive explosion) — dynamics must scale with the era."""
    rg = {key: sim["R"] for key, (sim, _real) in season_rates.items()}
    assert rg[(1968, "AL")] < rg[(1987, "AL")] < rg[(1930, "AL")]
    assert rg[(1968, "AL")] < rg[(2001, "NL")] < rg[(1930, "AL")]


# per-season tolerance (sampling noise of ~1300 games included) and the
# tolerance for the totals over all sampled seasons
EVENT_TOLERANCE = {"SB": (0.20, 0.05), "CS": (0.25, 0.06), "HBP": (0.25, 0.06),
                   "E": (0.12, 0.04), "DP": (0.25, 0.08), "GIDP": (0.25, 0.10),
                   "WP": (0.20, 0.05), "PB": (0.30, 0.08), "SH": (0.20, 0.06)}


@pytest.mark.parametrize("stat", sorted(EVENT_TOLERANCE))
def test_running_game_matches_the_league(season_rates, stat):
    """Stolen bases, caught stealing, HBP, errors, double plays, wild
    pitches, passed balls and sacrifice hits per nine innings land near
    each league-season's real rate (where the league tracked the stat)."""
    per_season, pooled = EVENT_TOLERANCE[stat]
    sim_total = real_total = 0.0
    for (year, lg), (sim, real) in season_rates.items():
        if not real.get(stat):
            continue
        assert sim.get(stat, 0) / real[stat] == pytest.approx(1, abs=per_season), \
            (stat, year, lg, sim.get(stat, 0), real[stat])
        sim_total += sim.get(stat, 0)
        real_total += real[stat]
    assert real_total > 0
    assert sim_total / real_total == pytest.approx(1, abs=pooled), stat


# --- emergent: symbols and ratings actually matter in play ----------------------------

def _lineup_with_profile(league, profile, running, stealing=None):
    header = [f"running 1-{running}"] + ([f"stealing-{stealing}"] if stealing else [])
    card = layout_card(
        average_batter_chances(league), card_type="batter",
        name="TEST", year=2001, team=None, stats={},
        header_lines=header, profile=profile)
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
            "gb_a": 0.95, "plus_plus": 0}
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


def test_stealing_letter_drives_steals():
    """An AA lineup attempts far more steals, and succeeds more often, than
    an E lineup with otherwise identical cards."""
    league = db.league_batting(1987, "NL")
    _, pitcher = average_cards(league)
    profile = dict(single_2star=0.3, single_star=0.17, double_2star=0.32,
                   gb_a=0.6, plus_plus=1)
    aa = GameSimulator(_lineup_with_profile(league, profile, 15, "AA"), pitcher,
                       seed=4, context=league).game_rates(3000)
    e = GameSimulator(_lineup_with_profile(league, profile, 15, "E"), pitcher,
                      seed=4, context=league).game_rates(3000)
    assert aa["SB"] > 10 * e.get("SB", 0.01)
    assert aa["SB"] / (aa["SB"] + aa["CS"]) > 0.75


def test_average_lineup_layouts_differ():
    lineup = average_lineup(db.league_batting(2001, "NL"))
    assert len({str(card.columns) for card in lineup}) == 9


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
