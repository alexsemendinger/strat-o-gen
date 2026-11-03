"""The JSON-transcribed real cards: loading, vocabulary, structure, stats.

These 25 cards (data/real_cards/transcriptions/) expand the ground-truth
corpus and guard the import layer (stratogen/card_json.py). Two documented
real-card compromises are tolerated per card, side and category (xfail);
every other category of those cards, and every unofficial card, is held
to the strict bars, per the project's "real cards aren't perfect"
philosophy.
"""

import glob
import json
import math
import os

import pytest

from stratogen import card_json as cj
from stratogen.benchmark import (
    score_batter_card, score_pitcher_card, transcription_cases,
)
from stratogen.model import CHANCES_PER_CARD, XCHANCE, categorize

CARDS = cj.load_transcriptions()
JSON_FILES = sorted(glob.glob(
    os.path.join(os.path.dirname(cj.TRANSCRIPTIONS_DIR), "transcriptions", "*.json")))

# Documented tolerances: {card_id: {side: categories allowed to fail}} and
# the reason. Any other failing category still fails. See the dir README.
TOLERANCES = {
    "batter_judge-aaron_2024": {"basic": {"HR", "SO"}, "advanced": {"SO"}},
    "pitcher_bruney-brian_2008": {"advanced": {"H_per_PA"}},
}
TOLERANCE_REASONS = {
    "batter_judge-aaron_2024":
        "the real card under-prints HR (basic side) and SO (both sides); "
        "the generated card fits HR, BB and SO exactly, so this is the real "
        "card's compromise, not a 108-chance limit",
    "pitcher_bruney-brian_2008":
        "34-IP reliever: tiny platoon samples make the combined-advanced "
        "hit rate noisy",
}

STRICT_HIT = 0.015      # BA / hits-per-PA
STRICT_RATE = 0.020     # HR / BB / SO per PA


def _tolerant(card_id, official):
    """Excluded from the aggregate guard (unofficial or documented)."""
    return (not official) or (card_id in TOLERANCES)


# --- loading -----------------------------------------------------------------

def test_loads_all_cards():
    assert len(CARDS) == 25
    assert sum(c.card_type == "batter" for c in CARDS.values()) == 13
    assert sum(c.card_type == "pitcher" for c in CARDS.values()) == 12


def test_unofficial_cards_flagged():
    unofficial = {cid for cid, c in CARDS.items() if not c.official}
    assert unofficial == {
        "pitcher_orth-al_1906", "pitcher_shawkey-bob_1917",
        "pitcher_warhop-jack_1914", "pitcher_zuber-bill_1945"}


def test_sides_joined_by_card_id():
    pipp = CARDS["batter_pipp-wally_1921"]
    assert pipp.basic is not None and pipp.advanced is not None
    # advanced-only cards have no basic side
    assert CARDS["pitcher_orth-al_1906"].basic is None
    assert CARDS["pitcher_mcdaniel-lindy_undated"].basic is None


# --- vocabulary (normalizer regression guard) --------------------------------

def _all_tokens():
    for path in JSON_FILES:
        d = json.loads(open(path).read())
        for grid in d["grids"]:
            for col in grid["columns"]:
                for cell in col["cells"]:
                    for o in cell["outcomes"]:
                        yield path, o["result"]


def test_every_token_normalizes_and_categorizes():
    seen = set()
    for _path, token in _all_tokens():
        text, _injury = cj.parse_result(token)   # must not raise
        categorize(text)                          # must not raise
        seen.add(token)
    assert len(seen) > 150  # the full vocabulary is exercised


def test_token_categories_are_sane():
    # a few hand-checked mappings across the abbreviated vocabulary
    cases = {
        "SI*": "1B", "SI**": "1B", "DO": "2B", "DO**": "2B", "TR": "3B",
        "HR": "HR", "N-HR": "HR", "WALK": "BB", "HBP plus injury": "HBP",
        "strikeout ●": "SO", "gb (ss) A": "OUT", "fly (rf) B?": "OUT",
        "lo (2b) max": "OUT", "GB (ss) X": "X", "GROUND-BALL(p)X": "X",
        "CATCH-X": "X", "CATCHER'S CARD X": "X", "▼SINGLE (lf)": "1B",
    }
    for token, expected in cases.items():
        text, _ = cj.parse_result(token)
        assert categorize(text) == expected, (token, text)


def test_injury_flag_parsed():
    assert cj.parse_result("gb (ss) A plus injury")[1] is True
    assert cj.parse_result("HBP plus injury")[1] is True
    assert cj.parse_result("strikeout")[1] is False


# --- structure ---------------------------------------------------------------

def _sides_and_grids():
    for cid, card in sorted(CARDS.items()):
        for side in card.sides:
            for i, grid in enumerate(side.grids):
                yield cid, card, side, i, grid


@pytest.mark.parametrize("cid,side_label,gi", [
    (cid, side.side, i) for cid, _c, side, i, _g in _sides_and_grids()])
def test_every_grid_is_a_valid_108_chance_card(cid, side_label, gi):
    card = CARDS[cid]
    side = card.basic if side_label == "3col" else card.advanced
    grid_card = cj._grid_card(side, side.grids[gi], card.name)
    problems = grid_card.validate()
    total = sum(grid_card.chances().values())
    ok = (not problems) and math.isclose(total, CHANCES_PER_CARD, abs_tol=1e-6)
    assert ok, f"{cid} {side_label} grid {gi}: {problems or total}"


def test_basic_pitcher_cards_carry_30_x_chances():
    """Every *basic*-side pitcher card carries the standard 30-chance X-chart
    block. (Advanced platoon sides distribute X differently — e.g. Capuano
    32, McDaniel 41/34 — so the rule is basic-side only.)"""
    off_failures = []
    for cid, card in CARDS.items():
        if card.card_type != "pitcher" or card.basic is None:
            continue
        x = cj._grid_card(card.basic, card.basic.grids[0], card.name).chances()[XCHANCE]
        if not math.isclose(x, 30.0, abs_tol=0.5):
            off_failures.append((cid, round(x, 1)))
    assert not off_failures, off_failures


# --- statistical benchmark ---------------------------------------------------

CASES = transcription_cases()
SCORE_TARGETS = [(c.card_id, rep) for c in CASES for rep in c.reps]


RESOLVED = {
    "batter_benintendi-andrew_2022", "batter_carey-andy_1953",
    "batter_combs-earle_1930", "batter_henderson-rickey_1986",
    "batter_judge-aaron_2024", "batter_lemahieu-dj_2021",
    "batter_linz-phil_1963", "batter_pipp-wally_1921",
    "batter_posada-jorge_2003", "batter_rizzuto-phil_1949",
    "batter_silvera-charlie_1949", "batter_strawberry-darryl_1985",
    "pitcher_bruney-brian_2008", "pitcher_capuano-chris_2014",
    "pitcher_gibson-paul_1994", "pitcher_mendoza-ramiro_2001",
    "pitcher_monroe-zach_1958", "pitcher_orth-al_1906",
    "pitcher_perez-melido_1994", "pitcher_pettitte-andy_2012",
    "pitcher_shawkey-bob_1917", "pitcher_warhop-jack_1914",
    "pitcher_zuber-bill_1945",
}


def test_have_statistical_cases():
    """Every dated card resolves to its Lahman season (only the HOF Sewell
    and the undated McDaniel can't); a card silently dropping out of the
    benchmark fails here."""
    assert {c.card_id for c in CASES} == RESOLVED


# Printed-vs-Lahman differences known to be on the card, not the match.
KNOWN_PRINT_DIFFS = {
    ("batter_linz-phil_1963", "HR"):
        "statRecord says 6, but the card's own SLG .349 and Lahman say 2; "
        "re-check the photo",
}


@pytest.mark.parametrize("card_id", sorted(RESOLVED))
def test_printed_line_matches_lahman(card_id):
    """benchmark_cases() cross-checks the .txt cards' printed lines; do the
    same for the transcriptions (a wrong player match or a bad
    transcription shows up here)."""
    case = next(c for c in CASES if c.card_id == card_id)
    printed = cj.stat_record(case.transcription.basic or case.transcription.advanced)
    if not printed:
        pytest.skip("no printed stat line (advanced-only unofficial card)")
    actual = case.actual_stats
    keys = (("AB", "HR", "SO") if case.card_type == "batter"
            else ("W", "L", "SO", "BB"))
    for key in keys:
        if key not in printed or (card_id, key) in KNOWN_PRINT_DIFFS:
            continue
        assert abs(printed[key] - actual[key]) <= 2, (key, printed[key], actual[key])
    if case.card_type == "pitcher" and "IP" in printed:
        assert abs(printed["IP"] - actual["IP"]) <= 1.0


@pytest.mark.parametrize("card_id,rep", SCORE_TARGETS)
def test_card_reproduces_real_season(card_id, rep):
    case = next(c for c in CASES if c.card_id == card_id)
    scorer = (score_pitcher_card if case.card_type == "pitcher"
              else score_batter_card)
    err = scorer(case.reps[rep], case.actual_stats, case.league)
    hit_key = "H_per_PA" if case.card_type == "pitcher" else "BA"
    checks = [
        (hit_key, err[hit_key], STRICT_HIT),
        ("HR", err["HR"], STRICT_RATE),
        ("BB", err["BB"], STRICT_RATE),
        ("SO", err["SO"], STRICT_RATE),
    ]
    worst = [(k, v, lim) for k, v, lim in checks if v > lim]
    allowed = TOLERANCES.get(card_id, {}).get(rep, set())
    if worst and {k for k, _v, _lim in worst} <= allowed:
        pytest.xfail(f"{card_id} [{rep}]: {worst}: {TOLERANCE_REASONS[card_id]}")
    assert not worst, f"{card_id} [{rep}] exceeds bars: {worst}"


def test_official_corpus_is_tight_in_aggregate():
    """Beyond per-card bars: the official cards as a group must be accurate
    (guards against systemic drift the generous per-card bars might miss)."""
    errs = {"hit": [], "HR": [], "BB": [], "SO": []}
    for case in CASES:
        if _tolerant(case.card_id, case.official):
            continue
        scorer = (score_pitcher_card if case.card_type == "pitcher"
                  else score_batter_card)
        for rep in case.reps:
            e = scorer(case.reps[rep], case.actual_stats, case.league)
            errs["hit"].append(e["H_per_PA"] if case.card_type == "pitcher"
                               else e["BA"])
            for k in ("HR", "BB", "SO"):
                errs[k].append(e[k])
    for k, values in errs.items():
        mean = sum(values) / len(values)
        assert mean < 0.008, (k, mean)


# --- archival integrity ------------------------------------------------------

def test_markers_preserved_in_json():
    """The verbatim JSON must retain the situational/marker glyphs even
    though the Card model drops them — they're future-feature material."""
    d = json.loads(open(os.path.join(
        cj.TRANSCRIPTIONS_DIR, "som_batter_judge-aaron_2024_6col.json")).read())
    markers = {m for g in d["grids"] for col in g["columns"]
               for cell in col["cells"] for m in (cell.get("markers") or [])}
    assert {"omega", "diamond", "downTriangle"} & markers


# --- generated basic cards vs the real basic sides --------------------------------

# A real basic side the generated card may trail in one category, by design.
GENERATED_TRADEOFFS = {
    ("batter_silvera-charlie_1949", "1B"):
        "his 2B/3B/HR clamp to 0; the deficit comes out of singles so total "
        "hits stay exact (the real card misses H/PA by .0035)",
}


@pytest.mark.parametrize("card_id", sorted(
    c.card_id for c in CASES if "basic" in c.reps))
def test_generated_card_matches_real_basic_side(card_id):
    """Like tests/test_benchmark.py for the .txt fixtures: per category the
    generated basic card may trail the real basic side by at most 0.002 per
    PA (advanced sides: tests/test_platoon.py)."""
    from stratogen.generate import generate_batter_card, generate_pitcher_card
    case = next(c for c in CASES if c.card_id == card_id)
    if case.card_type == "pitcher":
        scorer, gen = score_pitcher_card, generate_pitcher_card
    else:
        scorer, gen = score_batter_card, generate_batter_card
    card, _ = gen(case.actual_stats, case.league)
    real = scorer(case.reps["basic"], case.actual_stats, case.league)
    mine = scorer(card, case.actual_stats, case.league)
    for key, value in real.items():
        if (card_id, key) in GENERATED_TRADEOFFS:
            assert mine["H_per_PA"] <= real["H_per_PA"]
            continue
        assert mine[key] <= value + 0.002, (key, mine[key], value)
