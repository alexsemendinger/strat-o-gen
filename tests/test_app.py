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


def test_generate_wrong_year_is_friendly(client):
    resp = client.post("/api/generate", json={
        "player_id": "ruthba01", "year": 1990, "kind": "batter"})
    assert resp.status_code == 404
    assert "no batting record" in resp.get_json()["error"]


def test_generate_tiny_sample_rejected(client):
    # Ruth's final season fragment: 1935, 92 PA — generates with warning;
    # use a sub-50-PA season instead: his 1914 cup of coffee (10 AB).
    resp = client.post("/api/generate", json={
        "player_id": "ruthba01", "year": 1914, "kind": "batter"})
    assert resp.status_code == 400
    assert "not enough" in resp.get_json()["error"]
