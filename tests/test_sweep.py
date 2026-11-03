"""A deterministic sweep over the random-season pool: card conventions and
layout precision hold beyond the 14 fixtures, in every era."""

import random

import pytest

from stratogen.generate import (
    batter_chance_targets, generate_batter_card, generate_pitcher_card,
    pitcher_chance_targets,
)
from stratogen.lahman import default_db
from stratogen.model import DICE_WEIGHTS

db = default_db()
_rng = random.Random(2026)
SAMPLE = sorted({db.random_season(_rng) for _ in range(600)})
# seasons whose cards once lost their injury or max-effort lineout
EDGES = [("gallojo01", 2019, "batter"), ("sanomi01", 2015, "batter"),
         ("custja01", 2007, "batter")]


def _card(pid, year, kind):
    if kind == "batter":
        stats = db.batting_season(pid, year)
        league = db.league_batting(year, stats["league"])
        return generate_batter_card(stats, league)[0], \
            batter_chance_targets(stats, league)[0]
    stats = db.pitching_season(pid, year)
    league = db.league_batting(year, stats["league"])
    return generate_pitcher_card(stats, league)[0], \
        pitcher_chance_targets(stats, league)[0]


def test_sweep_cards_are_valid_and_on_target():
    """Every card validates and carries each category within 0.11 chances
    of its target (over 1500 pool seasons the worst miss is 0.098)."""
    misses = []
    for pid, year, kind in SAMPLE + EDGES:
        card, targets = _card(pid, year, kind)
        assert card.validate() == [], (pid, year)
        placed = card.chances()
        for cat, t in targets.items():
            if abs(placed.get(cat, 0.0) - t) > 0.11:
                misses.append((pid, year, cat, round(t, 3), placed.get(cat)))
    assert not misses, misses
    assert len(SAMPLE) > 500


@pytest.mark.parametrize("pid,year,kind", EDGES + [
    s for s in SAMPLE if s[2] == "batter"][:150])
def test_sweep_batter_conventions(pid, year, kind):
    """Exactly one injury result and one max-effort lineout on every
    batter card, the lineout on a 1-chance row as on every real card."""
    card, _ = _card(pid, year, kind)
    injuries = {(c, d) for c, d, s in card.iter_splits() if s.injury}
    max_outs = [d for _c, d, s in card.iter_splits()
                if "as many outs as possible" in s.text]
    assert len(injuries) == 1
    assert len(max_outs) == 1 and DICE_WEIGHTS[max_outs[0]] == 1
