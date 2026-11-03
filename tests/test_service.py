"""The product pipeline (stratogen/service.py), stat formatting and the
roster / autocomplete methods in LahmanDB's teams section."""

import time

import pytest

from stratogen import service
from stratogen.lahman import default_db
from stratogen.render import format_average, format_innings, format_stat


@pytest.fixture(scope="module")
def db():
    return default_db()


# --- formatting (W1) ---------------------------------------------------------------

@pytest.mark.parametrize("key,value,text", [
    ("ERA", 0.61, "0.61"), ("ERA", 4.7, "4.70"), ("ERA", 7.0, "7.00"), ("ERA", None, "-"),
    ("BA", 0.0, ".000"), ("BA", 0.356, ".356"), ("BA", 1.0, "1.000"), ("SLG", 2.0, "2.000"),
    ("OBP", 0.4861, ".486"), ("IP", 273.3, "273.1"), ("IP", 273.7, "273.2"),
    ("IP", 0.3, "0.1"), ("IP", 192.0, "192"), ("HR", 60, "60"), ("SO", 89.0, "89"),
])
def test_format_stat(key, value, text):
    assert format_stat(key, value) == text


def test_format_ip_prefers_season_display_and_outs():
    assert format_stat("IP", 273.3, {"IP_display": "273⅓"}) == "273⅓"
    assert format_stat("IP", 273.3, {"IPouts": 820}) == "273.1"
    assert format_innings(None, 821) == "273.2"
    assert format_average(float("nan")) == "-"


# --- warnings -------------------------------------------------------------------------

def test_tidy_warnings_merges_untracked_fields():
    raw = ["IBB not tracked in AL 1911 (treated as 0)",
           "SF not tracked in AL 1911 (treated as 0)",
           "CS not tracked in AL 1911 (treated as 0)",
           "IBB not tracked for this season (treated as 0)",
           "small sample: only 10 effective PA",
           "vs LHP/RHP: walks will run ~3.8/4.7% of PA high: x"]
    out = service.tidy_warnings(raw, "batter", 1911)
    assert out[0] == "Small sample: only 10 plate appearances"
    assert out[1].startswith("Against left-/right-handed pitchers: walks")
    assert out[-1].startswith("Not recorded in 1911: intentional walks, sacrifice flies, "
                              "caught stealing")
    pitcher = service.tidy_warnings(raw[:4], "pitcher", 1911)
    assert pitcher == ["Not recorded in 1911: intentional walks — the card treats it as zero."]


# --- pipeline ---------------------------------------------------------------------------

def test_make_cards_both_sides(db):
    cs = service.make_cards(db, "ruthba01", 1927)
    assert cs.kind == "batter" and cs.kinds == ["batter"]
    assert cs.basic.card_type == cs.advanced.card_type == "batter"
    assert not cs.basic.validate() and not cs.advanced.validate()
    assert "bunting-" in " ".join(cs.advanced.header_lines)     # advanced ratings
    assert cs.basic.header_lines != cs.advanced.header_lines
    rows = dict((r[0], r[1:]) for r in cs.honesty["basic"])
    assert rows["Home runs"] == ("60", "60")
    assert "Hit by pitch" in dict((r[0], r) for r in cs.honesty["advanced"])
    assert service.make_cards(db, "ruthba01", 1927) is cs        # cached


def test_honesty_ba_uses_the_seasons_at_bats(db):
    """G9: hits match exactly, so the average must match too (Gwynn has SF/HBP)."""
    rows = dict((r[0], r[1:]) for r in service.make_cards(db, "gwynnto01", 1994).honesty["basic"])
    assert rows["Hits"][0] == rows["Hits"][1]
    assert rows["Batting average"] == (".394", ".394")


def test_card_data_round_trip_schema(db):
    data = service.make_cards(db, "seaveto01", 1969).card_data()
    assert data["basic"]["statRecord"]["stats"]["ERA"] == "2.21"
    assert data["basic"]["statRecord"]["stats"]["IP"] == "273.1"
    assert [g["vs"] for g in data["advanced"]["grids"]] == ["LHB", "RHB"]
    cells = data["basic"]["grids"][0]["columns"][0]["cells"]
    assert [c["roll"] for c in cells] == list(range(2, 13))


def test_card_errors(db):
    with pytest.raises(service.CardError) as err:
        service.make_cards(db, "riverma01", 1999, "batter")
    assert err.value.other_kind == "pitcher"
    with pytest.raises(service.CardError):
        service.make_cards(db, "ruthba01", 1990)
    with pytest.raises(service.CardError):
        service.make_cards(db, "nobody99", 1927)


# --- roster / autocomplete methods -------------------------------------------------------

def test_primary_role(db):
    assert db.primary_role("ohtansh01", 2022) == "batter"
    assert db.primary_role("ruthba01", 1916) == "pitcher"
    assert db.primary_role("ruthba01", 1927) == "batter"
    assert db.primary_role("riverma01", 1999) == "pitcher"
    assert db.primary_role("ruthba01") == "batter"


def test_playable_years(db):
    assert 1999 not in db.playable_years("riverma01", "batter")
    assert 1999 in db.playable_years("riverma01", "pitcher")


def test_career_summary_from_stats(db):
    trout = db.career_summary("troutmi01")
    assert trout["first_year"] == 2011 and trout["last_year"] >= 2024
    gibson = db.career_summary("gibsojo99") or db.career_summary(
        db.suggest_players("josh gibson")[0]["player_id"])
    assert gibson["first_year"] and gibson["position"] == "C"


def test_suggest_is_fast_and_ranked(db):
    db.suggest_players("warm")
    start = time.perf_counter()
    hits = db.suggest_players("ruth")
    assert time.perf_counter() - start < 0.05
    assert hits[0]["player_id"] == "ruthba01"
    assert [h["player_id"] for h in db.suggest_players("smith")][:1] != ["smith01"]
    assert db.suggest_players("") == [] and db.suggest_players("zzqq") == []


def test_teams_and_roster(db):
    teams = db.teams(1927)
    nya = next(t for t in teams if t["team_id"] == "NYA")
    assert (nya["W"], nya["L"], nya["league"]) == (110, 44, "AL")
    roster = {p["player_id"]: p for p in db.team_roster(1927, "NYA")}
    assert roster["ruthba01"]["batting"]["G"] == 151 and roster["ruthba01"]["pitching"] is None
    assert roster["hoytwa01"]["role"] == "pitcher"
    assert db.team_roster(1927, "XXX") == []
    assert db.team_years()[0] == 1871


def test_traded_player_in_roster(db):
    roster = {p["player_id"]: p for p in db.team_roster(2017, "DET")}
    jd = roster["martijd02"]
    assert [o["team_id"] for o in jd["other_teams"]] == ["ARI"]


# --- team sets -------------------------------------------------------------------------------

def test_team_set_contents_and_speed(db):
    service.team_set(db, 1927, "NYA")                 # warm
    start = time.perf_counter()
    ts = service.team_set(db, 1927, "NYA")
    assert time.perf_counter() - start < 2.0
    assert len(ts.batters) == 14 and len(ts.pitchers) == 9
    assert ts.batters[0].position == "C" and ts.pitchers[0].position == "SP"
    assert {x["name"] for x in ts.left_out} == {"Julie Wera", "Walter Beall"}


def test_team_set_two_way_and_traded(db):
    ts = service.team_set(db, 2022, "LAA")
    ohtani = [(c.cards.kind, c.position) for c in ts.cards if c.cards.player_id == "ohtansh01"]
    assert sorted(ohtani) == [("batter", "DH"), ("pitcher", "SP")]
    traded = [c for c in ts.cards if c.traded_note]
    assert traded and all("full 2022 season" in c.traded_note for c in traded)
    # the card prints the set's team, not the one he played most for
    doc = service.team_document(ts, "basic")
    assert doc.count("Los Angeles Angels of Anaheim</span>") == len(ts.cards)


def test_thresholds_scale_with_schedule():
    assert service.team_thresholds(154) == {"pa": 49, "ip": 20}
    assert service.team_thresholds(30) == {"pa": 10, "ip": 4}
