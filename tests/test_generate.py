"""Generator tests across player archetypes, eras, and edge cases."""

import pytest

from stratogen.generate import generate_batter_card, generate_pitcher_card
from stratogen.benchmark import score_batter_card, score_pitcher_card
from stratogen.lahman import default_db
from stratogen.model import DICE_WEIGHTS, HR, SO, WALK
from stratogen.simulate import simulate_season, combined_rates, card_chances
from stratogen.generate import average_pitcher_chances

db = default_db()

# (label, player_id, year, kind) — chosen to cover extreme archetypes
ARCHETYPES = [
    ("power/TTO", "mcgwima01", 1998, "batter"),       # 70 HR, high BB+K
    ("contact, never Ks", "gwynnto01", 1995, "batter"),  # 15 SO in 577 PA
    ("speed/leadoff", "henderi01", 1982, "batter"),   # 130 SB
    ("dead-ball era", "cobbty01", 1911, "batter"),    # .420, 24 3B
    ("19th century", "duffyhu01", 1894, "batter"),    # .440
    ("negro leagues", "gibsojo99", 1943, "batter"),   # Josh Gibson
    ("modern shohei", "ohtansh01", 2024, "batter"),
    ("dominant modern P", "martipe02", 2000, "pitcher"),  # Pedro, 1.74 ERA
    ("control artist", "maddugr01", 1995, "pitcher"),     # Maddux
    ("wild flamethrower", "ryanno01", 1974, "pitcher"),
    ("dead-ball pitcher", "johnswa01", 1913, "pitcher"),  # Walter Johnson
    ("modern reliever", "chapmar01", 2014, "pitcher"),    # 52% K rate
]


@pytest.mark.parametrize("label,pid,year,kind", ARCHETYPES,
                         ids=[a[0] for a in ARCHETYPES])
def test_archetype_generates_valid_accurate_card(label, pid, year, kind):
    """Cards must track stats tightly except where the card format itself
    can't (clamped below-average categories) — and then a warning is
    mandatory. Official SOM cards share exactly these limitations."""
    if kind == "batter":
        stats = db.batting_season(pid, year)
        assert stats is not None, f"no stats for {pid} {year}"
        league = db.league_batting(year, stats["league"])
        card, warnings = generate_batter_card(stats, league)
        err = score_batter_card(card, stats, league)
        # Hit-total redistribution must hold BA for every archetype.
        if not any("hit total runs high" in w for w in warnings):
            assert err["BA"] < 0.008, (label, err, warnings)
            assert err["H_per_PA"] < 0.005, (label, err, warnings)
    else:
        stats = db.pitching_season(pid, year)
        assert stats is not None, f"no stats for {pid} {year}"
        league = db.league_batting(year, stats["league"])
        card, warnings = generate_pitcher_card(stats, league)
        err = score_pitcher_card(card, stats, league)
        if not any("hits allowed will run" in w for w in warnings):
            assert err["H_per_PA"] < 0.008, (label, err, warnings)
        if err[WALK] >= 0.008:
            assert any("walks will run" in w for w in warnings), (label, err)
        if err[SO] >= 0.008:
            assert any("strikeouts will run" in w for w in warnings), (label, err)
    assert card.validate() == []


def test_above_average_categories_are_tracked_closely():
    """For categories where the player is at/above league average no
    clamping occurs, so the card must nail the rate."""
    stats = db.batting_season("mcgwima01", 1998)
    league = db.league_batting(1998, stats["league"])
    card, _ = generate_batter_card(stats, league)
    err = score_batter_card(card, stats, league)
    assert err[HR] < 0.002
    assert err[WALK] < 0.002
    assert err[SO] < 0.002


def test_below_average_categories_warn():
    stats = db.batting_season("gwynnto01", 1995)  # far below league K rate
    league = db.league_batting(1995, stats["league"])
    _card, warnings = generate_batter_card(stats, league)
    assert any("strikeouts" in w for w in warnings)


def test_tiny_sample_warns():
    stats = db.batting_season("murphda05", 1976)  # 65 AB
    league = db.league_batting(1976, stats["league"])
    _card, warnings = generate_batter_card(stats, league)
    assert any("small sample" in w for w in warnings)


def test_no_pa_raises():
    with pytest.raises(ValueError):
        generate_batter_card({"name": "Nobody", "AB": 0},
                             db.league_batting(2000, "AL"))


def test_pre_ibb_era_league_warning_passes_through():
    stats = db.batting_season("ruthba01", 1927)
    league = db.league_batting(1927, "AL")
    _card, warnings = generate_batter_card(stats, league)
    assert any("IBB" in w or "SF" in w for w in warnings)


def _text_share(card, base, suffix):
    """Chance-weighted share of `base` outcomes carrying `suffix`."""
    from stratogen.model import DICE_WEIGHTS
    total = match = 0.0
    for _c, d, s in card.iter_splits():
        if s.text.startswith(base):
            w = DICE_WEIGHTS[d] * s.fraction
            total += w
            if s.text == base + suffix:
                match += w
    return match / total if total else 0.0


def _card_for(pid, year):
    stats = db.batting_season(pid, year)
    league = db.league_batting(year, stats["league"])
    card, _ = generate_batter_card(stats, league)
    return card


def test_hit_symbol_shares_are_the_real_card_means():
    """The */** shares are the official basic batter cards' means (isolated
    power, which used to set them, anti-correlates with the real shares),
    recomputed here from the fixtures, chance-weighted within each card."""
    import statistics
    from stratogen.benchmark import transcription_cases
    from stratogen.card_text import load_real_cards
    from stratogen.generate import (DOUBLE_2STAR_SHARE, SINGLE_2STAR_SHARE,
                                    SINGLE_STAR_SHARE)
    cards = [c for stem, c in load_real_cards().items()
             if c.card_type == "batter"
             and stem not in ("posnanski_2014", "raines_hero")]
    cards += [c.reps["basic"] for c in transcription_cases()
              if c.card_type == "batter" and c.official and "basic" in c.reps]
    shares = {"SINGLE**": [], "SINGLE*": [], "DOUBLE**": []}
    for card in cards:
        for base in ("SINGLE", "DOUBLE"):
            parts = {}
            for _c, d, s in card.iter_splits():
                if s.text.startswith(base):
                    suffix = s.text[len(base):].strip()
                    parts[suffix] = parts.get(suffix, 0.0) + DICE_WEIGHTS[d] * s.fraction
            total = sum(parts.values())
            if not total:
                continue
            if base == "SINGLE":
                shares["SINGLE**"].append(parts.get("**", 0.0) / total)
                shares["SINGLE*"].append(parts.get("*", 0.0) / total)
            else:
                shares["DOUBLE**"].append(parts.get("**", 0.0) / total)
    assert len(shares["SINGLE**"]) >= 19
    for key, value in (("SINGLE**", SINGLE_2STAR_SHARE),
                       ("SINGLE*", SINGLE_STAR_SHARE),
                       ("DOUBLE**", DOUBLE_2STAR_SHARE)):
        assert statistics.mean(shares[key]) == pytest.approx(value, abs=0.02), (
            key, statistics.mean(shares[key]))


def test_dp_letters_track_gidp_tendency():
    """Jim Rice (36 GIDP in 1984) gets more double-play A groundouts than
    a fast low-GIDP runner."""
    rice = _card_for("riceji01", 1984)
    coleman = _card_for("colemvi01", 1987)

    def gb_a_share(card):
        from stratogen.model import DICE_WEIGHTS
        a = total = 0.0
        for _c, d, s in card.iter_splits():
            if s.text.startswith("groundball"):
                w = DICE_WEIGHTS[d] * s.fraction
                total += w
                if s.text.rstrip("+").endswith("A"):
                    a += w
        return a / total if total else 0.0

    assert gb_a_share(rice) > gb_a_share(coleman)


def test_plus_plus_tracks_speed_and_stays_off_pitcher_cards():
    coleman = _card_for("colemvi01", 1987)   # extremely fast
    fielder = _card_for("fieldce01", 1991)   # Cecil Fielder, not fast
    def pp(card):
        return sum(1 for _c, _d, s in card.iter_splits() if s.text.endswith("++"))
    assert pp(coleman) > pp(fielder)

    stats = db.pitching_season("ryanno01", 1974)
    league = db.league_batting(1974, stats["league"])
    pitcher_card, _ = generate_pitcher_card(stats, league)
    assert pp(pitcher_card) == 0  # rulebook 6.1: ++ is batter-cards-only


def test_stealing_rating_capped_when_cs_untracked():
    """Pre-1951 runners must not get AA off volume alone (CS unknown)."""
    from stratogen.ratings import stealing_rating
    cobb = db.batting_season("cobbty01", 1911)   # 83 SB, CS not tracked
    assert "CS" in cobb["missing"]
    assert stealing_rating(cobb["SB"], cobb["CS"], cs_missing=True) == "A"
    # measured elite seasons still earn AA
    assert stealing_rating(60, 9) == "AA"  # Raines fixture
    # and the card carries a warning
    league = db.league_batting(1911, "AL")
    _card, warnings = generate_batter_card(cobb, league)
    assert any("stealing rating estimated" in w for w in warnings)


def test_strikeouts_and_walks_spread_across_columns():
    """No single column may hoard a category (real cards mix them)."""
    from stratogen.model import DICE_WEIGHTS, SO, WALK
    for pid, year in [("judgeaa01", 2022), ("mcgwima01", 1998),
                      ("bondsba01", 2001)]:
        card = _card_for(pid, year)
        for cat in (SO, WALK):
            per_col = {}
            for col, d, s in card.iter_splits():
                if s.category == cat:
                    per_col[col] = per_col.get(col, 0.0) + DICE_WEIGHTS[d] * s.fraction
            total = sum(per_col.values())
            if total >= 9:  # only meaningful with a real allocation
                # 0.72 allows extreme cards (Bonds's 41 walk chances crowd
                # the board) while still catching one-column hoarding —
                # the old layout put 87% of Judge's strikeouts in column 1.
                assert max(per_col.values()) <= 0.72 * total, (pid, cat, per_col)


def test_monte_carlo_agrees_with_exact_rates():
    """The Monte Carlo simulator and the closed-form expectation must agree
    (sanity check that both read the cards the same way)."""
    stats = db.batting_season("mayswi01", 1965)
    league = db.league_batting(1965, "NL")
    card, _ = generate_batter_card(stats, league)
    # Lay out an average pitcher card for the pairing
    from stratogen.generate import layout_card
    avg = layout_card(average_pitcher_chances(league), card_type="pitcher",
                      name="AVERAGE", year=1965, team=None, stats={},
                      header_lines=[])
    exact = combined_rates(card, avg)
    n = 200_000
    counts = simulate_season(card, avg, num_pa=n, seed=42)
    for cat in (HR, WALK, SO):
        assert counts[cat] / n == pytest.approx(exact[cat], abs=0.004), cat


# --- pitcher hit targets ---------------------------------------------------------

@pytest.mark.parametrize("year,lg", [(1908, "NL"), (1930, "NL"), (1968, "AL"),
                                     (2001, "NL"), (2024, "AL")])
def test_league_average_pitcher_line_is_the_average_card(year, lg):
    """A pitcher with exactly the league's line gets exactly the average
    pitcher card: the X block's singles come out of the singles share
    alone, so doubles and triples allowed keep the league mix (they used
    to be scaled down ~25% along with the singles)."""
    from stratogen.generate import pitcher_targets_from_rates
    league = db.league_batting(year, lg)
    targets = pitcher_targets_from_rates(
        league["BB_per_PA"], league["K_per_PA"], league["HR_per_PA"],
        league["H_per_PA"], league, [])
    for cat, value in average_pitcher_chances(league).items():
        assert targets[cat] == pytest.approx(value, abs=1e-6), cat


def test_dominant_reliever_x_block_never_adds_hits():
    """Brandon Workman 2019 allowed 29 hits in 71.2 IP, fewer than the 30
    X chances' own singles: the block shrinks so it can't add hits he
    never allowed (39 in play before), and one quantified warning says
    how far above his line the card's floor still is."""
    stats = db.pitching_season("workmbr01", 2019)
    league = db.league_batting(2019, stats["league"])
    card, warnings = generate_pitcher_card(stats, league)
    assert card.chances()["X"] < 30
    hit_warnings = [w for w in warnings if "hits allowed" in w]
    assert len(hit_warnings) == 1 and "% of PA high" in hit_warnings[0]
    from stratogen.simulate import pitcher_effective_pa
    err = score_pitcher_card(card, stats, league)
    floor = league["H_per_PA"] / 2 - stats["H"] / pitcher_effective_pa(stats)
    assert err["H_per_PA"] == pytest.approx(floor, abs=1e-9)


# --- pitcher denominators -----------------------------------------------------

def test_pitcher_effective_pa_leaves_out_sacrifices():
    """Pitcher rates use the league's footing (AB + BB - IBB + HBP + SF):
    Lahman BFP also counts sacrifice hits, which are a manager's call, not
    a card result."""
    from stratogen.simulate import _league_pitching_sums, pitcher_effective_pa
    ryan = db.pitching_season("ryanno01", 1972)          # SH tracked
    assert pitcher_effective_pa(ryan) == ryan["TBF"] - ryan["IBB"] - ryan["SH"]
    # SH untracked (pre-1970): scaled by the league's PA_eff / sum(BFP - IBB),
    # which is the league's sacrifice share (1930 NL: 2.8% of BFP)
    league = db.league_batting(1930, "NL")
    factor = league["PA_eff"] / _league_pitching_sums()[(1930, "NL")][0]
    assert 1 / factor == pytest.approx(1 + league["raw"]["SH"] / league["PA_eff"],
                                       abs=0.001)
    hubbell = db.pitching_season("hubbeca01", 1930)
    assert "SH" in hubbell["missing"]
    assert pitcher_effective_pa(hubbell, league) == pytest.approx(
        (hubbell["TBF"] - hubbell["IBB"]) * factor)
    assert pitcher_effective_pa(hubbell) == pitcher_effective_pa(hubbell, league)
    # BFP untracked (1925 NNL): the IP/H/BB/HBP estimate, calibrated per league
    dean = db.pitching_season("deanne01", 1925)
    assert "TBF" in dean["missing"]
    raw = round(dean["IP"] * 3) + dean["H"] + dean["BB"] + dean["HBP"]
    assert 0.94 * raw < pitcher_effective_pa(dean) < 0.98 * raw
    _card, warnings = generate_pitcher_card(
        dean, db.league_batting(1925, dean["league"]))
    assert any("batters faced not recorded" in w and "estimated" in w
               for w in warnings)
    # a bare stat line with no league to look up is taken as printed
    assert pitcher_effective_pa({"TBF": 600, "IBB": 5}) == 595


def test_ryan_1972_strikeouts_match_the_real_card():
    """The real card carries 47 strikeout chances; with sacrifices out of
    the denominator the formula gives 46.1 (45.5 with them in)."""
    from stratogen.generate import pitcher_chance_targets
    stats = db.pitching_season("ryanno01", 1972)
    league = db.league_batting(1972, stats["league"])
    targets, _ = pitcher_chance_targets(stats, league)
    assert targets[SO] == pytest.approx(46.1, abs=0.05)


# --- out content and decorations -------------------------------------------------

@pytest.mark.parametrize("pid,year,kind", [
    ("mayswi01", 1965, "batter"), ("riceji01", 1984, "batter"),
    ("colemvi01", 1987, "batter"), ("maddugr01", 1995, "pitcher"),
    ("seaveto01", 1969, "pitcher")])
def test_out_mix_is_allocated_not_drawn(pid, year, kind):
    """Out types, letters and fielders are allocated by quota once every
    out piece is known, so each card realizes its mix (and its profile's
    groundball-A share) instead of scattering around it cell by cell."""
    from stratogen.generate import _OutFlavors, hit_profile
    from stratogen.model import DICE_WEIGHTS, OUT
    if kind == "batter":
        stats = db.batting_season(pid, year)
        card = _card_for(pid, year)
    else:
        stats = db.pitching_season(pid, year)
        card, _ = generate_pitcher_card(stats, db.league_batting(year, stats["league"]))
    mix = dict(zip(_OutFlavors._TYPES, _OutFlavors._MIX[kind]))
    got, gb = {}, {}
    for _c, d, s in card.iter_splits():
        if s.category == OUT:
            w = DICE_WEIGHTS[d] * s.fraction
            out_type = s.text.split()[0]
            got[out_type] = got.get(out_type, 0.0) + w
            if out_type == "groundball":
                letter = s.text.rstrip("+")[-1]
                gb[letter] = gb.get(letter, 0.0) + w
    total = sum(got.values())
    for t, share in mix.items():
        assert got.get(t, 0.0) / total == pytest.approx(share / 100, abs=0.035), (t, got)
    if kind == "batter":
        assert set(gb) <= {"A", "B"}
        assert gb.get("A", 0) / sum(gb.values()) == pytest.approx(
            hit_profile(stats)["gb_a"], abs=0.05)
    else:
        assert "A" not in gb


def test_decorations_sit_where_real_cards_put_them():
    """Max-effort lineout on a 1-chance row (every real card puts it
    there) and the injury on a light row, also on cards with no whole out row to spare
    (Gallo 2019, Sano 2015, Cust 2007 used to lose one or both); ++ only on
    groundball-A results."""
    from stratogen.model import DICE_WEIGHTS
    for pid, year in [("mayswi01", 1965), ("judgeaa01", 2024), ("gallojo01", 2019),
                      ("sanomi01", 2015), ("custja01", 2007), ("colemvi01", 1987)]:
        card = _card_for(pid, year)
        maxlo = [d for _c, d, s in card.iter_splits() if "as many outs" in s.text]
        injury = {(c, d) for c, d, s in card.iter_splits() if s.injury}
        assert len(maxlo) == 1 and DICE_WEIGHTS[maxlo[0]] == 1, (pid, maxlo)
        # real cards: injury on 1-chance rows 17 times of 22, else 2 or 3
        assert len(injury) == 1 and DICE_WEIGHTS[next(iter(injury))[1]] <= 3, pid
        for _c, _d, s in card.iter_splits():
            if s.text.endswith("++"):
                assert s.text[:-2].endswith("A"), s.text
