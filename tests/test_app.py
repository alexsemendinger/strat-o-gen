"""Tests for the Flask app (offline, via test client)."""

import random

import pytest

import app as app_module


@pytest.fixture()
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client


def _gen(client, **body):
    return client.post("/api/generate", json=body)


# --- pages and health ----------------------------------------------------------

def test_index_serves_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Strat-O-Matic Card Maker" in resp.data
    assert b'role="combobox"' in resp.data          # name autocomplete
    assert b"/static/app.js" in resp.data


def test_static_and_card_css(client):
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200
    css = client.get("/card.css")
    assert css.status_code == 200 and css.mimetype == "text/css"
    assert b"2.6in" in css.data and b"print-color-adjust" in css.data
    assert b"scale(0.6)" not in css.data


def test_health(client):
    data = client.get("/api/health").get_json()
    assert data["app"] == "strat-o-gen" and data["ok"] is True
    assert "ready" in data


# --- errors are JSON -----------------------------------------------------------

def test_404_and_405_are_json(client):
    resp = client.get("/no/such/page")
    assert resp.status_code == 404 and resp.is_json and resp.get_json()["error"]
    resp = client.get("/api/generate")
    assert resp.status_code == 405 and resp.is_json and resp.get_json()["error"]


def test_500_is_json(client, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(app_module.service, "make_cards", boom)
    resp = _gen(client, player_id="ruthba01", year=1927)
    assert resp.status_code == 500 and resp.is_json
    assert "RuntimeError" in resp.get_json()["error"]


@pytest.mark.parametrize("body,status", [
    ({"player_id": ["x"], "year": 1927}, 404),          # non-string id
    ({"player_id": "nobody99", "year": 1927}, 404),     # unknown player
    ({"player_id": "ruthba01", "year": True}, 400),     # bool is not a year
    ({"player_id": "ruthba01", "year": 1927.5}, 400),
    ({"player_id": "ruthba01", "year": "abc"}, 400),
    ({"player_id": "ruthba01", "year": 1700}, 400),     # out of range
    ({"player_id": "ruthba01"}, 400),                   # missing year
    ({"player_id": "ruthba01", "year": 1927, "kind": "catcher"}, 400),
])
def test_generate_validation(client, body, status):
    resp = _gen(client, **body)
    assert resp.status_code == status and resp.is_json
    assert resp.get_json()["error"]


def test_generate_rejects_non_json(client):
    resp = client.post("/api/generate", data="year=1927")
    assert resp.status_code == 400 and resp.is_json


def test_generate_accepts_numeric_string_year(client):
    assert _gen(client, player_id="ruthba01", year="1927").status_code == 200


# --- search / suggest / random ----------------------------------------------------

def test_search_finds_player(client):
    resp = client.get("/api/search?name=Babe Ruth")
    data = resp.get_json()
    assert resp.status_code == 200
    assert any(p["player_id"] == "ruthba01" for p in data["players"])


def test_search_disambiguates(client):
    resp = client.get("/api/search?name=Ken Griffey")
    assert len(resp.get_json()["players"]) >= 2  # Jr. and Sr.


def test_search_requires_name(client):
    resp = client.get("/api/search?name=")
    assert resp.status_code == 400 and resp.is_json


def test_search_includes_years_and_span(client):
    player = next(p for p in client.get("/api/search?name=Babe Ruth").get_json()["players"]
                  if p["player_id"] == "ruthba01")
    assert 1927 in player["batting_years"]
    assert 1916 in player["pitching_years"]
    assert player["span"] == "1914–1935"
    assert player["primary"] == "batter"


def test_search_span_for_active_and_negro_league_players(client):
    """W13: spans come from the stats, never 'None' or blank."""
    for name in ("Mike Trout", "Josh Gibson"):
        players = client.get(f"/api/search?name={name}").get_json()["players"]
        assert players and all("None" not in p["meta"] for p in players)
        assert all(p["span"] for p in players)


def test_search_year_marks_matching_player(client):
    players = client.get("/api/search?name=Frank Thomas&year=2000").get_json()["players"]
    assert players[0]["has_year"] and players[0]["player_id"] == "thomafr04"
    assert sum(p["has_year"] for p in players) == 1


def test_offered_years_only_playable(client):
    """W3: Rivera's batting years are only seasons that make a card."""
    rivera = next(p for p in client.get("/api/search?name=Mariano Rivera").get_json()["players"]
                  if p["player_id"] == "riverma01")
    assert rivera["primary"] == "pitcher"
    for year in rivera["batting_years"]:
        assert _gen(client, player_id="riverma01", year=year, kind="batter").status_code == 200


def test_suggest(client):
    data = client.get("/api/suggest?q=babe ru").get_json()
    assert data["players"][0]["player_id"] == "ruthba01"
    assert data["players"][0]["span"] == "1914–1935"
    assert len(client.get("/api/suggest?q=smith").get_json()["players"]) == 8
    assert client.get("/api/suggest?q=").get_json() == {"players": []}
    assert client.get("/api/suggest?q=zzzzqqq").get_json() == {"players": []}


def test_suggest_handles_initials_suffixes_and_apostrophes(client):
    def top(q):
        return client.get("/api/suggest", query_string={"q": q}).get_json()["players"][0]["name"]
    assert top("A.J. Pierz") == "A. J. Pierzynski"
    assert top("Ken Griffey Jr.").startswith("Ken Griffey")
    assert top("Paul O’Neill") == "Paul O'Neill"
    assert top("mays w") == "Willie Mays"


def test_random_player_always_generates(client):
    random.seed(9)
    for _ in range(5):
        resp = client.get("/api/random")
        pick = resp.get_json()
        assert resp.status_code == 200
        assert pick["kind"] in ("batter", "pitcher")
        years = pick["batting_years"] if pick["kind"] == "batter" else pick["pitching_years"]
        assert pick["year"] in years
        gen = _gen(client, player_id=pick["player_id"], year=pick["year"], kind=pick["kind"])
        assert gen.status_code == 200, (pick, gen.get_json())
        assert "som-card" in gen.get_json()["card_html"]


# --- generating cards ----------------------------------------------------------------

def test_generate_batter_card(client):
    resp = _gen(client, player_id="ruthba01", year=1927, kind="batter")
    data = resp.get_json()
    assert resp.status_code == 200
    assert "som-card" in data["card_html"] and "BABE RUTH" in data["card_html"]
    assert "intentional walks" in " ".join(data["warnings"])
    assert data["accuracy"]  # comparison table present
    assert dict((r[0], r[1:]) for r in data["accuracy"])["Batting average"] == [".356", ".356"]


def test_generate_has_advanced_side(client):
    data = _gen(client, player_id="ruthba01", year=1927).get_json()
    adv = data["advanced_html"]
    assert "AGAINST LEFT-HANDED PITCHERS" in adv and "AGAINST RIGHT-HANDED PITCHERS" in adv
    assert "Power-" in adv
    assert "bunting-" in adv and "hit &amp; run-" in adv   # advanced header ratings
    labels = [r[0] for r in data["honesty"]["advanced"]]
    assert "Hit by pitch" in labels
    assert data["advanced_explainer"] and data["honesty_notes"]["advanced"]


def test_warnings_are_deduplicated(client):
    data = _gen(client, player_id="cobbty01", year=1911).get_json()
    assert len(data["warnings"]) == len(set(data["warnings"]))
    assert sum("Not recorded" in w for w in data["warnings"]) == 1
    assert not any("not tracked in" in w for w in data["warnings"])


def test_generate_pitcher_card(client):
    resp = _gen(client, player_id="seaveto01", year=1969, kind="pitcher")
    data = resp.get_json()
    assert resp.status_code == 200
    assert "PITCHING CARD" in data["card_html"]
    assert "273.1" in data["card_html"]                   # IP notation
    assert "AGAINST LEFT-HANDED BATTERS" in data["advanced_html"]
    assert "Walks (non-intentional)" in [r[0] for r in data["accuracy"]]


@pytest.mark.parametrize("pid,year", [("martipe02", 2000), ("ryanno01", 1972),
                                      ("riverma01", 1999)])
def test_pitchers_default_to_pitcher_card(client, pid, year):
    """W2: no kind given -> his main role that season."""
    data = _gen(client, player_id=pid, year=year).get_json()
    assert data["kind"] == "pitcher", data


def test_two_way_player_offers_both(client):
    data = _gen(client, player_id="ohtansh01", year=2022).get_json()
    assert data["kind"] == "batter" and data["kinds"] == ["batter", "pitcher"]
    data = _gen(client, player_id="ohtansh01", year=2022, kind="pitcher").get_json()
    assert data["kind"] == "pitcher"


def test_generate_wrong_year_offers_valid_years(client):
    resp = _gen(client, player_id="ruthba01", year=1990, kind="batter")
    assert resp.status_code == 404
    data = resp.get_json()
    assert "no batter card for 1990" in data["error"]
    assert 1927 in data["years"]  # clickable seasons for the UI
    assert 1990 not in data["years"]


def test_generate_wrong_kind_suggests_other(client):
    resp = _gen(client, player_id="riverma01", year=1999, kind="batter")
    assert resp.status_code == 404
    data = resp.get_json()
    assert "didn't bat in 1999" in data["error"] and data["other_kind"] == "pitcher"


def test_generate_tiny_sample_works_with_visible_warning(client):
    """Even a 10-AB cup of coffee makes a card (SOM prints these too)."""
    data = _gen(client, player_id="ruthba01", year=1914, kind="batter").get_json()
    assert any("small sample" in w.lower() for w in data["warnings"])
    assert "small sample" not in data["card_html"].lower()


def test_colon_2016_batting_card_generates(client):
    resp = _gen(client, player_id="colonba01", year=2016, kind="batter")
    assert resp.status_code == 200
    assert "BARTOLO COLON" in resp.get_json()["card_html"]


def test_multi_team_season_is_labeled(client):
    data = _gen(client, player_id="martijd02", year=2017).get_json()
    assert len(data["teams"]) == 2 and "full-season" in data["team_note"]


# --- downloads ---------------------------------------------------------------------

def test_download_card_html_and_json(client):
    resp = client.get("/download/card?player_id=ruthba01&year=1927&kind=batter&format=html")
    assert resp.status_code == 200 and "attachment" in resp.headers["Content-Disposition"]
    assert b"<title>Babe Ruth 1927 batter card</title>" in resp.data
    assert b"som-advanced" in resp.data
    resp = client.get("/download/card?player_id=ruthba01&year=1927&kind=batter&format=json")
    data = resp.get_json()
    assert data["basic"]["side"] == "3col" and data["advanced"]["side"] == "6col"
    assert data["basic"]["statRecord"]["stats"]["AVG"] == ".356"
    assert client.get("/download/card?player_id=ruthba01&year=1927&format=pdf").status_code == 400


# --- teams -------------------------------------------------------------------------

def test_teams(client):
    data = client.get("/api/teams?year=1927").get_json()
    al = next(lg for lg in data["leagues"] if lg["league"] == "AL")
    nya = next(t for t in al["teams"] if t["team_id"] == "NYA")
    assert (nya["name"], nya["W"], nya["L"]) == ("New York Yankees", 110, 44)
    assert al["teams"][0]["team_id"] == "NYA"   # standings order
    assert client.get("/api/teams?year=").status_code == 400


def test_team_set(client):
    data = client.get("/api/team?year=1927&team=NYA").get_json()
    names = {(c["name"], c["kind"]) for c in data["cards"]}
    assert ("Babe Ruth", "batter") in names and ("Waite Hoyt", "pitcher") in names
    assert all("som-basic" in c["card_html"] and "som-advanced" in c["advanced_html"]
               for c in data["cards"])
    assert {x["name"] for x in data["left_out"]} >= {"Julie Wera"}
    assert all(x["reason"] for x in data["left_out"])
    assert data["downloads"]["both"].startswith("/download/team")


def test_team_set_errors(client):
    assert client.get("/api/team?year=1927&team=XXX").status_code == 404
    assert client.get("/api/team?year=1927&team=<b>").status_code == 404
    assert client.get("/api/team?year=1927").status_code == 400


def test_team_download_sheet(client):
    resp = client.get("/download/team?year=1927&team=NYA&sides=basic")
    assert resp.status_code == 200
    assert resp.data.count(b'class="sheet-page sheet-basic"') == 6   # 23 cards, 4/page
    assert b'class="sheet-page sheet-advanced"' not in resp.data
    assert client.get("/download/team?year=1927&team=NYA&sides=x").status_code == 400


def test_print_fit_script_is_served_and_embedded(client):
    """Cards are fitted to the real 4.1in height when printed: the app
    serves the fit script and saved documents embed it."""
    resp = client.get("/card-fit.js")
    assert resp.status_code == 200 and b"somFitCards" in resp.data
    assert b"card-fit.js" in client.get("/").data
    doc = client.get("/download/card?player_id=linzph01&year=1963&kind=batter"
                     "&format=html&sides=basic")
    assert doc.status_code == 200
    assert b"somFitCards(document)" in doc.data
    assert b"var(--som-fit, 1)" in doc.data


def test_basic_header_runs_positions_together(client):
    """A utility man's positions share one wrapping line on the card
    (six stacked lines would push it past real card height)."""
    data = client.post("/api/generate", json={
        "player_id": "linzph01", "year": 1963, "kind": "batter"}).get_json()
    assert "shortstop-3, 3rd base-3, 2nd base-3" in data["card_html"]
