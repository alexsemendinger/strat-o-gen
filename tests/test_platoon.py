"""Advanced (L/R platoon) cards: the platoon model, exact accounting,
real-card benchmarks, structure, export, and no regressions to basic cards.

Exactness is checked the way the basic cards are: closed-form per-PA rates
of each grid against the average opposing grid of its own matchup,
weighted by the grid's share of PA (stratogen.benchmark.advanced_*_rates).
"""

import dataclasses
import hashlib
import io
import json
from contextlib import redirect_stdout

import pytest

from stratogen import platoon as pl
from stratogen.benchmark import (
    advanced_batter_rates, advanced_pitcher_rates, advanced_sides,
    score_advanced_batter, score_advanced_pitcher, score_batter_card,
    score_pitcher_card, transcription_cases, transcription_sides,
)
from stratogen.card_json import advanced_card_to_json, load_transcriptions, platoon_cards
from stratogen.card_text import render_advanced_card
from stratogen.generate import (
    MAX_WEAK_SHARE, average_advanced_batter_chances,
    average_advanced_pitcher_chances, batter_chance_targets,
    generate_advanced_batter_card, generate_advanced_pitcher_card,
    generate_batter_card, generate_pitcher_card, merge_side_warnings,
    pitcher_chance_targets,
)
from stratogen.lahman import default_db
from stratogen.model import (
    DICE_WEIGHTS, HBP, HR, SINGLE, SO, TRIPLE, DOUBLE, WALK, XCHANCE,
    categorize,
)
from stratogen.simulate import (
    actual_batting_rates, combined_rates, derived_stats, effective_pa,
)

db = default_db()


def _batter(pid, year):
    stats = db.batting_season(pid, year)
    league = db.league_batting(year, stats["league"])
    return stats, league, pl.league_context(league, db)


def _pitcher(pid, year):
    stats = db.pitching_season(pid, year)
    league = db.league_batting(year, stats["league"])
    return stats, league, pl.league_context(league, db)


# --- the platoon model ---------------------------------------------------------

LEAGUES = [(1894, "NL"), (1913, "AL"), (1943, "NN2"), (1963, "AL"),
           (1986, "AL"), (2003, "AL"), (2024, "AL")]


@pytest.mark.parametrize("year,lg", LEAGUES)
def test_matchup_rates_reproduce_league_line(year, lg):
    """Frequency-weighted matchup rates are exactly the league line."""
    league = db.league_batting(year, lg)
    ctx = pl.league_context(league, db)
    assert sum(ctx.freq(p, h) for p in "LR" for h in "LR") == pytest.approx(1.0)
    for cat in pl.PLATOON_CATEGORIES:
        mix = sum(ctx.freq(p, h) * ctx.rates[(p, h)][cat]
                  for p in "LR" for h in "LR")
        assert mix == pytest.approx(ctx.league_rates[cat], rel=1e-12), cat


def test_matchup_rates_follow_the_same_hand_ratios():
    ctx = pl.league_context(db.league_batting(2003, "AL"), db)
    for h in "LR":
        same, opp = ctx.rates[(h, h)], ctx.rates[(pl.opposite(h), h)]
        for cat, ratio in pl.SAME_HAND_RATIO[h].items():
            assert same[cat] / opp[cat] == pytest.approx(ratio), (h, cat)
    # platoon disadvantage: more strikeouts, fewer walks and homers
    assert ctx.rates[("L", "L")][SO] > ctx.rates[("R", "L")][SO]
    assert ctx.rates[("L", "L")][HR] < ctx.rates[("R", "L")][HR]


def test_player_split_reproduces_his_line():
    stats, league, ctx = _batter("ortizda01", 2006)        # lefty slugger
    rates = actual_batting_rates(stats)
    shares = {"L": 0.3, "R": 0.7}
    split = pl.split_rates({c: rates[c] for c in pl.PLATOON_CATEGORIES},
                           ctx.batter_factors("L"), shares)
    for cat in pl.PLATOON_CATEGORIES:
        mix = sum(shares[p] * split[p][cat] for p in "LR")
        assert mix == pytest.approx(rates[cat], rel=1e-12)
    assert split["L"][HR] / split["R"][HR] == pytest.approx(0.76)
    assert split["L"][SO] / split["R"][SO] == pytest.approx(1.22)


def test_switch_hitters_have_no_individual_split():
    stats, league, ctx = _batter("bowala01", 1971)         # switch hitter
    card, _ = generate_advanced_batter_card(stats, league)
    assert card.hand == "S"
    assert pl.effective_hand("S", "L") == "R" and pl.effective_hand("B", "R") == "L"
    factors = ctx.batter_factors("S")
    assert all(f == 1.0 for side in factors.values() for f in side.values())


def test_unknown_and_odd_hands():
    assert pl.batting_hand("") == "?" and pl.batting_hand("B") == "S"
    assert pl.throwing_hand("S") == "?"
    assert pl.effective_hand(None, "L") == "R"
    stats, league, ctx = _batter("mayswi01", 1965)
    card, warnings = generate_advanced_batter_card(stats, league, bats="?")
    assert card.hand == "R"
    assert any("batting hand unknown" in w for w in warnings)


def test_context_without_handedness_falls_back_with_warning():
    league = db.league_batting(2001, "NL")
    ctx = pl.build_context(league, None)
    assert ctx.lhp_share == pytest.approx(0.27)
    assert any("handedness unknown" in w for w in ctx.warnings)
    assert all(w == 0.0 for w in ctx.weak_share.values())


def test_league_without_left_handed_pitching():
    """1876 NL had no LHP: the vs-LHP grid has a 0% share but is still a
    valid card, and the line is still reproduced."""
    stats, league, ctx = _batter("barnero01", 1876)
    assert ctx.lhp_share == 0.0
    card, _ = generate_advanced_batter_card(stats, league)
    assert card.validate() == []
    assert card.side("LHP").share == 0.0
    err = score_advanced_batter(advanced_sides(card), card.hand, stats, ctx)
    assert err["BA"] < 0.002 and err[HR] < 0.001


# --- usage shares and Power ratings vs the real cards ---------------------------

REAL = transcription_cases()


def test_share_model_against_printed_percentages():
    """Printed share vs LHP (batters) / LHB (pitchers) on the official
    cards. Achieved: batters MAE 3.3 points (12 cards; 5.7 with the plain
    league share), pitchers 3.6 points (7 official cards). Bounded here
    at the achieved level; the unofficial cards (made without split data)
    miss by ~7.8 and aren't bounded."""
    bat, pit = [], []
    for c in REAL:
        s = c.actual_stats
        info = db.player_info(s["player_id"])
        ctx = pl.league_context(c.league, db)
        grids = {g["vs"]: g["percent"] / 100 for g in c.transcription.advanced.grids}
        if c.card_type == "batter":
            pred = pl.printed_share(pl.batter_lhp_share(
                info["bats"], effective_pa(s), ctx))
            bat.append(abs(pred - grids["LHP"]))
        elif c.official:
            pred = pl.printed_share(pl.pitcher_lhb_share(info["throws"], ctx))
            pit.append(abs(pred - grids["LHB"]))
    assert len(bat) == 12 and len(pit) == 7
    assert sum(bat) / len(bat) <= 0.034
    assert sum(pit) / len(pit) <= 0.036
    assert max(bat + pit) <= 0.10 + 1e-9   # Gibson 1994: 24% vs printed 34%


def test_part_time_righties_are_platooned():
    ctx = pl.league_context(db.league_batting(1963, "AL"), db)
    full = pl.batter_lhp_share("R", ctx.full_time_pa, ctx)
    part = pl.batter_lhp_share("R", 200, ctx)
    assert full == pytest.approx(ctx.lhp_share)
    assert ctx.lhp_share < part < 0.5
    assert pl.batter_lhp_share("L", 200, ctx) == pytest.approx(ctx.lhp_share)


def test_power_labels_against_real_cards():
    """24 side labels on the 12 official batter cards with a season.
    Achieved 20/24 (absolute and league-relative thresholds both top out
    at 20; see platoon.POWER_HR_THRESHOLD). All misses are printed N
    where the split model says W."""
    agree = total = 0
    for c in REAL:
        if c.card_type != "batter":
            continue
        s = c.actual_stats
        pa = effective_pa(s)
        bats = db.player_info(s["player_id"])["bats"]
        sides = pl.batter_sides(bats, pa, s["HR"] / pa,
                                pl.league_context(c.league, db))
        for g in c.transcription.advanced.grids:
            total += 1
            agree += sides[g["vs"][0]][2] == g["power"]
    assert total == 24
    assert agree >= 20


def test_power_rule():
    assert pl.power_rating(0.0, 0.03) == "W"
    assert pl.power_rating(0.014, 0.03) == "W"      # N would clamp: forced W
    assert pl.power_rating(0.0136, 0.02) == "N"
    assert pl.power_rating(0.0130, 0.02) == "W"     # under the 1.35% bar
    # dead-ball cap: the bar is at most 1.35x the league rate
    assert pl.power_rating(0.006, 0.004) == "N"


def test_weak_share_by_era():
    """Share of matchup PA taken by Power-W hitters: a minority in modern
    leagues, a majority in low-HR eras (capped by the league-relative bar)."""
    modern = pl.league_context(db.league_batting(2024, "AL"), db).weak_share
    assert all(0.05 < w < 0.3 for w in modern.values()), modern
    deadball = pl.league_context(db.league_batting(1913, "AL"), db).weak_share
    assert all(0.4 < w < 0.85 for w in deadball.values()), deadball


# --- exactness: advanced vs basic on the archetypes --------------------------------

BATTERS = [
    ("power/TTO", "mcgwima01", 1998), ("contact, never Ks", "gwynnto01", 1995),
    ("speed/leadoff", "henderi01", 1982), ("dead-ball era", "cobbty01", 1911),
    ("19th century", "duffyhu01", 1894), ("negro leagues", "gibsojo99", 1943),
    ("modern shohei", "ohtansh01", 2024),
    ("0-HR shortstop", "belanma01", 1971), ("0-HR switch hitter", "bowala01", 1971),
    ("0-HR part-timer", "silvech01", 1949),
]
PITCHERS = [
    ("dominant modern P", "martipe02", 2000), ("control artist", "maddugr01", 1995),
    ("wild flamethrower", "ryanno01", 1974), ("dead-ball pitcher", "johnswa01", 1913),
    ("modern reliever", "chapmar01", 2014), ("HR-prone 1950s", "roberro01", 1956),
]
_BAT_KEYS = ("BA", "H_per_PA", HR, TRIPLE, DOUBLE, SINGLE, WALK, SO, HBP)
_PIT_KEYS = ("H_per_PA", HR, WALK, SO)


@pytest.mark.parametrize("label,pid,year", BATTERS, ids=[b[0] for b in BATTERS])
def test_advanced_batter_card_at_least_as_exact_as_basic(label, pid, year):
    """Every category (HBP included) at least as tight as the basic card,
    up to 0.001 per PA where a below-average category clamps on a grid
    (the platoon split moves a little clamped mass: Gwynn's strikeouts
    run 0.0007 higher). Home runs are always exact: a grid whose N formula
    would clamp is Power-W, which never clamps."""
    stats, league, ctx = _batter(pid, year)
    basic, _ = generate_batter_card(stats, league)
    adv, warnings = generate_advanced_batter_card(stats, league)
    eb = score_batter_card(basic, stats, league)
    eb[HBP] = actual_batting_rates(stats)[HBP]       # basic cards carry none
    ea = score_advanced_batter(advanced_sides(adv), adv.hand, stats, ctx)
    for key in _BAT_KEYS:
        assert ea[key] <= eb[key] + 0.001, (label, key, ea[key], eb[key])
    assert ea[HR] < 0.0002, (label, ea[HR])
    assert ea[HBP] <= 0.5 / 216 + 1e-12          # whole chances: rounding only
    assert adv.validate() == []


@pytest.mark.parametrize("pid,year", [("belanma01", 1971), ("bowala01", 1971),
                                      ("silvech01", 1949)])
def test_zero_hr_hitters_are_now_exact(pid, year):
    """The documented basic-card limitation (a 0-HR season still yields
    half the league HR rate) is gone on the advanced side."""
    stats, league, ctx = _batter(pid, year)
    assert stats["HR"] == 0
    basic, _ = generate_batter_card(stats, league)
    adv, _ = generate_advanced_batter_card(stats, league)
    assert score_batter_card(basic, stats, league)[HR] > 0.005
    assert all(s.power == "W" for s in adv.sides)
    assert all(s.card.chances()[HR] == 0 for s in adv.sides)
    implied = advanced_batter_rates(advanced_sides(adv), adv.hand, ctx)
    assert implied[HR] == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("label,pid,year", PITCHERS, ids=[p[0] for p in PITCHERS])
def test_advanced_pitcher_card_vs_basic(label, pid, year):
    """Hits, walks and strikeouts at least as tight as the basic card (up
    to 0.001 per PA from per-grid clamping). Home runs are exact unless
    the card warns — and the warning is unavoidable for HR-stingy
    pitchers: Power-W hitters carry all their own homers, so the average
    batter grid holds lg_HR * (1 + w) * 108 HR chances and a pitcher can't
    allow fewer than lg_HR * (1 + w) / 2 per PA (basic floor: lg_HR / 2).
    Achieved HR errors: Pedro 2000 and Johnson 1913 0.0000, Ryan 1974
    0.0003, Maddux 1995 0.0059 (basic 0.0023), Chapman 2014 0.0100
    (basic 0.0063)."""
    stats, league, ctx = _pitcher(pid, year)
    basic, _ = generate_pitcher_card(stats, league)
    adv, warnings = generate_advanced_pitcher_card(stats, league)
    eb = score_pitcher_card(basic, stats, league)
    ea = score_advanced_pitcher(advanced_sides(adv), adv.hand, stats, ctx)
    for key in ("H_per_PA", WALK, SO):
        assert ea[key] <= eb[key] + 0.001, (label, key, ea[key], eb[key])
    hr_warned = any("home runs allowed" in w for w in warnings)
    if not hr_warned:
        assert ea[HR] < 0.0005, (label, ea[HR])
    else:
        w = max(ctx.weak_share[(adv.hand, h)] for h in "LR")
        lg_hr = max(ctx.rates[(adv.hand, h)][HR] for h in "LR")
        assert ea[HR] <= eb[HR] + w * lg_hr / 2 + 0.0005, (label, ea[HR], eb[HR])
    assert adv.validate() == []


def test_n_hr_amplification_is_exact_and_needed():
    """Robin Roberts 1956 (46 HR allowed): his N-HR only reach the Power-N
    hitters (w ~ 0.4 of PA), so they're amplified by 1/(1-w); the card is
    exact on HR. Built as if every hitter were N (no amplification), the
    same card would give up visibly too few homers in play."""
    stats, league, ctx = _pitcher("roberro01", 1956)
    adv, warnings = generate_advanced_pitcher_card(stats, league)
    assert not any("home runs allowed" in w for w in warnings)
    err = score_advanced_pitcher(advanced_sides(adv), adv.hand, stats, ctx)
    assert err[HR] < 1e-4 and err["H_per_PA"] < 1e-3

    naive_ctx = dataclasses.replace(
        ctx, weak_share={k: 0.0 for k in ctx.weak_share})
    naive, _ = generate_advanced_pitcher_card(stats, league, context=naive_ctx)
    naive_err = score_advanced_pitcher(advanced_sides(naive), naive.hand,
                                       stats, ctx)
    assert naive_err[HR] > 0.003
    # amplified N-HR come out of singles, so total hits are unchanged
    for a, n in zip(adv.sides, naive.sides):
        hits = lambda c: sum(c[k] for k in (HR, TRIPLE, DOUBLE, SINGLE))
        assert hits(a.card.chances()) == pytest.approx(
            hits(n.card.chances()), abs=0.15)
        assert a.card.chances()[HR] > n.card.chances()[HR]


@pytest.mark.parametrize("year,lg", LEAGUES)
def test_average_grids_close_the_league(year, lg):
    """The average N/W batter mix against the average pitcher grid
    reproduces each matchup's league rates exactly — the reference both
    sides are built against is one consistent league."""
    ctx = pl.league_context(db.league_batting(year, lg), db)
    for (p, h), w in ctx.weak_share.items():
        cell = ctx.cell_league(p, h)
        bat = average_advanced_batter_chances(cell, w)
        pit = average_advanced_pitcher_chances(cell)
        n = combined_rates(bat, pit, batter_power="N")
        wk = combined_rates(bat, pit, batter_power="W")
        rates = {k: (1 - w) * n[k] + w * wk[k] for k in n}
        for cat in (HR, TRIPLE, DOUBLE, SINGLE, WALK, SO, HBP):
            assert rates[cat] == pytest.approx(ctx.rates[(p, h)][cat],
                                               abs=1e-12), (p, h, cat)


def test_dead_ball_amplification_is_capped():
    stats, league, ctx = _pitcher("johnswa01", 1913)
    assert max(ctx.weak_share.values()) <= 1.0
    assert MAX_WEAK_SHARE < 1.0
    adv, _ = generate_advanced_pitcher_card(stats, league)
    for s in adv.sides:
        assert s.card.chances()[HR] < 6     # sane N-HR counts


# --- against the real advanced cards ------------------------------------------------

ADV_CASES = [c for c in REAL if c.transcription.advanced is not None]


@pytest.mark.parametrize("card_id", [c.card_id for c in ADV_CASES])
def test_generated_advanced_card_matches_real_advanced_card(card_id):
    """Like tests/test_benchmark.py: per category, the generated advanced
    card's share-weighted error may exceed the real advanced card's by at
    most 0.002 per PA (real grids scored with their printed percentages
    and Power labels)."""
    case = next(c for c in ADV_CASES if c.card_id == card_id)
    s = case.actual_stats
    info = db.player_info(s["player_id"])
    ctx = pl.league_context(case.league, db)
    real = transcription_sides(case.transcription)
    if case.card_type == "batter":
        card, _ = generate_advanced_batter_card(s, case.league)
        real_err = score_advanced_batter(real, info["bats"], s, ctx)
        gen_err = score_advanced_batter(advanced_sides(card), card.hand, s, ctx)
        keys = _BAT_KEYS
    else:
        card, _ = generate_advanced_pitcher_card(s, case.league)
        real_err = score_advanced_pitcher(real, info["throws"], s, ctx)
        gen_err = score_advanced_pitcher(advanced_sides(card), card.hand, s, ctx)
        keys = _PIT_KEYS
    for key in keys:
        assert gen_err[key] <= real_err[key] + 0.002, (
            f"{card_id} {key}: generated {gen_err[key]:.4f} vs real "
            f"{real_err[key]:.4f}")


def test_real_advanced_cards_score_well_side_by_side():
    """Sanity for the side-by-side scorer: official real advanced cards
    land in the same ballpark as the basic-side bars."""
    for c in ADV_CASES:
        if not c.official or c.card_id == "pitcher_bruney-brian_2008":
            continue   # Bruney: 36-IP reliever, documented tolerance
        s = c.actual_stats
        info = db.player_info(s["player_id"])
        ctx = pl.league_context(c.league, db)
        sides = transcription_sides(c.transcription)
        if c.card_type == "batter":
            err = score_advanced_batter(sides, info["bats"], s, ctx)
            limit = 0.035 if c.card_id == "batter_judge-aaron_2024" else 0.015
            assert max(err[k] for k in ("BA", HR, WALK, SO)) < limit, c.card_id
        else:
            err = score_advanced_pitcher(sides, info["throws"], s, ctx)
            assert max(err[k] for k in _PIT_KEYS) < 0.01, c.card_id


# --- structure, layout, determinism, export ----------------------------------------

@pytest.fixture(scope="module")
def judge():
    stats, league, _ = _batter("judgeaa01", 2024)
    return generate_advanced_batter_card(stats, league)[0]


@pytest.fixture(scope="module")
def capuano():
    stats, league, _ = _pitcher("capuach01", 2014)
    return generate_advanced_pitcher_card(stats, league)[0]


def test_every_generated_grid_is_valid():
    for c in ADV_CASES:
        fn = (generate_advanced_pitcher_card if c.card_type == "pitcher"
              else generate_advanced_batter_card)
        card, _ = fn(c.actual_stats, c.league)
        assert card.validate() == [], c.card_id
        assert [s.percent for s in card.sides][0] + card.sides[1].percent == 100


def test_hbp_on_batter_grids_only(judge, capuano):
    """Judge 2024: 2 * 9 / 683 * 108 = 2.85 -> 3 whole HBP chances on both
    grids (the real card carries 3 on each), on edge rows as real cards
    place them. Pitcher grids carry none."""
    for side in judge.sides:
        cells = [(c, d) for c, d, s in side.card.iter_splits()
                 if s.category == HBP]
        assert sum(DICE_WEIGHTS[d] for _c, d in cells) == 3
        assert all(d in (2, 3, 4, 10, 11, 12) for _c, d in cells)
        assert all(s.lo == 1 and s.hi == 20 for _c, _d, s in side.card.iter_splits()
                   if s.category == HBP)
    for side in capuano.sides:
        assert side.card.chances()[HBP] == 0


def test_pitcher_grids_print_n_hr_and_x_block(capuano):
    for side in capuano.sides:
        hr_texts = {s.text for _c, _d, s in side.card.iter_splits()
                    if s.category == HR}
        assert hr_texts <= {"N-HR"} and hr_texts
        assert side.card.chances()[XCHANCE] == pytest.approx(30.0)
        assert side.power is None
    assert categorize("N-HR") == HR


def test_batter_grids_keep_the_card_conventions(judge):
    for side in judge.sides:
        assert len({(c, d) for c, d, s in side.card.iter_splits() if s.injury}) == 1
        assert sum("as many outs" in s.text
                   for _c, _d, s in side.card.iter_splits()) == 1


def test_generation_is_deterministic():
    stats, league, _ = _batter("mayswi01", 1965)
    a = render_advanced_card(generate_advanced_batter_card(stats, league)[0])
    b = render_advanced_card(generate_advanced_batter_card(stats, league)[0])
    assert a == b
    assert "vs LHP" in a and "vs RHP" in a and "Power-" in a
    # the two grids are laid out independently (different seeds)
    card = generate_advanced_batter_card(stats, league)[0]
    assert card.sides[0].card.columns != card.sides[1].card.columns


def test_json_round_trip(tmp_path, judge, capuano):
    """Export to the transcription schema and load back via card_json."""
    for card in (judge, capuano):
        data = advanced_card_to_json(card)
        assert data["side"] == "6col" and data["cardType"] == card.card_type
        path = tmp_path / f"som_{data['cardId']}_6col.json"
        path.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_transcriptions(tmp_path)
    assert len(loaded) == 2
    for card in (judge, capuano):
        t = next(v for v in loaded.values() if v.card_type == card.card_type)
        assert not t.official and t.year == card.year
        parts = platoon_cards(t)
        for side, (weight, grid), g in zip(card.sides, parts, t.advanced.grids):
            assert g["vs"] == side.vs and g["percent"] == side.percent
            assert g.get("power") == side.power
            assert weight == pytest.approx(side.share)
            assert grid.validate() == []
            assert list(grid.iter_splits()) == list(side.card.iter_splits())


def test_merge_side_warnings():
    merged = merge_side_warnings({
        "LHP": ["walks will run ~1.2% of PA high", "only here"],
        "RHP": ["walks will run ~0.8% of PA high"]})
    assert merged == ["vs LHP/RHP: walks will run ~1.2/0.8% of PA high",
                      "vs LHP: only here"]
    assert merge_side_warnings({"LHB": ["x 5"], "RHB": ["x 5"]}) == ["vs LHB/RHB: x 5"]


def test_combined_rates_power():
    pitcher = {HR: 10.0, SINGLE: 10.0}
    batter = {HR: 2.0}
    n = combined_rates(batter, pitcher)
    w = combined_rates(batter, pitcher, batter_power="W")
    assert n[HR] == pytest.approx(12 / 216) and w[HR] == pytest.approx(2 / 216)
    assert w[SINGLE] - n[SINGLE] == pytest.approx(10 / 216)
    with pytest.raises(ValueError):
        combined_rates(batter, pitcher, batter_power="X")


def test_cli_advanced(capsys, monkeypatch):
    import generate_card
    monkeypatch.setattr("sys.argv", ["generate_card.py", "Chris Capuano", "2014",
                                     "--pitcher", "--advanced"])
    assert generate_card.main() == 0
    out = capsys.readouterr().out
    assert "vs LHB" in out and "vs RHB" in out and "N-HR" in out


# --- no regressions to the basic side ----------------------------------------------

# Fingerprints of basic-card output (targets, grid, warnings). First recorded
# from the code before advanced generation existed, then re-recorded when:
# - the out-type mix and DP-grounder share were recalibrated to the real cards
#   (chances, hit cells and warnings were verified identical; only out texts
#   moved);
# - pitcher cards took the X block's singles out of the singles share alone
#   (batter cards verified identical; on the pitchers only the 1B/2B/3B split
#   moved, total hits unchanged, plus Chapman's now-quantified hits warning);
# - pitcher rates left sacrifice hits out of batters faced
#   (simulate.pitcher_effective_pa; batter cards verified identical, the
#   pitchers' BB/SO/HR/hit targets rose by their SH share, ~1%).
# '++' is stripped and the header excluded, so they only depend on the
# chance model and layout.
_BASIC_GOLDEN = [
    ("mayswi01", 1965, "batter", "9f2a5e9d8cfbc2db"),
    ("gwynnto01", 1995, "batter", "97bd25606327eb01"),
    ("cobbty01", 1911, "batter", "cbc297e924d0548d"),
    ("judgeaa01", 2024, "batter", "81710993e5f25871"),
    ("ryanno01", 1974, "pitcher", "2e668f31a7d24c4b"),
    ("maddugr01", 1995, "pitcher", "81d6932415f72730"),
    ("chapmar01", 2014, "pitcher", "1e967d72383454cf"),
]


@pytest.mark.parametrize("pid,year,kind,digest", _BASIC_GOLDEN)
def test_basic_cards_unchanged(pid, year, kind, digest):
    if kind == "batter":
        stats, league, _ = _batter(pid, year)
        card, warnings = generate_batter_card(stats, league)
        targets, _ = batter_chance_targets(stats, league)
    else:
        stats, league, _ = _pitcher(pid, year)
        card, warnings = generate_pitcher_card(stats, league)
        targets, _ = pitcher_chance_targets(stats, league)
    grid = [(col, d, s.lo, s.hi, s.text.replace("++", ""), s.injury)
            for col, d, s in card.iter_splits()]
    payload = repr((sorted(targets.items()), grid, list(warnings)))
    assert hashlib.sha256(payload.encode()).hexdigest()[:16] == digest
