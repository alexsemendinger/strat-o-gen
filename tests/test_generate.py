"""Generator tests across player archetypes, eras, and edge cases."""

import pytest

from stratogen.generate import generate_batter_card, generate_pitcher_card
from stratogen.benchmark import score_batter_card, score_pitcher_card
from stratogen.lahman import default_db
from stratogen.model import HR, SO, WALK
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
