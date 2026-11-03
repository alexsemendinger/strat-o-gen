"""Stealing and running ratings against every real card that prints them.

Truth: the 20 dated real batter cards — the plain-text fixtures (Raines'
composite and the fictional Posnanski excluded) and the JSON
transcriptions (both sides print the same stealing/running).
"""

import pytest

from stratogen import ratings
from stratogen.fielding import position_ratings
from stratogen.lahman import default_db

db = default_db()

# (player_id, year, stealing, running)
TRUTH = [
    ("bondsba01", 2001, "B", 14), ("cartega01", 1975, "C", 12),
    ("cespeyo01", 2016, "D", 13), ("dawsoan01", 1977, "A", 15),
    ("fostege01", 1971, "C", 13), ("mayswi01", 1965, "C", 17),
    ("murphda05", 1976, "E", 10), ("murraed02", 1977, "E", 11),
    ("beninan01", 2022, "C", 13), ("careyan01", 1953, "C", 14),
    ("combsea01", 1930, "B", 16), ("henderi01", 1986, "AA", 17),
    ("judgeaa01", 2024, "B", 13), ("lemahdj01", 2021, "D", 13),
    ("linzph01", 1963, "D", 14), ("pippwa01", 1921, "B", 12),
    ("posadjo01", 2003, "D", 9), ("rizzuph01", 1949, "B", 17),
    ("silvech01", 1949, "D", 8), ("strawda01", 1985, "A", 17),
]


def _header(pid, year):
    return ratings.batter_header_lines(db.batting_season(pid, year),
                                       position_ratings(db, pid, year))


def _printed(lines, prefix):
    return next(ln[len(prefix):] for ln in lines if ln.startswith(prefix))


def test_truth_matches_transcriptions():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "data" / "real_cards"
    for path in sorted((root / "transcriptions").glob("som_batter_*_3col.json")):
        r = json.loads(path.read_text(encoding="utf-8"))["ratings"]
        year = path.stem.split("_")[-2]
        if not year.isdigit():
            continue   # the Sewell Hall of Fame composite
        row = next(t for t in TRUTH if t[1] == int(year)
                   and t[0][:4] in path.stem.replace("-", ""))
        assert (r["stealing"], int(r["running"].split("-")[1])) == row[2:], path


def test_running_agreement():
    """9/20 exact, 17/20 within one, mean error 0.85 (leave-one-out, see
    the running_rating docstring: 8/20, 15/20, 1.00). The old SB/triples
    heuristic: 6/20, 12/20, 1.45."""
    got = [(int(_printed(_header(pid, y), "running 1-")), run)
           for pid, y, _s, run in TRUTH]
    exact = sum(g == t for g, t in got)
    within = sum(abs(g - t) <= 1 for g, t in got)
    mae = sum(abs(g - t) for g, t in got) / len(got)
    assert exact >= 9 and within >= 17 and mae <= 0.9, got


def test_running_reaches_the_slow_end():
    """Catchers print 1-8 / 1-9; the old formula couldn't go below 10."""
    assert _printed(_header("silvech01", 1949), "running 1-") == "8"
    assert _printed(_header("posadjo01", 2003), "running 1-") == "9"


def test_stealing_agreement():
    """18/20 exact; LeMahieu 2021 (C vs D) and Carey 1953 (D vs C) miss —
    both about attempts per opportunity, which volume can't see."""
    got = [(_printed(_header(pid, y), "stealing-"), steal)
           for pid, y, steal, _r in TRUTH]
    assert sum(g == t for g, t in got) >= 18, got
    order = ["AA", "A", "B", "C", "D", "E"]
    assert all(abs(order.index(g) - order.index(t)) <= 1 for g, t in got)


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
