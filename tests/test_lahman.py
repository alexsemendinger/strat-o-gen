"""Tests for the offline Lahman data layer."""

import pytest

from stratogen.lahman import default_db

db = default_db()


def test_search_exact_name():
    hits = db.search_players("Babe Ruth")
    assert any(h.player_id == "ruthba01" for h in hits)


def test_search_is_accent_and_case_insensitive():
    assert any(h.player_id == "beltrad01" for h in db.search_players("adrian beltre"))
    assert any(h.player_id == "bondsba01" for h in db.search_players("BARRY BONDS"))


def test_batting_season_bonds_2001():
    stats = db.batting_season("bondsba01", 2001)
    assert stats["AB"] == 476
    assert stats["HR"] == 73
    assert stats["BB"] == 177
    assert stats["IBB"] == 35
    assert stats["league"] == "NL"
    assert stats["missing"] == []


def test_batting_season_ruth_1927_missing_fields():
    stats = db.batting_season("ruthba01", 1927)
    assert stats["HR"] == 60
    assert "IBB" in stats["missing"]
    assert "SF" in stats["missing"]


def test_multi_team_season_aggregates():
    # George Foster 1971: SFN + CIN
    stats = db.batting_season("fostege01", 1971)
    assert stats["multi_team"]
    assert stats["HR"] == 13
    assert stats["SO"] == 120
    assert set(stats["team_ids"]) == {"SFN", "CIN"}


def test_pitching_season_ryan_1972():
    stats = db.pitching_season("ryanno01", 1972)
    assert stats["SO"] == 329
    assert stats["BB"] == 157
    assert stats["H"] == 166
    assert stats["TBF"] > 1000
    assert stats["league"] == "AL"


def test_no_data_returns_none():
    assert db.batting_season("ruthba01", 1936) is None
    assert db.pitching_season("bondsba01", 2001) is None


def test_league_batting_modern():
    nl2001 = db.league_batting(2001, "NL")
    assert 0.255 < nl2001["BA"] < 0.270
    assert 0.025 < nl2001["HR_per_PA"] < 0.035
    assert nl2001["warnings"] == []


def test_league_batting_all_eras():
    """League averages must exist for every era, back to the 19th century."""
    for year, league in [(1871, "NA"), (1901, "AL"), (1927, "AL"), (1942, "NN2"),
                         (1968, "NL"), (1987, "AL"), (2024, "NL"), (2025, "AL")]:
        avg = db.league_batting(year, league)
        assert 0.18 < avg["BA"] < 0.36, (year, league, avg["BA"])
        assert avg["PA_eff"] > 0


def test_league_batting_era_differences():
    """Sanity: known historical shifts must appear in the data."""
    al1968 = db.league_batting(1968, "AL")   # year of the pitcher
    al2019 = db.league_batting(2019, "AL")   # juiced ball
    assert al1968["BA"] < 0.245
    assert al2019["HR_per_PA"] > 1.8 * al1968["HR_per_PA"]
    al1927 = db.league_batting(1927, "AL")
    assert al1927["K_per_PA"] < 0.10  # contact era


def test_unknown_league_raises():
    with pytest.raises(KeyError):
        db.league_batting(1927, "XX")


def test_positions():
    # outfield corners are split out (FieldingOFsplit covers 1891+)
    pos = db.positions("mayswi01", 1965)
    assert pos[0][0] == "CF"
    # pre-1891 only the combined OF exists
    pos_1875 = db.positions("orourji01", 1875)
    assert any(p == "OF" for p, _ in pos_1875)
