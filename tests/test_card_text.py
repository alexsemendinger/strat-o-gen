"""Tests for the card text parser: the real-card fixtures, and round trips of
generated cards through every export format (basic text, advanced text and
advanced JSON)."""

import json
import math
import random

import pytest

from stratogen import card_json, card_text
from stratogen.fielding import position_ratings, rate_position
from stratogen.generate import (
    generate_advanced_batter_card, generate_advanced_pitcher_card,
    generate_batter_card, generate_pitcher_card,
)
from stratogen.lahman import default_db
from stratogen.simulate import effective_pa
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


def test_fixtures_resolve_from_any_working_directory(tmp_path, monkeypatch):
    """The data directories hang off the package, not the CWD: run from
    elsewhere, the corpora load in full (an empty corpus would turn every
    parametrized fixture test into a silent skip)."""
    assert card_text.REAL_CARDS_DIR.is_absolute()
    assert card_json.TRANSCRIPTIONS_DIR.is_absolute()
    n_txt = len(card_text.load_real_cards())
    n_json = len(card_json.load_transcriptions())
    assert n_txt == 14 and n_json >= 27
    monkeypatch.chdir(tmp_path)
    assert len(card_text.load_real_cards()) == n_txt
    assert len(card_json.load_transcriptions()) == n_json


def test_missing_fixtures_fail_loudly(tmp_path):
    for loader in (card_text.load_real_cards, card_json.load_transcriptions):
        with pytest.raises(FileNotFoundError):
            loader(tmp_path / "missing")
        with pytest.raises(FileNotFoundError):
            loader(tmp_path)                  # exists, but empty


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


def test_max_lineout_parsed_as_one_out():
    """Every fixture batter prints one max-effort lineout, wrapped over
    several lines; it must rejoin into a single OUT reading."""
    for stem, card in REAL_CARDS.items():
        texts = [s.text for _c, _d, s in card.iter_splits()
                 if "as many outs" in s.text]
        if card.card_type == "pitcher":
            assert texts == [], stem
            continue
        assert len(texts) == 1, stem
        assert texts[0].startswith("lineout"), stem
        assert texts[0].endswith(" into as many outs as possible"), stem
        assert categorize(texts[0]) == "OUT"


def _cells(card):
    return [(c, d, s.lo, s.hi, s.text, s.injury) for c, d, s in card.iter_splits()]


def _assert_same_card(reparsed, card, label=""):
    for attr in ("name", "card_type", "team", "year", "header_lines", "stats"):
        assert getattr(reparsed, attr) == getattr(card, attr), (label, attr)
    assert _cells(reparsed) == _cells(card), label
    assert reparsed.chances() == card.chances(), label


@pytest.mark.parametrize("stem", sorted(REAL_CARDS))
def test_round_trip(stem):
    """parse -> render -> parse must preserve the card semantically."""
    card = REAL_CARDS[stem]
    reparsed = card_text.parse_card(card_text.render_card(card))
    _assert_same_card(reparsed, card, stem)


def test_card_type_comes_from_structure():
    """A rating line naming the pitcher position doesn't make a batting
    card a pitcher card; contradictory structure is an error."""
    bonds = REAL_CARDS["bonds_2001"]
    text = card_text.render_card(bonds).replace(
        "BARRY BONDS\n", "BARRY BONDS\npitcher-1\n", 1)
    assert card_text.parse_card(text).card_type == "batter"
    with pytest.raises(ValueError):
        card_text.parse_card(text.replace("BATTING RECORD", "PITCHING RECORD"))
    seaver = card_text.render_card(REAL_CARDS["seaver_1969"])
    with pytest.raises(ValueError):
        card_text.parse_card(seaver.replace("PITCHING RECORD", "BATTING RECORD"))


# --- generated cards: every export format reads back --------------------------

db = default_db()


def _basic(pid, year, kind):
    if kind == "batter":
        stats = db.batting_season(pid, year)
        league = db.league_batting(year, stats["league"])
        return generate_batter_card(
            stats, league, position_ratings=position_ratings(db, pid, year))[0]
    stats = db.pitching_season(pid, year)
    league = db.league_batting(year, stats["league"])
    return generate_pitcher_card(
        stats, league, fielding_rating=rate_position(db, pid, year, "P") or 3)[0]


def _advanced(pid, year, kind):
    if kind == "batter":
        stats = db.batting_season(pid, year)
        league = db.league_batting(year, stats["league"])
        return generate_advanced_batter_card(
            stats, league, position_ratings=position_ratings(db, pid, year))[0]
    stats = db.pitching_season(pid, year)
    league = db.league_batting(year, stats["league"])
    return generate_advanced_pitcher_card(
        stats, league, fielding_rating=rate_position(db, pid, year, "P") or 3)[0]


def _era_sample(per_decade=2, seed=20260609):
    """A deterministic every-era sample: per decade 1870s-2020s, a few
    substantial batter and pitcher seasons, plus each sampled pitcher's
    batting card that year (pre-DH pitchers' and two-way players'
    batting cards list 'pitcher-N' among their positions)."""
    rng = random.Random(seed)
    want = {(decade, kind): per_decade for decade in range(1870, 2030, 10)
            for kind in ("batter", "pitcher")}
    picked = []
    for _ in range(200_000):
        if not any(want.values()):
            break
        pid, year, kind = db.random_season(rng)
        key = (year // 10 * 10, kind)
        if want.get(key):
            want[key] -= 1
            picked.append((pid, year, kind))
            batting = db.batting_season(pid, year) if kind == "pitcher" else None
            if batting and effective_pa(batting) > 0:
                picked.append((pid, year, "batter"))
    return sorted(set(picked))


ERA_SAMPLE = _era_sample()
NAMED_SEASONS = [
    ("seaveto01", 1969, "batter"),     # a pitcher's batting card
    ("ruthba01", 1918, "batter"),      # two-way: outfield-3, pitcher-1, ...
    ("ohtansh01", 2021, "batter"),
    ("mayswi01", 1965, "batter"),
    ("seaveto01", 1969, "pitcher"),
    ("eckerde01", 1990, "pitcher"),
    ("altroni01", 1919, "pitcher"),    # 0 IP
]


def test_era_sample_is_broad():
    decades = {year // 10 for _pid, year, _kind in ERA_SAMPLE}
    assert len(decades) == 16                         # 1870s-2020s
    two_way = [s for s in ERA_SAMPLE if s[2] == "batter"
               and (s[0], s[1], "pitcher") in ERA_SAMPLE]
    assert two_way


@pytest.mark.parametrize("pid,year,kind", NAMED_SEASONS + ERA_SAMPLE)
def test_generated_card_round_trip(pid, year, kind):
    """generate -> render_card -> parse_card reproduces the card exactly:
    type, header, team, year, stats, every split and injury."""
    card = _basic(pid, year, kind)
    reparsed = card_text.parse_card(card_text.render_card(card))
    assert reparsed.validate() == []
    _assert_same_card(reparsed, card, (pid, year, kind))


ADVANCED_SAMPLE = sorted({(pid, year, kind) for pid, year, kind in ERA_SAMPLE
                          if kind == "pitcher" or (pid, year, "pitcher")
                          not in ERA_SAMPLE})[::2] + [
    ("judgeaa01", 2024, "batter"), ("ohtansh01", 2021, "batter"),
    ("capuach01", 2014, "pitcher")]


@pytest.mark.parametrize("pid,year,kind", ADVANCED_SAMPLE)
def test_generated_advanced_card_round_trips(pid, year, kind, tmp_path):
    """The advanced side reads back from both of its exports: the command-
    line text (render_advanced_card -> parse_advanced_card) and the
    transcription-schema JSON (advanced_card_to_json -> card_json)."""
    card = _advanced(pid, year, kind)

    back = card_text.parse_advanced_card(card_text.render_advanced_card(card))
    assert back.validate() == []
    for attr in ("name", "card_type", "hand", "team", "year", "header_lines"):
        assert getattr(back, attr) == getattr(card, attr), attr
    assert len(back.sides) == len(card.sides)
    for got, side in zip(back.sides, card.sides):
        assert (got.vs, got.percent, got.power) == (side.vs, side.percent, side.power)
        assert got.share == pytest.approx(side.share, abs=1e-12)
        assert _cells(got.card) == _cells(side.card), side.vs

    data = card_json.advanced_card_to_json(card)
    (tmp_path / f"som_{data['cardId']}_6col.json").write_text(
        json.dumps(data), encoding="utf-8")
    loaded = card_json.load_transcriptions(tmp_path)[data["cardId"]]
    assert (loaded.card_type, loaded.name, loaded.year) == (
        card.card_type, card.name, card.year)
    assert loaded.advanced.player["team"] == card.team
    assert loaded.advanced.player["bats" if kind == "batter" else "throws"] == card.hand
    parts = card_json.platoon_cards(loaded)
    assert len(parts) == len(card.sides)
    for (weight, grid), g, side in zip(parts, loaded.advanced.grids, card.sides):
        assert (g["vs"], g["percent"], g.get("power")) == (
            side.vs, side.percent, side.power)
        assert weight == pytest.approx(side.share)
        assert grid.validate() == []
        assert _cells(grid) == _cells(side.card), side.vs


def test_undefined_stat_round_trips():
    """A stat with no defined value (None, e.g. the ERA of a pitcher with
    no outs recorded) prints as '-' and reads back as None."""
    card = _basic("seaveto01", 1969, "pitcher")
    card.stats["ERA"] = None
    text = card_text.render_card(card)
    assert "\nERA               -\n" in text
    assert card_text.parse_card(text).stats == card.stats
