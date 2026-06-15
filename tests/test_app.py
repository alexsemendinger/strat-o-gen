"""Smoke tests for the Flask app (offline, via test client)."""

import pytest

import app as app_module


@pytest.fixture()
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client


def test_index_serves_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Strat-O-Matic Card Maker" in resp.data


def test_search_finds_player(client):
    resp = client.get("/api/search?name=Babe Ruth")
    data = resp.get_json()
    assert resp.status_code == 200
    assert any(p["player_id"] == "ruthba01" for p in data["players"])


def test_search_disambiguates(client):
    resp = client.get("/api/search?name=Ken Griffey")
    data = resp.get_json()
    assert len(data["players"]) >= 2  # Jr. and Sr.


def test_generate_batter_card(client):
    resp = client.post("/api/generate", json={
        "player_id": "ruthba01", "year": 1927, "kind": "batter"})
    data = resp.get_json()
    assert resp.status_code == 200
    assert "som-card" in data["card_html"]
    assert "BABE RUTH" in data["card_html"]
    assert any("IBB" in w for w in data["warnings"])
    assert data["accuracy"]  # comparison table present


def test_generate_pitcher_card(client):
    resp = client.post("/api/generate", json={
        "player_id": "seaveto01", "year": 1969, "kind": "pitcher"})
    data = resp.get_json()
    assert resp.status_code == 200
    assert "PITCHING CARD" in data["card_html"]


def test_generate_wrong_year_offers_valid_years(client):
    resp = client.post("/api/generate", json={
        "player_id": "ruthba01", "year": 1990, "kind": "batter"})
    assert resp.status_code == 404
    data = resp.get_json()
    assert "no batting record" in data["error"]
    assert 1927 in data["years"]  # clickable seasons for the UI
    assert 1990 not in data["years"]


def test_search_includes_years_for_chips(client):
    resp = client.get("/api/search?name=Babe Ruth")
    player = resp.get_json()["players"][0]
    assert 1927 in player["batting_years"]
    assert 1916 in player["pitching_years"]


def test_random_player_always_generates(client):
    """The random picker must only return seasons that generate cleanly."""
    for _ in range(5):
        resp = client.get("/api/random")
        pick = resp.get_json()
        assert resp.status_code == 200
        assert pick["kind"] in ("batter", "pitcher")
        assert (pick["can_bat"] if pick["kind"] == "batter" else pick["can_pitch"])
        gen = client.post("/api/generate", json={
            "player_id": pick["player_id"], "year": pick["year"],
            "kind": pick["kind"]})
        assert gen.status_code == 200, (pick, gen.get_json())
        assert "som-card" in gen.get_json()["card_html"]


def test_generate_tiny_sample_works_with_visible_warning(client):
    """Even a 10-AB cup of coffee makes a card (SOM prints these too —
    see the Bartolo Colon 2016 batting card). The small-sample note goes
    in the warnings panel, never on the card itself."""
    resp = client.post("/api/generate", json={
        "player_id": "ruthba01", "year": 1914, "kind": "batter"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert any("small sample" in w for w in data["warnings"])
    assert "small sample" not in data["card_html"]


def test_colon_2016_batting_card_generates(client):
    """The fixture photo that motivated this: .083, 12 AB, one homer."""
    resp = client.post("/api/generate", json={
        "player_id": "colonba01", "year": 2016, "kind": "batter"})
    assert resp.status_code == 200
    assert "BARTOLO COLON" in resp.get_json()["card_html"]
