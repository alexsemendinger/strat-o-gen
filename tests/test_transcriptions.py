"""The JSON-transcribed real cards: loading, vocabulary, structure, stats.

These 25 cards (data/real_cards/transcriptions/) expand the ground-truth
corpus and guard the import layer (stratogen/card_json.py). Unofficial cards
and two documented edge cases are tested *tolerantly*: a failure only they
exhibit is allowed (xfail), per the project's "real cards aren't perfect"
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

# Documented tolerances (failure allowed, with reason). See the dir README.
TOLERANT_CARDS = {
    "batter_judge-aaron_2024":
        "extreme 2024 season: HR and walk totals can't both fit 108 chances, "
        "so the real basic card trades away HR (confirmed from the photo)",
    "pitcher_bruney-brian_2008":
        "36-IP reliever: tiny platoon samples make the combined-advanced "
        "hit rate noisy",
}

STRICT_HIT = 0.015      # BA / hits-per-PA
STRICT_RATE = 0.020     # HR / BB / SO per PA


def _tolerant(card_id, official):
    return (not official) or (card_id in TOLERANT_CARDS)


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
    if not ok and _tolerant(cid, card.official):
        pytest.xfail(f"{cid}: tolerant card; {problems or total}")
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


def test_have_statistical_cases():
    # most cards resolve to a real season; HOF/undated are excluded
    assert len(CASES) >= 20


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
    if worst and _tolerant(card_id, case.official):
        reason = TOLERANT_CARDS.get(card_id, "unofficial card")
        pytest.xfail(f"{card_id} [{rep}]: {worst} — {reason}")
    assert not worst, f"{card_id} [{rep}] exceeds bars: {worst}"


def test_official_corpus_is_tight_in_aggregate():
    """Beyond per-card bars: the official cards as a group must be accurate
    (guards against systemic drift the generous per-card bars might miss)."""
    errs = {"hit": [], "HR": [], "BB": [], "SO": []}
    for case in CASES:
        if not case.official or case.card_id in TOLERANT_CARDS:
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
