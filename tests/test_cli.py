"""Command-line interface (generate_card.main)."""

import json

import generate_card


def run(capsys, *argv):
    rc = generate_card.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_basic_batter_card(capsys):
    rc, out, _ = run(capsys, "Willie Mays", "1965")
    assert rc == 0
    assert "WILLIE MAYS" in out and "1965 BATTING RECORD" in out
    assert "AVG               .317" in out and "Batting average" in out


def test_pitcher_defaults_to_pitcher_card_with_formatted_record(capsys):
    rc, out, _ = run(capsys, "Tom Seaver", "1969")
    assert rc == 0 and "PITCHING CARD" in out
    assert "ERA               2.21" in out and "IP                273.1" in out


def test_no_traceback_for_wrong_kind(capsys):
    rc, _, err = run(capsys, "Mariano Rivera", "1999", "--batter")
    assert rc == 1 and "didn't bat in 1999" in err and "--pitcher" in err


def test_empty_name_rejected(capsys):
    rc, _, err = run(capsys, "", "1969")
    assert rc == 1 and "player name" in err


def test_ambiguous_name_lists_ids(capsys):
    rc, _, err = run(capsys, "Frank Thomas")
    assert rc == 1
    assert "thomafr03" in err and "thomafr04" in err and "--id" in err


def test_year_picks_the_only_match(capsys):
    rc, out, _ = run(capsys, "Frank Thomas", "2000")
    assert rc == 0 and "Chicago White Sox" in out


def test_id_flag(capsys):
    rc, out, _ = run(capsys, "--id", "thomafr03", "1960")
    assert rc == 0 and "Chicago Cubs" in out
    rc, _, err = run(capsys, "--id", "nobody99", "1960")
    assert rc == 1 and "No player with ID" in err


def test_seasons_listing_without_year(capsys):
    rc, out, _ = run(capsys, "--id", "ruthba01")
    assert rc == 0 and "1927" in out and "pitching seasons" in out


def test_advanced_json_and_html(capsys, tmp_path):
    js, page = tmp_path / "judge.json", tmp_path / "judge.html"
    rc, out, _ = run(capsys, "Aaron Judge", "2024", "--advanced",
                     "--json", str(js), "--html", str(page))
    assert rc == 0 and "vs LHP" in out and "Hit by pitch" in out
    assert json.loads(js.read_text(encoding="utf-8"))["side"] == "6col"
    html = page.read_text(encoding="utf-8")
    assert "<title>Aaron Judge 2024 batter card</title>" in html and "som-advanced" in html


def test_unwritable_html_path(capsys, tmp_path):
    rc, _, err = run(capsys, "Willie Mays", "1965", "--html", str(tmp_path / "no" / "x.html"))
    assert rc == 1 and "Could not write" in err


def test_team_sheet(capsys, tmp_path):
    path = tmp_path / "nya.html"
    rc, out, _ = run(capsys, "--team", "NYA", "--year", "1927", "--html", str(path))
    assert rc == 0 and "Babe Ruth" in out and "Left out" in out
    html = path.read_text(encoding="utf-8")
    assert html.count('class="sheet-page sheet-basic"') == 6
    assert html.count('class="sheet-page sheet-advanced"') == 12


def test_team_errors(capsys):
    rc, _, err = run(capsys, "--team", "XXX", "--year", "1927")
    assert rc == 1 and "NYA" in err
    rc, _, err = run(capsys, "--team", "NYA")
    assert rc == 1 and "--year" in err
