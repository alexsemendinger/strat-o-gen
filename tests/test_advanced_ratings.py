"""Advanced-side ratings calibrated against the real-card transcriptions.

Ground truth is every rating printed on the advanced (6col) side of the
official JSON-transcribed cards (data/real_cards/transcriptions/), keyed to
the Lahman season. Sewell (HOF composite) and McDaniel (undated) are
excluded; the four unofficial dead-ball pitchers are weak evidence and
checked tolerantly. As in tests/test_fielding.py the bar is "close almost
everywhere, exact often": official formulas are proprietary and SOM's
raters see play-by-play data that box scores don't have. Known outliers
are documented here rather than fitted away; if one ever starts passing
the strict check, move it into the truth table.
"""

import json
import math
import re

import pytest

from stratogen import advanced_ratings as ar
from stratogen import card_json as cj
from stratogen.lahman import default_db

db = default_db()
CARDS = cj.load_transcriptions()

# cardId -> (Lahman playerID, season)
PLAYERS = {
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
    "pitcher_orth-al_1906": ("orthal01", 1906),
    "pitcher_shawkey-bob_1917": ("shawkbo01", 1917),
    "pitcher_warhop-jack_1914": ("warhoja01", 1914),
    "pitcher_zuber-bill_1945": ("zuberbi01", 1945),
}
EXCLUDED = {"batter_sewell-joe_HOF", "pitcher_mcdaniel-lindy_undated"}

# (cardId, position, official eN). Outfielders carry one e for all three
# spots, so each player's outfield rating appears once.
ERROR_TRUTH = [
    ("batter_benintendi-andrew_2022", "LF", 0),
    ("batter_carey-andy_1953", "3B", 6),
    ("batter_carey-andy_1953", "2B", 41),
    ("batter_carey-andy_1953", "SS", 88),
    ("batter_combs-earle_1930", "LF", 12),
    ("batter_henderson-rickey_1986", "CF", 7),
    ("batter_judge-aaron_2024", "CF", 0),
    ("batter_lemahieu-dj_2021", "2B", 4),
    ("batter_lemahieu-dj_2021", "1B", 4),
    ("batter_lemahieu-dj_2021", "3B", 29),
    ("batter_linz-phil_1963", "SS", 29),
    ("batter_linz-phil_1963", "3B", 18),
    ("batter_linz-phil_1963", "2B", 41),
    ("batter_linz-phil_1963", "RF", 13),
    ("batter_pipp-wally_1921", "1B", 16),
    ("batter_rizzuto-phil_1949", "SS", 24),
    ("batter_strawberry-darryl_1985", "RF", 3),
    ("batter_posada-jorge_2003", "C", 1),
    ("batter_silvera-charlie_1949", "C", 5),
]

# Outfield arms (lower = stronger)
ARM_TRUTH = [
    ("batter_henderson-rickey_1986", 2),
    ("batter_linz-phil_1963", 2),
    ("batter_combs-earle_1930", 3),
    ("batter_benintendi-andrew_2022", 0),
]
# Strong arms that deterred runners instead of collecting assists: box-score
# assists can't see them (Judge: 4 assists vs 4.2 expected; Strawberry 6 vs
# 7.7). Documented, not fitted away.
ARM_OUTLIERS = [
    ("batter_judge-aaron_2024", -4),
    ("batter_strawberry-darryl_1985", -2),
]

# (cardId, arm, T-1-N, pb-N)
CATCHER_TRUTH = [
    ("batter_posada-jorge_2003", 0, 7, 4),
    ("batter_silvera-charlie_1949", 1, 9, 0),
]

# (cardId, bunting, hit & run)
BATTER_LETTERS = [
    ("batter_benintendi-andrew_2022", "D", "C"),
    ("batter_carey-andy_1953", "D", "D"),
    ("batter_combs-earle_1930", "C", "B"),
    ("batter_henderson-rickey_1986", "D", "C"),
    ("batter_judge-aaron_2024", "D", "D"),
    ("batter_lemahieu-dj_2021", "D", "B"),
    ("batter_linz-phil_1963", "B", "B"),
    ("batter_pipp-wally_1921", "A", "B"),
    ("batter_posada-jorge_2003", "D", "D"),
    ("batter_rizzuto-phil_1949", "A", "B"),
    ("batter_silvera-charlie_1949", "D", "B"),
    ("batter_strawberry-darryl_1985", "D", "D"),
]

# (cardId, e, hold, wp, bk, bunting, starter, relief, closer)
PITCHER_TRUTH = [
    ("pitcher_bruney-brian_2008", 0, 3, 6, 0, "C", None, 1, "0"),
    ("pitcher_capuano-chris_2014", 15, -4, 18, 4, "C", 6, 3, "N"),
    ("pitcher_gibson-paul_1994", 0, 4, 7, 10, "C", None, 1, "N"),
    ("pitcher_mendoza-ramiro_2001", 0, 0, 4, 0, "D", 5, 3, "3"),
    ("pitcher_monroe-zach_1958", 24, -2, 0, 0, "D", 5, 3, "0"),
    ("pitcher_perez-melido_1994", 10, 0, 10, 2, "C", 6, None, None),
    ("pitcher_pettitte-andy_2012", 0, -3, 2, 0, "B", 6, None, None),
]
# Unofficial dead-ball cards: (cardId, e, starter, relief) — weak evidence
UNOFFICIAL_PITCHERS = [
    ("pitcher_orth-al_1906", 34, 8, 5),
    ("pitcher_shawkey-bob_1917", 24, 8, 5),
    ("pitcher_warhop-jack_1914", 46, 8, 5),
    ("pitcher_zuber-bill_1945", 11, 8, 5),
]

LETTERS = "ABCDE"


def _pid(cid):
    return PLAYERS[cid]


def _letter_gap(a, b):
    return abs(LETTERS.index(a) - LETTERS.index(b))


@pytest.fixture(scope="module")
def pitchers():
    return {cid: ar.advanced_pitcher_ratings(db, *_pid(cid))
            for cid, *_ in PITCHER_TRUTH + UNOFFICIAL_PITCHERS}


# --- the truth tables are the cards ----------------------------------------

def _ratings(cid):
    return CARDS[cid].advanced and json.loads(
        CARDS[cid].advanced.path.read_text(encoding="utf-8"))["ratings"]


def _num(text, signed=True):
    m = re.search(r"[+-]?\d+" if signed else r"\d+", str(text))
    return int(m.group()) if m else None


def test_truth_tables_match_transcriptions():
    """Every hand-keyed truth value is read back from the JSON source."""
    for cid, pos, e in ERROR_TRUTH:
        fielding = {f["pos"].upper(): f for f in _ratings(cid)["fielding"]}
        assert fielding[pos]["error"] == f"e{e}", (cid, pos)
    for cid, arm in ARM_TRUTH + ARM_OUTLIERS:
        # the verbatim header in the notes, e.g. 'cf-1(+2) e7' / 'lf-2(0) e0'
        printed = re.findall(r"\b(?:lf|cf|rf)-\d\(([+-]?\d+)\)", _ratings(cid)["notes"])
        assert {int(a) for a in printed} == {arm}, cid
    for cid, arm, t, pb in CATCHER_TRUTH:
        text = json.dumps(_ratings(cid))
        m = re.search(r"c-\d\(([+-]?\d+)\) e\d+,\s*T-1-(\d+)\(pb-(\d+)\)", text)
        assert m and tuple(int(g) for g in m.groups()) == (arm, t, pb), cid
    for cid, bunt, hr in BATTER_LETTERS:
        r = _ratings(cid)
        assert (r["bunting"], r["hitAndRun"]) == (bunt, hr), cid
    for cid, e, hold, wp, bk, bunt, starter, relief, closer in PITCHER_TRUTH:
        r = _ratings(cid)
        assert _num(r["hold"]) == hold, cid
        assert _num(r["wildPitch"], signed=False) == wp, cid   # 'wp-18'
        assert _num(r["balk"], signed=False) == bk, cid
        assert r["bunting"][-1] == bunt, cid
        assert re.search(rf"(?<![\w-])e{e}\b", r["notes"]), cid
        assert _num(r["role"].get("starter")) == starter, cid
        assert _num(r["role"].get("relief")) == relief, cid
        suffix = re.search(r"relief\s*\(\d\)\s*/\s*([N\d])", r["notes"])
        assert (suffix.group(1) if suffix else None) == closer, cid
    for cid, e, starter, relief in UNOFFICIAL_PITCHERS:
        r = _ratings(cid)
        assert not CARDS[cid].official
        assert f"e{e}" in r["notes"]
        assert (_num(r["role"]["starter"]), _num(r["role"]["relief"])) == (starter, relief)


def test_ids_point_at_the_right_seasons():
    for cid, (pid, year) in PLAYERS.items():
        assert CARDS[cid].year == year
        assert db.batting_season(pid, year) or db.pitching_season(pid, year), cid
    assert not EXCLUDED & set(PLAYERS)


# --- error ratings -----------------------------------------------------------

@pytest.mark.parametrize("cid,pos,official", ERROR_TRUTH)
def test_error_rating_close_to_official(cid, pos, official):
    got = ar.error_rating(db, *_pid(cid), pos)
    assert got is not None
    assert abs(got - official) <= 3, f"{cid} {pos}: e{got}, card e{official}"


def test_error_rating_calibration_quality():
    """Fitted on these 19: 11 exact, 16 within one (README)."""
    got = [(ar.error_rating(db, *_pid(cid), pos), e) for cid, pos, e in ERROR_TRUTH]
    exact = sum(g == e for g, e in got)
    within = sum(abs(g - e) <= 1 for g, e in got)
    assert exact >= 11, got
    assert within >= 16, got


@pytest.mark.parametrize("cid,e", [(row[0], row[1]) for row in PITCHER_TRUTH])
def test_pitcher_error_rating_exact(cid, e, pitchers):
    assert pitchers[cid]["error"] == e


@pytest.mark.parametrize("cid,e,starter,relief", UNOFFICIAL_PITCHERS)
def test_unofficial_pitchers_within_one(cid, e, starter, relief, pitchers):
    """Weak evidence only: the same formula lands within one."""
    r = pitchers[cid]
    assert abs(r["error"] - e) <= 1
    assert abs(r["starter"] - starter) <= 1
    assert abs(r["relief"] - relief) <= 1


def test_outfield_error_is_shared_across_spots():
    r = ar.advanced_batter_ratings(db, "judgeaa01", 2024)
    outfield = [p["error"] for p in r["positions"] if p["pos"] in ("LF", "CF", "RF")]
    assert len(outfield) >= 2 and len(set(outfield)) == 1


# --- arms, catcher detail ----------------------------------------------------

@pytest.mark.parametrize("cid,official", ARM_TRUTH)
def test_outfield_arm_within_one(cid, official):
    got = ar.outfield_arm(db, *_pid(cid))
    assert abs(got - official) <= 1, f"{cid}: arm {got}, card {official}"


def test_outfield_arm_quality():
    got = [(ar.outfield_arm(db, *_pid(cid)), a) for cid, a in ARM_TRUTH + ARM_OUTLIERS]
    assert sum(g == a for g, a in got) >= 2, got


@pytest.mark.parametrize("cid,official", ARM_OUTLIERS)
def test_outfield_arm_outliers_documented(cid, official):
    """Still weaker than the card, but on the strong side of the weak arms."""
    got = ar.outfield_arm(db, *_pid(cid))
    assert abs(got - official) >= 2
    assert got <= 1


@pytest.mark.parametrize("cid,arm,t,pb", CATCHER_TRUTH)
def test_catcher_detail(cid, arm, t, pb):
    got_arm = ar.catcher_arm(db, *_pid(cid))
    assert abs(got_arm - arm) <= 1
    assert abs(ar.catcher_throwing(got_arm) - t) <= 2
    assert ar.catcher_passed_balls(db, *_pid(cid)) == pb


def test_posada_header_matches_card():
    lines = ar.advanced_batter_header_lines(
        ar.advanced_batter_ratings(db, "posadjo01", 2003))
    assert lines[0] == "c-3(0) e1, T-1-7(pb-4)"


# --- bunting / hit & run -----------------------------------------------------

@pytest.mark.parametrize("cid,bunt,hit_run", BATTER_LETTERS)
def test_batter_letters_exact(cid, bunt, hit_run):
    stats = db.batting_season(*_pid(cid))
    assert ar.bunting_rating(db, stats) == bunt
    assert ar.hit_and_run_rating(db, stats) == hit_run


def _loo(score, truth, higher_is_better):
    """Leave-one-out: cut points refitted (class midpoints) without the card."""
    order = "ABCD"
    hits = within = 0
    for i, (s_i, t_i) in enumerate(zip(score, truth)):
        rest = [(s, t) for j, (s, t) in enumerate(zip(score, truth)) if j != i]
        got = "D"
        for k, letter in enumerate(order[:-1]):
            better = [s for s, t in rest if order.index(t) <= k]
            worse = [s for s, t in rest if order.index(t) > k]
            if not better or not worse:
                continue
            cut = ((min(better) + max(worse)) / 2 if higher_is_better
                   else (max(better) + min(worse)) / 2)
            if (s_i >= cut) if higher_is_better else (s_i < cut):
                got = letter
                break
        hits += got == t_i
        within += abs(order.index(got) - order.index(t_i)) <= 1
    return hits, within


def test_batter_letters_leave_one_out():
    bunt, hit_run, bunt_truth, hr_truth = [], [], [], []
    for cid, b, h in BATTER_LETTERS:
        s = db.batting_season(*_pid(cid))
        pa = ar._pa(s)
        sh_lg = ar._league_rate(db, s["year"], s["league"], "SH")
        so_lg = ar._league_rate(db, s["year"], s["league"], "SO")
        bunt.append(s["SH"] / (pa * sh_lg + ar.BUNT_PSEUDO_SH))
        hit_run.append(((s["SO"] + ar.HIT_RUN_PSEUDO_PA * so_lg)
                        / (pa + ar.HIT_RUN_PSEUDO_PA)) / so_lg)
        bunt_truth.append(b)
        hr_truth.append(h)
    assert _loo(bunt, bunt_truth, True) >= (9, 12)
    assert _loo(hit_run, hr_truth, False) >= (11, 12)


# --- pitchers ----------------------------------------------------------------

def _pitcher_rows(pitchers, index, key):
    return [(pitchers[row[0]][key], row[index]) for row in PITCHER_TRUTH]


@pytest.mark.parametrize("key,index,min_exact", [
    ("wp", 3, 6), ("bk", 4, 6), ("bunting", 5, 7),
    ("starter", 6, 7), ("relief", 7, 7), ("closer", 8, 7),
])
def test_pitcher_ratings_agreement(pitchers, key, index, min_exact):
    rows = _pitcher_rows(pitchers, index, key)
    assert sum(g == t for g, t in rows) >= min_exact, rows
    for got, truth in rows:
        if isinstance(truth, int):
            assert abs(got - truth) <= 1, rows


def test_hold_prior_agreement(pitchers):
    """Hold has no Lahman basis (a handedness prior): 3/7 exact, 4/7 within one."""
    rows = _pitcher_rows(pitchers, 2, "hold")
    assert sum(g == t for g, t in rows) >= 3, rows
    assert sum(abs(g - t) <= 1 for g, t in rows) >= 4, rows


def test_endurance_roles(pitchers):
    """Starter/relief tags appear exactly where the cards print them."""
    for cid, *_x, starter, relief, _closer in PITCHER_TRUTH:
        r = pitchers[cid]
        assert (r["starter"] is None) == (starter is None), cid
        assert (r["relief"] is None) == (relief is None), cid


def test_pitcher_header_lines_format():
    lines = ar.advanced_pitcher_header_lines({
        "fielding": 2, "error": 15, "starter": 6, "relief": 3, "closer": "N",
        "hold": -4, "wp": 18, "bk": 4, "bunting": "C"})
    assert lines == ["pitcher-2 e15", "starter(6) relief(3)/N", "hold -4",
                     "wp-18", "bk-4", "bunting-C"]
    lines = ar.advanced_pitcher_header_lines({
        "fielding": 3, "error": 0, "starter": None, "relief": 1, "closer": "0",
        "hold": 3, "wp": None, "bk": None, "bunting": "C"})
    assert lines == ["pitcher-3 e0", "relief(1)/0", "hold +3", "bunting-C"]


def test_batter_header_lines_format():
    lines = ar.advanced_batter_header_lines({
        "positions": [
            {"pos": "CF", "range": 1, "games": 138, "error": 7, "arm": 2},
            {"pos": "LF", "range": 1, "games": 11, "error": 7}],
        "stealing": "AA", "running": 17, "bunting": "D", "hit_and_run": "C"})
    assert lines == ["cf-1(+2) e7", "lf-1 e7", "stealing-AA", "bunting-D",
                     "hit & run-C", "running 1-17"]
    lines = ar.advanced_batter_header_lines({
        "positions": [], "stealing": "E", "running": 10, "bunting": "C",
        "hit_and_run": "C"})
    assert lines[0] == "dh"


def test_arm_printed_on_first_outfield_spot_only():
    r = ar.advanced_batter_ratings(db, "linzph01", 1963)
    outfield = [p for p in r["positions"] if p["pos"] in ("LF", "CF", "RF")]
    assert "arm" in outfield[0] and all("arm" not in p for p in outfield[1:])
    assert all("arm" not in p for p in r["positions"]
               if p["pos"] not in ("LF", "CF", "RF", "OF", "C"))


# --- stealing detail ---------------------------------------------------------

def test_every_stealing_detail_parses():
    details = [(r["stealingDetail"], r.get("stealing")) for c in CARDS.values()
               if c.advanced and (r := _ratings(c.card_id)).get("stealingDetail")]
    assert len(details) >= 19
    for text, grade in details:
        parsed = ar.parse_stealing_detail(text)
        assert parsed is not None, text
        if parsed["numbers"] is None:       # '-/- (---)': can't steal
            assert grade == "E" and not parsed["rolls_a"] + parsed["rolls_b"]
        else:
            assert 1 <= parsed["numbers"][0] <= 20


def test_stealing_detail_structure():
    linz = ar.parse_stealing_detail("*2-4,11/5-10,12 (15-1)")
    assert linz["star"] and linz["numbers"] == (15, 1)
    assert sorted(linz["rolls_a"] + linz["rolls_b"]) == list(range(2, 13))
    judge = ar.parse_stealing_detail("*3/- (20-6)")
    assert judge == {"star": True, "rolls_a": [3], "rolls_b": [], "numbers": (20, 6)}
    assert ar.parse_stealing_detail("6/- (15-6)")["star"] is False
    assert ar.parse_stealing_detail("-/- (---)") == {
        "star": False, "rolls_a": [], "rolls_b": [], "numbers": None}
    assert ar.parse_stealing_detail("garbage") is None
    assert ar.parse_stealing_detail("5/- (--)") is None


# --- monotonicity / sanity ---------------------------------------------------

class _StubDB:
    """The real database plus one synthetic player-season."""

    def __init__(self, fielding=None, pitching=None, batting=None, info=None):
        self._fielding = fielding or {}
        self._pitching = pitching
        self._batting = batting
        self._info = info or {}

    def __getattr__(self, name):
        return getattr(db, name)

    def fielding_by_position(self, pid, year):
        if pid == "fake":
            return self._fielding if year == 2000 else {}
        return db.fielding_by_position(pid, year)

    def pitching_season(self, pid, year):
        return self._pitching if pid == "fake" else db.pitching_season(pid, year)

    def batting_season(self, pid, year):
        return self._batting if pid == "fake" else db.batting_season(pid, year)

    def player_info(self, pid):
        return self._info if pid == "fake" else db.player_info(pid)


def _line(**kw):
    base = {"G": 150, "GS": 150, "InnOuts": 150 * 27, "PO": 250, "A": 450,
            "E": 15, "DP": 90, "PB": 0, "SB": 0, "CS": 0, "lg": "AL"}
    base.update(kw)
    return base


def test_more_errors_per_chance_raises_e():
    values = [ar.error_rating(_StubDB({"SS": _line(E=e)}), "fake", 2000, "SS")
              for e in (0, 5, 10, 20, 30)]
    assert values == sorted(values) and values[0] < values[-1]
    assert values[0] == 0


def test_cameo_never_error_free():
    cameo = ar.error_rating(_StubDB({"2B": _line(G=3, GS=3, InnOuts=81, PO=5,
                                                  A=8, E=0)}), "fake", 2000, "2B")
    regular = ar.error_rating(_StubDB({"2B": _line(PO=300, A=420, E=0)}),
                              "fake", 2000, "2B")
    assert regular == 0 and cameo > 10


def test_more_assists_stronger_arm():
    arms = [ar.outfield_arm(_StubDB({"RF": _line(PO=300, A=a, E=3)}), "fake", 2000)
            for a in (0, 4, 8, 14, 22)]
    assert arms == sorted(arms, reverse=True) and arms[0] > arms[-1]
    assert all(-6 <= a <= 5 for a in arms)


def test_catcher_monotonic():
    def catcher(**kw):
        return _StubDB({"C": _line(PO=900, A=60, E=5, **kw)})
    arms = [ar.catcher_arm(catcher(SB=100 - cs, CS=cs), "fake", 2000)
            for cs in (10, 25, 40, 55)]
    assert arms == sorted(arms, reverse=True) and arms[0] > arms[-1]
    pbs = [ar.catcher_passed_balls(catcher(PB=pb), "fake", 2000) for pb in (0, 5, 12, 25)]
    assert pbs == sorted(pbs) and pbs[0] < pbs[-1]


def _pitching(**kw):
    base = {"year": 2000, "league": "AL", "G": 32, "GS": 32, "IP": 200.0,
            "WP": 5, "BK": 1, "SV": 0, "missing": []}
    base.update(kw)
    return base


def test_more_wild_pitches_and_balks_raise_ratings():
    wps = [ar.wild_pitch_rating(_pitching(WP=w)) for w in (0, 3, 8, 15, 40)]
    bks = [ar.balk_rating(_pitching(BK=b)) for b in (0, 1, 3, 6, 30)]
    for seq in (wps, bks):
        assert seq == sorted(seq) and seq[0] == 0 and seq[-1] == ar.WP_BK_MAX
    assert ar.wild_pitch_rating(_pitching(missing=["WP"])) is None
    assert ar.balk_rating(_pitching(IP=0.0, BK=0)) == 0


def test_longer_starts_raise_starter_rating():
    ratings = [ar.starter_endurance(db, _pitching(IP=ip)) for ip in (130, 170, 200, 230)]
    assert ratings == sorted(ratings) and ratings[0] < ratings[-1]
    assert ar.starter_endurance(db, _pitching(G=40, GS=1, IP=60)) is None


def test_closer_monotonic():
    values = [ar.closer_rating({"SV": s}) for s in (0, 1, 6, 20, 45)]
    assert values[0] == "N"
    nums = [int(v) for v in values[1:]]
    assert nums == sorted(nums) and nums[-1] == 5


def test_hold_lefties_better():
    assert ar.hold_rating("L") < ar.hold_rating("R")


def test_bunting_and_hit_and_run_monotonic():
    base = db.batting_season("rizzuph01", 1949)
    bunts = [ar.bunting_rating(db, dict(base, SH=sh)) for sh in (0, 6, 12, 20, 40)]
    assert [LETTERS.index(b) for b in bunts] == sorted(
        (LETTERS.index(b) for b in bunts), reverse=True)
    assert bunts[0] == "D" and bunts[-1] == "A"
    hrs = [ar.hit_and_run_rating(db, dict(base, SO=so)) for so in (5, 30, 60, 120)]
    assert [LETTERS.index(h) for h in hrs] == sorted(LETTERS.index(h) for h in hrs)
    assert hrs[0] in "AB" and hrs[-1] == "D"


# --- every era, every gap: never raises, always well-formed -----------------

BATTER_LINE = re.compile(
    r"^(dh|(p|c|1b|2b|3b|ss|lf|cf|rf|of)-[1-5](\([+-]?\d\))? e\d{1,2}"
    r"(, T-1-\d{1,2}\(pb-\d{1,2}\))?|stealing-(AA|[A-E])|bunting-[A-D]"
    r"|hit & run-[A-D]|running 1-\d{1,2})$")
PITCHER_LINE = re.compile(
    r"^(pitcher-[1-5] e\d{1,2}|(starter\(\d\))?( ?relief\(\d\)/[N0-5])?"
    r"|hold [+-]?\d|wp-\d{1,2}|bk-\d{1,2}|bunting-[A-D])$")

ERA_BATTERS = [
    ("ansonca01", 1880),   # 19th century, no corner OF splits, no CS
    ("wagneho01", 1910),   # dead ball
    ("berrayo01", 1950),   # catcher, steals against not recorded
    ("henderi01", 1990),
    ("judgeaa01", 2024),
    ("ohtansh01", 2024),   # DH only: no positions
    ("warhoja01", 1914),   # a pitcher with a zero-chance outfield game
    ("cockrph01", 1925),   # Negro National League
    ("nosuchp01", 1950),   # unknown player
]
ERA_PITCHERS = [
    ("radboch01", 1884),
    ("youngcy01", 1890),
    ("johnswa01", 1910),
    ("cockrph01", 1925),   # Negro leagues: BFP and BK missing
    ("fellebo01", 1946),
    ("maddugr01", 1995),
    ("skenepa01", 2024),
    ("nosuchp01", 1950),   # unknown player
]


def test_zero_chance_and_missing_bfp_cases_exist():
    """The smoke test below really covers these gaps."""
    assert ar._tc(db.fielding_by_position("warhoja01", 1914)["OF"]) == 0
    assert "TBF" in db.pitching_season("cockrph01", 1925)["missing"]


@pytest.mark.parametrize("pid,year", ERA_BATTERS)
def test_batter_ratings_every_era(pid, year):
    r = ar.advanced_batter_ratings(db, pid, year)
    for key in ("bats", "positions", "stealing", "running", "bunting", "hit_and_run"):
        assert key in r
    for p in r["positions"]:
        assert 1 <= p["range"] <= 5
        assert p["error"] is None or 0 <= p["error"] <= 99
        if p.get("arm") is not None:
            assert -6 <= p["arm"] <= 5
    for line in ar.advanced_batter_header_lines(r):
        assert BATTER_LINE.match(line), line


@pytest.mark.parametrize("pid,year", ERA_PITCHERS)
def test_pitcher_ratings_every_era(pid, year):
    r = ar.advanced_pitcher_ratings(db, pid, year)
    assert 1 <= r["fielding"] <= 5 and 0 <= r["error"] <= 99
    assert r["starter"] is None or 1 <= r["starter"] <= 9
    assert r["relief"] is None or 1 <= r["relief"] <= 5
    assert -5 <= r["hold"] <= 5
    for key in ("wp", "bk"):
        assert r[key] is None or 0 <= r[key] <= ar.WP_BK_MAX
    assert r["bunting"] in "ABCD"
    for line in ar.advanced_pitcher_header_lines(r):
        assert PITCHER_LINE.match(line), line


def test_season_games():
    assert ar.season_games(1921, "AL") == 154
    assert ar.season_games(1961, "AL") == 162
    assert ar.season_games(1961, "NL") == 154
    assert ar.season_games(1994, "AL") == 162
    assert math.isclose(ar.season_games(1880), 154)
