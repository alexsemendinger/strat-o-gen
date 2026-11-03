"""Fielding ratings calibrated against the ratings printed on real cards.

Single-season fielding stats are noisy and official SOM raters use
scouting judgment, so the bar is: within +/-1 of the official rating
almost everywhere, with a healthy share of exact matches. Clay Kirby is
a known outlier (3 errors in 19 chances in 1975 and a bad 1974, yet the
card reads "2" — either generous official rating or the header digit
isn't a fielding rating; see data/real_cards/README.md).

Ground truth is every range rating printed on a real card: the 14 plain-
text fixtures (GROUND_TRUTH) plus both sides of the dated JSON
transcriptions (JSON_TRUTH, read from data/real_cards/transcriptions/).
The basic and advanced sides of one card sometimes disagree by one (Judge
cf-2/rf-1 vs cf-3/rf-2), so +/-1 is partly noise in the truth itself.
"""

import json
from pathlib import Path

import pytest

from stratogen import fielding
from stratogen.fielding import (
    peer_league_sets, position_ratings, rate_position, unrecorded_positions,
)
from stratogen.lahman import default_db

db = default_db()

# (player_id, year, position, official rating from the fixture card)
GROUND_TRUTH = [
    ("mayswi01", 1965, "CF", 1),
    ("bondsba01", 2001, "LF", 2),
    ("cespeyo01", 2016, "LF", 2),
    ("cespeyo01", 2016, "CF", 3),
    ("murraed02", 1977, "1B", 4),
    ("murraed02", 1977, "LF", 4),
    ("cartega01", 1975, "C", 3),
    ("cartega01", 1975, "RF", 3),
    ("cartega01", 1975, "3B", 4),
    ("dawsoan01", 1977, "CF", 3),
    ("dawsoan01", 1977, "LF", 3),
    ("dawsoan01", 1977, "RF", 3),
    ("fostege01", 1971, "CF", 3),
    ("fostege01", 1971, "LF", 3),
    ("fostege01", 1971, "RF", 3),
    ("murphda05", 1976, "C", 3),
    ("seaveto01", 1969, "P", 1),
    ("ryanno01", 1972, "P", 4),
    ("colonba01", 2016, "P", 1),
]
KNOWN_OUTLIERS = [("kirbycl01", 1975, "P", 2)]

TRANSCRIPTIONS = (Path(__file__).resolve().parent.parent
                  / "data" / "real_cards" / "transcriptions")
# JSON card stem -> Lahman season (official, dated cards only)
JSON_CARDS = {
    "batter_benintendi-andrew_2022": ("beninan01", 2022),
    "batter_carey-andy_1953": ("careyan01", 1953),
    "batter_combs-earle_1930": ("combsea01", 1930),
    "batter_henderson-rickey_1986": ("henderi01", 1986),
    "batter_judge-aaron_2024": ("judgeaa01", 2024),
    "batter_lemahieu-dj_2021": ("lemahdj01", 2021),
    "batter_linz-phil_1963": ("linzph01", 1963),
    "batter_pipp-wally_1921": ("pippwa01", 1921),
    "batter_posada-jorge_2003": ("posadjo01", 2003),
    "batter_rizzuto-phil_1949": ("rizzuph01", 1949),
    "batter_silvera-charlie_1949": ("silvech01", 1949),
    "batter_strawberry-darryl_1985": ("strawda01", 1985),
    "pitcher_bruney-brian_2008": ("brunebr01", 2008),
    "pitcher_capuano-chris_2014": ("capuach01", 2014),
    "pitcher_gibson-paul_1994": ("gibsopa01", 1994),
    "pitcher_mendoza-ramiro_2001": ("mendora01", 2001),
    "pitcher_monroe-zach_1958": ("monroza01", 1958),
    "pitcher_perez-melido_1994": ("perezme01", 1994),
    "pitcher_pettitte-andy_2012": ("pettian01", 2012),
}
_POS = {"leftfield": "LF", "lf": "LF", "centerfield": "CF", "cf": "CF",
        "rightfield": "RF", "rf": "RF", "catcher": "C", "c": "C",
        "1st base": "1B", "1b": "1B", "2nd base": "2B", "2b": "2B",
        "3rd base": "3B", "3b": "3B", "shortstop": "SS", "ss": "SS"}


def _json_truth(side: str) -> list[tuple[str, int, str, int]]:
    """Every range rating on one side ('3col' basic / '6col' advanced)."""
    out = []
    for stem, (pid, year) in JSON_CARDS.items():
        ratings = json.loads((TRANSCRIPTIONS / f"som_{stem}_{side}.json")
                             .read_text(encoding="utf-8"))["ratings"]
        for f in ratings.get("fielding") or []:
            out.append((pid, year, _POS[f["pos"].lower()], int(f["rating"])))
        if (ratings.get("pitcherFielding") or "").startswith("pitcher-"):
            out.append((pid, year, "P", int(ratings["pitcherFielding"][-1])))
    return out


JSON_TRUTH = _json_truth("3col")          # basic sides
JSON_ADVANCED_TRUTH = _json_truth("6col")
ALL_BASIC = GROUND_TRUTH + JSON_TRUTH
PITCHER_TRUTH = [t for t in ALL_BASIC if t[2] == "P"]


def _agreement(truth):
    got = [(rate_position(db, pid, year, pos), official)
           for pid, year, pos, official in truth]
    exact = sum(g == o for g, o in got)
    within = sum(g is not None and abs(g - o) <= 1 for g, o in got)
    return exact, within


def _check_ids():
    """The ground-truth IDs must point at the right seasons."""
    for pid, year, pos, _ in GROUND_TRUTH + JSON_TRUTH:
        assert db.fielding_by_position(pid, year), (pid, year)


def test_ground_truth_ids_resolve():
    _check_ids()
    assert len(JSON_TRUTH) == 34 and len(JSON_ADVANCED_TRUTH) == 34


@pytest.mark.parametrize("pid,year,pos,official", GROUND_TRUTH)
def test_rating_within_one_of_official(pid, year, pos, official):
    got = rate_position(db, pid, year, pos)
    assert got is not None
    assert abs(got - official) <= 1, f"{pid} {year} {pos}: got {got}, card says {official}"


def test_calibration_quality_overall():
    """At least half the official ratings must be matched exactly."""
    exact = sum(1 for pid, year, pos, official in GROUND_TRUTH
                if rate_position(db, pid, year, pos) == official)
    assert exact >= len(GROUND_TRUTH) // 2, f"only {exact}/{len(GROUND_TRUTH)} exact"


# Agreement on every printed rating (README "Known limitations"). Before the
# league-aware pools and innings-based pitcher range: fixtures 10/19 exact
# (19 within one), JSON basic sides 12/34 (28), advanced sides 10/34 (28),
# pitchers 3/10 (10). Off by two: Carey 3B (2 vs 4: a 40-game rookie
# season), Judge RF (1 vs 3: a reputation rating, he played CF in 2024),
# LeMahieu 2B (1 vs 3: Gold Glove-calibre, box scores show average range).
def test_json_card_agreement():
    assert _agreement(JSON_TRUTH) >= (18, 31)
    assert _agreement(JSON_ADVANCED_TRUTH) >= (16, 31)
    assert _agreement(ALL_BASIC) >= (28, 50)            # of 53


def test_pitcher_agreement_and_leave_one_out(monkeypatch):
    """Pitchers: range per nine innings, one fitted parameter (the 0.4
    threshold shift). In-sample 8/10 exact; leave-one-out (shift refitted
    on the other nine from -0.8..+0.4) 6/10 exact; always within one."""
    assert _agreement(PITCHER_TRUTH) >= (8, 10)
    shifts = [s / 10 for s in range(-8, 5)]

    def thresholds(shift):
        return tuple(t + shift for t in fielding._THRESHOLDS)

    preds = {}
    for shift in shifts:
        monkeypatch.setattr(fielding, "_THRESHOLDS_P", thresholds(shift))
        preds[shift] = [rate_position(db, pid, year, "P")
                        for pid, year, _pos, _o in PITCHER_TRUTH]
    truth = [o for *_x, o in PITCHER_TRUTH]
    exact = within = 0
    for i, official in enumerate(truth):
        def fit(shift):
            hits = sum(p == t for j, (p, t) in enumerate(zip(preds[shift], truth))
                       if j != i)
            return hits, -abs(shift - fielding._P_THRESHOLD_SHIFT)
        best = max(shifts, key=fit)
        exact += preds[best][i] == official
        within += abs(preds[best][i] - official) <= 1
    assert (exact, within) >= (6, 10)


def test_known_outlier_documented():
    """Kirby drifts 2 from the card; if this ever *passes* the +/-1 check,
    move him into GROUND_TRUTH."""
    pid, year, pos, official = KNOWN_OUTLIERS[0]
    got = rate_position(db, pid, year, pos)
    assert abs(got - official) >= 2


def test_gold_glove_vs_butcher_spread():
    """Sanity: legendary gloves rate well, legendary non-gloves don't.

    Adam Dunn only manages "never above average" here: box-score range
    factor can't see balls a slow fielder never reaches, so the worst
    defenders land at 3-4 rather than 5. Known limitation.
    """
    assert rate_position(db, "smithoz01", 1985, "SS") == 1   # Ozzie Smith
    assert rate_position(db, "belanma01", 1971, "SS") <= 2   # Mark Belanger
    assert rate_position(db, "dunnad01", 2009, "LF") >= 3    # Adam Dunn


def test_position_ratings_for_card_header():
    ratings = position_ratings(db, "mayswi01", 1965)
    assert ratings[0][0] == "CF"
    assert ratings[0][1] in (1, 2)
    # corner outfield split exists for the 1954+ AL/NL
    pos_codes = [p for p, _, _ in position_ratings(db, "cartega01", 1975)]
    assert "C" in pos_codes and "RF" in pos_codes


@pytest.mark.parametrize("pid,year,printed", [
    ("cartega01", 1975, {"C", "RF", "3B"}),       # 3B: one game
    ("dawsoan01", 1977, {"CF", "LF", "RF"}),      # RF: three games
    ("murraed02", 1977, {"1B", "LF"}),            # LF: three games
    ("careyan01", 1953, {"3B", "2B", "SS"}),      # 2B one game, SS two
    ("linzph01", 1963, {"SS", "3B", "2B", "CF", "RF", "LF"}),
])
def test_short_stints_are_printed_like_real_cards(pid, year, printed):
    """Real cards list one-game positions and long lists; the header must
    too (a player may only field the positions on his card)."""
    assert {p for p, _r, _g in position_ratings(db, pid, year)} == printed


def test_position_players_pitching_cameo_not_listed():
    # Brian Dozier 2019: 123 games at 2B, one mop-up inning
    assert [p for p, _r, _g in position_ratings(db, "doziebr01", 2019)] == ["2B"]
    # ...but a pitcher who only pitched keeps it (Ohtani 2023 fielded only P)
    assert [p for p, _r, _g in position_ratings(db, "ohtansh01", 2023)] == ["P"]


def test_pre_split_outfield_falls_back_to_combined_outfield():
    ratings = position_ratings(db, "duffyhu01", 1890)
    assert any(pos == "OF" for pos, _, _ in ratings)
    # MLB corners aren't split before 1954: a corner is rated on the
    # combined line (Combs 1930's card: lf-2 rf-2 cf-3)
    of = rate_position(db, "combsea01", 1930, "OF")
    assert rate_position(db, "combsea01", 1930, "LF") == of
    assert rate_position(db, "combsea01", 1930, "CF") == of


def test_no_data_returns_none():
    assert rate_position(db, "mayswi01", 1965, "C") is None


def test_small_sample_cannot_be_extreme():
    """A handful of games shrinks toward average: never 1 or 5."""
    # Murray played 22 games in LF as a rookie DH — must be 2-4.
    got = rate_position(db, "murraed02", 1977, "LF")
    assert got in (2, 3, 4)


# --- pitchers: range per nine innings, not per game ---------------------------

def test_relievers_and_starters_rated_on_one_scale():
    """Chances per game measure innings per appearance: rated per game,
    1990-2019 starters averaged 1.87 and relievers 3.25 (none a 1). Per
    nine innings the two groups land within a few tenths."""
    ratings = {"start": [], "relief": []}
    for year in range(1990, 2020, 3):
        for pid in db.season_pitchers(year):
            s = db.pitching_season(pid, year)
            if s["G"] < 25:
                continue
            kind = ("start" if s["GS"] >= 0.8 * s["G"]
                    else "relief" if s["GS"] == 0 else None)
            if kind:
                ratings[kind].append(rate_position(db, pid, year, "P"))
    mean = {k: sum(v) / len(v) for k, v in ratings.items()}
    assert abs(mean["start"] - mean["relief"]) < 0.4, mean
    assert 1 in ratings["relief"]


# --- league-aware peer pools ----------------------------------------------------

def test_peer_pools_are_league_aware():
    # From 1901 the AL and NL form one pool; Negro leagues their own,
    # widened to the year's other Negro/independent leagues if too small
    assert peer_league_sets(db, 1925, "SS", "AL")[0] == {"AL", "NL"}
    assert peer_league_sets(db, 1925, "SS", "NNL")[:2] == [{"NNL"}, {"NNL", "ECL"}]
    # 1925 NNL/ECL left PO and A blank: those rows no longer drag the MLB
    # norm down (mixed pool: mean range 3.0, sd 2.4)
    mean, sd = fielding._peer_distribution(db, 1925, "SS", "AL")["rf"]
    assert mean > 4.5 and sd < 1.2


def test_unrecorded_fielding_is_not_read_as_zero():
    # Walter Cannady 1925 ECL: 71 games at SS, PO/A/E blank — was a 5
    assert rate_position(db, "cannawa01", 1925, "SS") == 3
    assert "SS" in unrecorded_positions(db, "cannawa01", 1925)
    # Newt Allen 1925 (48 games at 2B, blank): rated from 1923-24, not a 5
    assert rate_position(db, "allenne02", 1925, "2B") < 5
    assert unrecorded_positions(db, "mayswi01", 1965) == []


def test_negro_league_fielders_rated_against_their_own_leagues():
    """Regulars 1920-48 (sampled every 4th season): mixing pools rated
    Negro-league regulars 1.2 grades worse than MLB regulars on average;
    against their own leagues the gap is under 0.3."""
    db.warm()
    mlb, negro = [], []
    for (pid, year), positions in db._fielding.items():   # every fielder
        if year < 1920 or year > 1948 or year % 4:
            continue
        for pos in ("1B", "2B", "3B", "SS", "OF"):
            line = db.fielding_by_position(pid, year).get(pos)
            if not line:
                continue
            major = line["lg"] in ("AL", "NL")
            if line["G"] >= (100 if major else 30):
                (mlb if major else negro).append(rate_position(db, pid, year, pos))
    gap = sum(negro) / len(negro) - sum(mlb) / len(mlb)
    assert len(negro) > 200 and abs(gap) < 0.3, gap
