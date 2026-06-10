"""Tests for the card text parser against the real-card fixtures."""

import math

import pytest

from stratogen import card_text
from stratogen.model import (
    CHANCES_PER_CARD, CHANCES_PER_COLUMN, DICE_WEIGHTS,
    HR, WALK, SO, XCHANCE, categorize,
)

REAL_CARDS = card_text.load_real_cards()


def test_all_fixtures_load():
    assert len(REAL_CARDS) == 14
    batters = [c for c in REAL_CARDS.values() if c.card_type == "batter"]
    pitchers = [c for c in REAL_CARDS.values() if c.card_type == "pitcher"]
    assert len(batters) == 10
    assert len(pitchers) == 4


@pytest.mark.parametrize("stem", sorted(REAL_CARDS))
def test_structurally_valid(stem):
    card = REAL_CARDS[stem]
    assert card.validate() == []


@pytest.mark.parametrize("stem", sorted(REAL_CARDS))
def test_chances_sum_to_108(stem):
    card = REAL_CARDS[stem]
    total = sum(card.chances().values())
    assert math.isclose(total, CHANCES_PER_CARD, abs_tol=1e-9)
    for col, rows in card.columns.items():
        col_total = sum(
            DICE_WEIGHTS[d] * s.fraction for d, splits in rows.items() for s in splits)
        assert math.isclose(col_total, CHANCES_PER_COLUMN, abs_tol=1e-9), col


@pytest.mark.parametrize("stem", sorted(s for s, c in REAL_CARDS.items()
                                        if c.card_type == "pitcher"))
def test_pitcher_cards_have_30_x_chances(stem):
    """Every official pitcher card carries exactly 30 X-chart chances."""
    card = REAL_CARDS[stem]
    assert math.isclose(card.chances()[XCHANCE], 30.0, abs_tol=1e-9)


def test_bonds_2001_known_chances():
    """Spot-check chance accounting against hand-counted values."""
    card = REAL_CARDS["bonds_2001"]
    chances = card.chances()
    # Col 1 rows 4-7 are full HOMERUN (3+4+5+6=18); row 8 is HR on 1-16 (5*0.8=4)
    assert math.isclose(chances[HR], 22.0, abs_tol=1e-9)
    # Walks: col1 rows 2,3 (1+2); col2 rows 6,12 (5+1); col3 all but row 5 (36-4)
    assert math.isclose(chances[WALK], 41.0, abs_tol=1e-9)
    # Strikeouts: col1 row 9 (4); col2 rows 5,9 (4+4)
    assert math.isclose(chances[SO], 12.0, abs_tol=1e-9)


def test_metadata_parsed():
    bonds = REAL_CARDS["bonds_2001"]
    assert bonds.name == "BARRY BONDS"
    assert bonds.year == 2001
    assert bonds.team == "SAN FRANCISCO"
    assert bonds.stats["HR"] == 73
    assert bonds.stats["BA"] == pytest.approx(0.328)

    seaver = REAL_CARDS["seaver_1969"]
    assert seaver.card_type == "pitcher"
    assert seaver.year == 1969
    assert seaver.stats["H"] == 202  # "HITS ALLOWED"
    assert seaver.stats["SO"] == 208
    assert seaver.stats["IP"] == 273

    raines = REAL_CARDS["raines_hero"]
    assert raines.year is None  # commemorative card, no year printed


def test_hyphen_rejoin_and_injury():
    seaver = REAL_CARDS["seaver_1969"]
    # "GROUND-\nBALL (2B) X" must rejoin to one token, category X
    texts = [s.text for _, _, s in seaver.iter_splits()]
    assert any(t.upper().startswith("GROUNDBALL") and t.upper().endswith("X")
               for t in texts)
    assert not any("GROUND-" in t for t in texts)

    bonds = REAL_CARDS["bonds_2001"]
    injury_splits = [(c, d, s) for c, d, s in bonds.iter_splits() if s.injury]
    assert [(c, d) for c, d, _ in injury_splits] == [(2, 2)]


def test_max_lineout_is_an_out():
    assert categorize("lineout (2b) into as many outs as possible") == "OUT"


@pytest.mark.parametrize("stem", sorted(REAL_CARDS))
def test_round_trip(stem):
    """parse -> render -> parse must preserve the card semantically."""
    card = REAL_CARDS[stem]
    reparsed = card_text.parse_card(card_text.render_card(card))
    assert reparsed.name == card.name
    assert reparsed.card_type == card.card_type
    assert reparsed.year == card.year
    assert reparsed.stats == card.stats
    assert reparsed.chances() == card.chances()
    for col in card.columns:
        for dice in card.columns[col]:
            a = [(s.lo, s.hi, s.text, s.injury) for s in card.columns[col][dice]]
            b = [(s.lo, s.hi, s.text, s.injury) for s in reparsed.columns[col][dice]]
            assert a == b, (stem, col, dice)
