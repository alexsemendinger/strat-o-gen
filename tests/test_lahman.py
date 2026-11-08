"""Tests for the offline Lahman data layer."""

import csv
import gzip
from pathlib import Path

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


def test_random_season_is_substantial():
    import random as random_module
    from stratogen.simulate import effective_pa
    rng = random_module.Random(7)
    for _ in range(40):
        pid, year, kind = db.random_season(rng)
        if kind == "batter":
            stats = db.batting_season(pid, year)
            assert effective_pa(stats) >= 150, (pid, year)
        else:
            stats = db.pitching_season(pid, year)
            faced = stats["TBF"] or stats["IPouts"] + stats["H"] + stats["BB"]
            assert faced >= 200, (pid, year)


def test_positions():
    # AL/NL outfield corners are split out from 1954 (FieldingOFsplit)
    pos = db.positions("mayswi01", 1965)
    assert pos[0][0] == "CF"
    # before that the corners come from Appearances (games by spot), so
    # Ruth 1927 reads right field first, then left
    assert db.positions("ruthba01", 1927) == [("RF", 94), ("LF", 56)]
    # Appearances reaches back to the 1870s too
    pos_1875 = dict(db.positions("orourji01", 1875))
    assert pos_1875["CF"] == 44 and "OF" not in pos_1875


# --- handedness (platoon matchup frequencies) ---------------------------------

def test_league_handedness_shares():
    """Built in the same load pass as the batting/pitching indexes."""
    h = db.league_handedness(2003, "AL")
    assert h["pitchers"]["L"] == pytest.approx(0.292, abs=0.005)
    assert sum(h["pitchers"].values()) == pytest.approx(1.0)
    assert sum(h["batters"].values()) == pytest.approx(1.0)
    assert 0.15 < h["batters"]["S"] < 0.22   # the switch-hitting 2000s
    assert h["pitcher_coverage"] == 1.0 and h["batter_coverage"] == 1.0


def test_league_handedness_unknown_hands_and_eras():
    # 19th-century hands are partly unknown: excluded, coverage reported
    early = db.league_handedness(1884, "UA")
    assert 0.5 < early["batter_coverage"] < 0.9
    assert sum(early["batters"].values()) == pytest.approx(1.0)
    # the 1876 NL had no left-handed pitching at all
    assert db.league_handedness(1876, "NL")["pitchers"]["L"] == 0.0
    # Negro leagues are covered too
    assert db.league_handedness(1943, "NN2")["pitchers"]
    with pytest.raises(KeyError):
        db.league_handedness(1927, "XX")


def test_league_batter_lines_and_schedule():
    lines = db.league_batter_lines(2001, "NL")
    bonds = [ln for ln in lines if ln[3] == 73]
    assert len(bonds) == 1 and bonds[0][0] == "L"
    assert bonds[0][2] == 476 + 177 - 35 + 9 + 2   # AB + BB - IBB + HBP + SF
    assert all(ln[1] > 0 for ln in lines)
    assert db.league_games_per_team(2001, "NL") == pytest.approx(162, abs=1)
    assert db.league_games_per_team(1906, "AL") == pytest.approx(152, abs=4)


# --- files ----------------------------------------------------------------------

_MINI = {
    "People": "playerID,nameFirst,nameLast,bats,throws,debut,finalGame\n"
              "testpl01,Test,Player,R,R,1960-04-01,1961-09-30\n",
    "Batting": "playerID,yearID,stint,teamID,lgID,G,AB,R,H,2B,3B,HR,RBI,SB,CS,"
               "BB,SO,IBB,HBP,SH,SF,GIDP\n"
               "testpl01,1960,1,NYA,AL,100,400,50,110,20,3,10,60,5,2,40,60,2,3,4,5,9\n",
    "Pitching": "playerID,yearID,stint,teamID,lgID,W,L,G,GS,IPouts,H,ER,BB,SO,BFP\n",
    "Fielding": "playerID,yearID,stint,teamID,lgID,POS,G,GS,InnOuts,PO,A,E,DP,PB,SB,CS\n"
                "testpl01,1960,1,NYA,AL,OF,95,90,,200,8,3,1,,,\n",
    "FieldingOFsplit": "playerID,yearID,stint,teamID,lgID,POS,G,GS,InnOuts,PO,A,E\n",
    "Teams": "yearID,lgID,teamID,name,G,R\n1960,AL,NYA,New York Yankees,154,746\n",
    "Appearances": "yearID,teamID,lgID,playerID,G_all,G_lf,G_cf,G_rf,G_dh\n"
                   "1960,NYA,AL,testpl01,100,20,70,5,0\n",
}


def test_plain_csv_release_files_load(tmp_path):
    """A new season's plain .csv files work without gzipping, and win over
    an older bundled .csv.gz; Appearances (optional) splits a combined
    outfield into corners."""
    import gzip
    import os
    from stratogen.lahman import LahmanDB
    for table, text in _MINI.items():
        (tmp_path / f"{table}.csv").write_text(text, encoding="utf-8")
    stale = tmp_path / "Batting.csv.gz"
    with gzip.open(stale, "wt", encoding="utf-8") as fh:
        fh.write(_MINI["Batting"].replace(",10,60,", ",99,60,"))
    os.utime(stale, (1, 1))   # older than the plain file
    mini = LahmanDB(tmp_path)
    assert mini.table_path("Batting").name == "Batting.csv"
    assert mini.batting_season("testpl01", 1960)["HR"] == 10
    assert mini.batting_years("testpl01") == [1960]
    assert [p for p, _g in mini.positions("testpl01", 1960)] == ["CF", "LF", "RF"]


def test_reads_skip_the_lock_once_loaded():
    """A search during warm() mustn't queue behind the Fielding load."""
    class NoLock:
        def __enter__(self):
            raise AssertionError("lock taken after load")

        def __exit__(self, *exc):
            return False

    db.warm()
    db.search_players("Mays")
    db.season_pitchers(1965)
    saved, db._lock = db._lock, NoLock()
    try:
        assert db.search_players("Willie Mays")[0].player_id == "mayswi01"
        assert db.batting_season("mayswi01", 1965)["HR"] == 52
        assert db.fielding_by_position("mayswi01", 1965)
        db.league_batting(1965, "NL")
    finally:
        db._lock = saved


# --- pitching lines: innings, ERA, batters faced --------------------------------

def test_innings_pitched_exact_with_baseball_display():
    s = db.pitching_season("seaveto01", 1969)
    assert s["IPouts"] == 820
    assert s["IP"] * 3 == pytest.approx(820)            # exact, for math
    assert str(s["IP"]) == s["IP_display"] == "273.1"   # 273 1/3 innings
    assert f"{s['IP']}" == "273.1"
    assert s["ERA"] == 2.21


def test_era_from_outs_not_rounded_innings():
    assert db.pitching_season("pritcwi01", 1930)["ERA"] == 29.61   # was 29.71
    # runs without recording an out: undefined, not 0
    assert db.pitching_season("bruckfr01", 1961)["ERA"] is None


def test_partial_batters_faced_treated_as_missing():
    """1925 NNL: Cliff Bell's BFP is 22 for 100 innings — a partial count
    that left his card without outs. It's estimated instead."""
    from stratogen.generate import pitcher_chance_targets
    from stratogen.model import OUT
    s = db.pitching_season("bellcl01", 1925)
    assert s["TBF"] == 0 and "TBF" in s["missing"]
    targets, warnings = pitcher_chance_targets(s, db.league_batting(1925, "NNL"))
    assert targets[OUT] > 30      # an ordinary out total, not the old 0
    assert any("estimated" in w for w in warnings)
    # a legitimate one-batter double play line is left alone
    assert db.pitching_season("hudsoha01", 1953)["TBF"] == 1


# --- league baselines -------------------------------------------------------------

def test_league_strikeouts_from_pitching_when_batting_untracked():
    """AA/UA batting SO is blank and Negro-league batting SO mostly zero:
    the league K rate comes from pitching strikeouts instead of ~0."""
    from stratogen.generate import pitcher_chance_targets
    from stratogen.model import SO
    aa = db.league_batting(1884, "AA")
    assert aa["K_per_PA"] == pytest.approx(0.117, abs=0.002)
    assert aa["batter_so_unrecorded"] and aa["raw"]["SO_batting"] == 0
    assert any("pitchers' totals" in w for w in aa["warnings"])
    assert db.league_batting(1943, "NN2")["K_per_PA"] == pytest.approx(0.113, abs=0.002)
    # MLB keeps the batting totals
    al = db.league_batting(2001, "AL")
    assert not al["batter_so_unrecorded"] and "SO_batting" not in al["raw"]
    # Satchel Paige 1934: ~45 strikeout chances, not 58
    paige = db.pitching_season("paigesa01", 1934)
    targets, _w = pitcher_chance_targets(paige, db.league_batting(1934, "NN2"))
    assert targets[SO] == pytest.approx(45, abs=2)
    # the batter's own zero-filled SO is flagged as not recorded
    assert "SO" in db.batting_season("gibsojo99", 1943)["missing"]
    assert "SO" not in db.batting_season("bondsba01", 2001)["missing"]


def test_tracking_decided_by_coverage():
    """A stat counts as tracked when rows carrying it hold half the PA —
    zeros on a few 0-AB rows used to mute the 1912-54 IBB/SF notes."""
    warnings = db.league_batting(1927, "AL")["warnings"]
    assert any(w.startswith("IBB not tracked") for w in warnings)
    assert any(w.startswith("SF not tracked") for w in warnings)
    # stolen bases weren't recorded in the 1876 NL
    assert any(w.startswith("SB not tracked") for w in
               db.league_batting(1876, "NL")["warnings"])


def test_tiny_leagues_pool_a_baseline():
    ind = db.league_batting(1894, "IND")      # 42 PA of independent clubs
    assert ind["PA_eff"] >= 5000 and ind["pooled_from"]
    assert "too small" in ind["warnings"][0]
    assert db.league_batting(1933, "NN2")["pooled_from"] == []


# --- multi-team seasons -----------------------------------------------------------

def test_traded_player_labelled_with_final_team():
    capuano = db.pitching_season("capuach01", 2014)    # BOS -> NYA
    assert capuano["team"] == "New York Yankees"
    assert capuano["teams"] == ["Boston Red Sox", "New York Yankees"]


def test_primary_league_by_work_and_blended_baseline():
    """Sabathia 2008: 18 games for CLE but more batters faced for MIL."""
    s = db.pitching_season("sabatcc01", 2008)
    assert s["league"] == "NL" and s["team"] == "Milwaukee Brewers"
    assert s["league_weights"] == {"AL": 507, "NL": 516}
    blend = db.season_league(s)
    al, nl = db.league_batting(2008, "AL"), db.league_batting(2008, "NL")
    assert al["K_per_PA"] < blend["K_per_PA"] < nl["K_per_PA"]
    assert blend["league"] == "NL" and set(blend["blend"]) == {"AL", "NL"}
    assert blend["raw"]["SO"] / blend["PA_eff"] == pytest.approx(blend["K_per_PA"])
    # one league: exactly league_batting
    bonds = db.batting_season("bondsba01", 2001)
    assert db.season_league(bonds) is db.league_batting(2001, "NL")


# --- card-ready seasons -------------------------------------------------------------

def test_year_lists_only_offer_seasons_that_make_cards():
    from stratogen.simulate import effective_pa
    years = db.batting_years("riverma01")
    assert years == [2006, 2009, 2010]          # 19 seasons have a row
    assert all(effective_pa(db.batting_season("riverma01", y)) > 0 for y in years)
    assert len(db.pitching_years("riverma01")) == 19
    assert db.pitching_years("yountla01") == []   # 1971: no batter faced
    assert db.pitching_season("yountla01", 1971) is not None


# --- search -------------------------------------------------------------------------

@pytest.mark.parametrize("query,pid", [
    ("Ken Griffey Jr.", "griffke02"), ("Ken Griffey Jr", "griffke02"),
    ("Cal Ripken Jr.", "ripkeca01"), ("Fernando Tatis Jr.", "tatisfe02"),
    ("Vladimir Guerrero Jr.", "guerrvl02"), ("Ronald Acuna Jr.", "acunaro01"),
    ("AJ Pierzynski", "pierzaj01"), ("A.J. Pierzynski", "pierzaj01"),
    ("JD Drew", "drewjd01"), ("J.D. Martinez", "martijd02"),
    ("C.C. Sabathia", "sabatcc01"), ("RA Dickey", "dickera01"),
    ("Paul ONeill", "oneilpa01"), ("Paul O’Neill", "oneilpa01"),
    ("Paul O'Neill", "oneilpa01"), ("Mays Willie", "mayswi01"),
    ("Mays, Willie", "mayswi01"), ("pierz", "pierzaj01"),
])
def test_search_forgives_suffixes_initials_and_quotes(query, pid):
    assert pid in [h.player_id for h in db.search_players(query)], query


def test_search_ranks_before_truncating():
    """Every match is scored first: famous players of common names surface."""
    griffey = db.search_players("Ken Griffey")
    assert [h.player_id for h in griffey] == ["griffke02", "griffke01"]
    assert db.search_players("Pedro Martinez")[0].player_id == "martipe02"
    assert db.search_players("Willie")[0].player_id == "mayswi01"
    for query, pid in (("Smith", "smithoz01"), ("Johnson", "johnswa01"),
                       ("Johnson", "johnsra05"), ("Williams", "willite01"),
                       ("Bell", "bellco99")):
        hits = db.search_players(query)
        assert pid in [h.player_id for h in hits[:10]], (query, pid)
    smith = db.search_players("Smith")
    assert len(smith) == 25 and smith.total > 200


def test_search_year_and_kind_filters_apply_before_the_limit():
    smiths = db.search_players("Smith", year=1990)    # 12 Smiths played
    assert smiths.total >= 12
    assert all(1990 in h.batting_years + h.pitching_years for h in smiths)
    batters = db.search_players("Smith", year=1990, kind="batter")
    assert all(1990 in h.batting_years for h in batters)
    assert batters[0].player_id == "smithoz01" and batters.total < smiths.total
    assert db.search_players("Frank Thomas", year=2000)[0].player_id == "thomafr04"
    johnson = db.search_players("Johnson", year=1995, kind="pitcher")
    assert "johnsra05" in [h.player_id for h in johnson]


# --- league totals API (game engine, advanced ratings) -----------------------------

def _direct_league_sums():
    """{(year, lg): {prefix_field: (sum, rows with a value, rows)}} straight
    from the Teams / Pitching / catchers' Fielding CSVs."""
    lahman = Path(__file__).resolve().parent.parent / "data" / "lahman"
    acc = {}
    for table, prefix, fields, keep in (
            ("Teams", "T_", ("G", "R", "IPouts", "SB", "CS", "HBP", "E", "DP", "SF"), None),
            ("Pitching", "P_", ("IPouts", "WP", "BK", "HBP", "IBB", "SH", "GIDP"), None),
            ("Fielding", "F_", ("PB",), "C")):
        with gzip.open(lahman / f"{table}.csv.gz", "rt", encoding="utf-8-sig",
                       newline="") as fh:
            reader = csv.reader(fh)
            idx = {h: i for i, h in enumerate(next(reader))}
            for row in reader:
                if keep is not None and row[idx["POS"]] != keep:
                    continue
                key = (int(row[idx["yearID"]]), row[idx["lgID"]])
                for f in fields:
                    slot = acc.setdefault(key, {}).setdefault(prefix + f, [0, 0, 0])
                    slot[2] += 1
                    value = row[idx[f]].strip()
                    if value:
                        slot[0] += int(float(value))
                        slot[1] += 1
    return acc


def test_league_totals_match_a_direct_read_of_the_csvs():
    """Teams / Pitching / catchers' Fielding totals equal per-row sums read
    straight from the CSVs."""
    checked = 0
    for (year, lg), slots in _direct_league_sums().items():
        for name, slot in slots.items():
            prefix, field = name.split("_", 1)
            if prefix == "T":
                got = db.league_team_totals(year, lg)[field]
            elif prefix == "P":
                got = db.league_pitching_totals(year, lg)[field]
            else:
                got = db.league_fielding_totals(year, lg, "C")[field]
            assert tuple(got) == tuple(slot), (name, year, lg)
            checked += 1
    assert checked > 5000
    t = db.league_team_totals(1975, "NL")
    assert t["G"].complete and t["CS"].coverage == 1.0
    with pytest.raises(KeyError):
        db.league_team_totals(1927, "XX")


def test_league_pitching_usage_and_season_pitchers():
    use = db.league_pitching_usage(2001, "AL")
    assert use["GS"] == pytest.approx(14 * 162, abs=10)
    assert 0 < use["relief_IPouts"] < use["IPouts"]
    assert db.season_pitchers(2001)["mendora01"] == 56
