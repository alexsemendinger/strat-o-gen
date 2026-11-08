"""Stealing and running ratings against every real card that prints them.

Truth: every dated real batter card — the plain-text fixtures (Raines'
composite and the fictional Posnanski excluded) and the JSON
transcriptions (a card's sides print the same stealing/running) — read
straight from the cards, so new cards join the check automatically.
"""

import json

import pytest

from stratogen import ratings
from stratogen.benchmark import benchmark_cases, transcription_cases
from stratogen.fielding import position_ratings
from stratogen.lahman import default_db

db = default_db()


def _truth():
    """[(card, player_id, year, stealing, running)] printed on the cards."""
    rows = []
    for case in benchmark_cases():
        if case.synthetic or case.card.card_type != "batter":
            continue
        lines = case.card.header_lines
        steal = next(ln for ln in lines if ln.startswith("stealing-"))[9:]
        run = int(next(ln for ln in lines if ln.startswith("running 1-"))[10:])
        rows.append((case.stem, case.actual_stats["player_id"],
                     case.actual_stats["year"], steal, run))
    for case in transcription_cases():
        if case.card_type != "batter":
            continue
        side = case.transcription.basic or case.transcription.advanced
        printed = json.loads(side.path.read_text(encoding="utf-8"))["ratings"]
        rows.append((case.card_id, case.actual_stats["player_id"],
                     case.actual_stats["year"], printed["stealing"].strip("()"),
                     int(str(printed["running"]).split("-")[1])))
    return rows


TRUTH = _truth()


def _header(pid, year):
    return ratings.batter_header_lines(db.batting_season(pid, year),
                                       position_ratings(db, pid, year))


def _printed(lines, prefix):
    return next(ln[len(prefix):] for ln in lines if ln.startswith(prefix))


def test_truth_covers_the_corpus():
    order = ["AA", "A", "B", "C", "D", "E"]
    assert len(TRUTH) >= 37
    assert all(steal in order and 1 <= run <= 20 for _c, _p, _y, steal, run in TRUTH)


def test_running_agreement():
    """On the 37 dated batter cards: 19 exact, 32 within one, mean error
    0.78 (on the first 20: 9, 17, 0.85; leave-one-out 8, 15, 1.00; the
    old SB/triples heuristic 6, 12, 1.45). Reputation ratings (Mays
    1965's 1-17 at 34) are the big misses."""
    got = [(int(_printed(_header(pid, y), "running 1-")), run)
           for _c, pid, y, _s, run in TRUTH]
    n = len(got)
    exact = sum(g == t for g, t in got)
    within = sum(abs(g - t) <= 1 for g, t in got)
    mae = sum(abs(g - t) for g, t in got) / n
    assert exact >= 0.45 * n and within >= 0.80 * n and mae <= 0.9, got


def test_running_reaches_the_slow_end():
    """Catchers print 1-8 / 1-9; the old formula couldn't go below 10."""
    assert _printed(_header("silvech01", 1949), "running 1-") == "8"
    assert _printed(_header("posadjo01", 2003), "running 1-") == "9"


def test_stealing_agreement():
    """35/37 exact, all within one grade (see stealing_rating); Carey 1953
    (a 2-for-3 cameo printed C) and Linz 1963 (1-for-7 printed D) miss."""
    got = [(card, _printed(_header(pid, y), "stealing-"), steal)
           for card, pid, y, steal, _r in TRUTH]
    order = ["AA", "A", "B", "C", "D", "E"]
    exact = sum(g == t for _c, g, t in got)
    assert exact >= 0.90 * len(got), [x for x in got if x[1] != x[2]]
    assert all(abs(order.index(g) - order.index(t)) <= 1 for _c, g, t in got)


def test_untracked_stolen_bases_are_neutral():
    """1884: SB not recorded. King Kelly was stealing-E / running 1-10."""
    lines = _header("kellyki01", 1884)
    assert "stealing-C" in lines
    assert int(_printed(lines, "running 1-")) >= 12
    assert ratings.stealing_rating(0, 0, sb_missing=True) == "C"


def test_position_labels_use_one_style():
    """'1st base' like '2nd base'/'3rd base' (1963 and 2014 cards), not a
    mix with the 1970s 'firstbase'."""
    lines = _header("lemahdj01", 2021)
    assert {ln.split("-")[0] for ln in lines[:3]} == {"2nd base", "1st base", "3rd base"}


def test_all_positions_reach_the_header():
    lines = _header("linzph01", 1963)
    assert sum(ln.endswith(tuple("12345")) and "-" in ln
               and not ln.startswith(("stealing", "running")) for ln in lines) == 6


@pytest.mark.parametrize("pid,year,roles", [
    ("mendora01", 2001, ["relief", "starter"]),   # 2 starts
    ("brunebr01", 2008, ["relief"]),              # 1 start
    ("capuach01", 2014, ["relief", "starter"]),
    ("perezme01", 1994, ["starter"]),
])
def test_pitcher_roles_match_cards(pid, year, roles):
    stats = db.pitching_season(pid, year)
    assert ratings.pitcher_header_lines(stats, 2)[1:] == roles
