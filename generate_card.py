#!/usr/bin/env python3
"""Command-line card generator.

Usage:
    python generate_card.py "Willie Mays" 1965
    python generate_card.py "Nolan Ryan" 1972            # pitchers: pitcher card
    python generate_card.py "Babe Ruth" 1918 --pitcher   # pick the side of a two-way season
    python generate_card.py "Tom Seaver" 1969 --html seaver.html
    python generate_card.py "Aaron Judge" 2024 --advanced --json judge.json
    python generate_card.py "Frank Thomas"               # list players and seasons
    python generate_card.py --id thomafr04 2000          # pick one of several by ID
    python generate_card.py --team NYA --year 1927       # printable team sheet
"""

from __future__ import annotations

import argparse
import json
import sys

from stratogen import service
from stratogen.card_text import render_advanced_card, render_card
from stratogen.card_json import advanced_card_to_json
from stratogen.lahman import default_db
from stratogen.render import stat_line

_RECORD_LABELS = {"HITS": "HITS ALLOWED"}   # as card_text.render_card prints it


def text_card(cs: service.CardSet) -> str:
    """The plain-text card, with the season record formatted by column
    (ERA 2.28, AVG .356, IP 273.1) instead of render_card's by-value
    formatting."""
    text = render_card(cs.basic)
    head, sep, _record = text.partition(" RECORD\n")
    if not sep:
        return text
    lines = [head + sep.rstrip("\n")]
    for label, value in stat_line(cs.basic, cs.stats):
        lines.append(f"{_RECORD_LABELS.get(label, label):<17} {value}")
    return "\n".join(lines) + "\n"


def _write(path: str, content: str, what: str) -> bool:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError as exc:
        print(f"Could not write {path}: {exc}", file=sys.stderr)
        return False
    print(f"\n{what} written to {path}")
    return True


def _print_rows(rows, title: str) -> None:
    print(title)
    for label, actual, card in rows:
        print(f"  {label:<26} {actual:>8}  ->  {card:>8}")


def _list_players(db, players: list[dict], year: int | None) -> None:
    for p in players:
        seasons = ""
        if year is not None:
            teams = []
            for getter in (db.batting_season, db.pitching_season):
                stats = getter(p["player_id"], year)
                if stats:
                    teams += [db.team_name(year, t) for t in stats.get("team_ids", [])]
            seasons = f"  {year}: {', '.join(dict.fromkeys(teams))}" if teams else f"  (no {year} season)"
        print(f"  {p['player_id']:<11} {p['name']:<24} {p['span']:<11} "
              f"{p['position'] or p['role'] or ''}{seasons}", file=sys.stderr)


def _find_player(db, args) -> dict | None:
    """The one player meant, or None after explaining (ambiguous names
    are listed with IDs, careers and that season's teams)."""
    if args.id:
        summary = service.player_summary(db, args.id)
        if summary is None:
            print(f"No player with ID {args.id!r}.", file=sys.stderr)
        return summary
    name = (args.name or "").strip()
    if not name:
        print("Give a player name (or --id PLAYERID, or --team TEAMID --year YEAR).",
              file=sys.stderr)
        return None
    seen, players = set(), []
    for hit in db.search_players(name):
        if hit.player_id not in seen:
            seen.add(hit.player_id)
            summary = service.player_summary(db, hit.player_id)
            if summary:
                players.append(summary)
    if not players:
        print(f"No player named {name!r}. Check the spelling - a last name alone works too.",
              file=sys.stderr)
        return None
    if args.year is not None:
        fits = [p for p in players
                if args.year in p["batting_years"] or args.year in p["pitching_years"]]
        if len(fits) == 1:
            return fits[0]
        if fits:
            players = fits
    if len(players) == 1:
        return players[0]
    which = f" in {args.year}" if args.year is not None else ""
    print(f"Several players match {name!r}{which}:", file=sys.stderr)
    _list_players(db, players, args.year)
    print("Pick one with --id PLAYERID.", file=sys.stderr)
    return None


def _team(db, args) -> int:
    if args.year is None:
        print("--team needs --year, e.g. --team NYA --year 1927", file=sys.stderr)
        return 1
    try:
        ts = service.team_set(db, args.year, args.team)
    except service.CardError as exc:
        print(exc.message, file=sys.stderr)
        teams = db.teams(args.year)
        if teams:
            print(f"Teams in {args.year}:", file=sys.stderr)
            for t in teams:
                print(f"  {t['team_id']:<4} {t['name']} ({t['league']}, {t['W']}-{t['L']})",
                      file=sys.stderr)
        return 1
    print(f"{ts.title} ({ts.team['league']}, {ts.team['W']}-{ts.team['L']}): "
          f"{len(ts.cards)} cards in {ts.seconds:.2f}s")
    for c in ts.cards:
        note = f"  [{c.traded_note}]" if c.traded_note else ""
        print(f"  {c.position:<5} {c.cards.name:<24} {c.cards.kind:<8} {c.usage}{note}")
    if ts.left_out:
        print("Left out:")
        for x in ts.left_out:
            print(f"  {x['name']}: {x['reason']}")
    path = args.html or f"{args.year}_{args.team}_{args.sides}.html"
    return 0 if _write(path, service.team_document(ts, args.sides), "Printable team sheet") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a Strat-O-Matic card or team set")
    parser.add_argument("name", nargs="?", help="player name, e.g. 'Babe Ruth'")
    parser.add_argument("year", nargs="?", type=int, help="season year, e.g. 1927")
    parser.add_argument("--year", dest="year_opt", type=int, metavar="YEAR",
                        help="season year (alternative to the positional YEAR)")
    parser.add_argument("--id", metavar="PLAYERID",
                        help="Lahman player ID, to pick one of several same-name players")
    kind = parser.add_mutually_exclusive_group()
    kind.add_argument("--pitcher", action="store_true",
                      help="pitcher card (default: his main role that season)")
    kind.add_argument("--batter", action="store_true", help="batter card")
    parser.add_argument("--advanced", action="store_true",
                        help="print the advanced side (L/R platoon grids)")
    parser.add_argument("--html", metavar="FILE",
                        help="also write a printable HTML file (card, or team sheet with --team)")
    parser.add_argument("--json", metavar="FILE",
                        help="also write the card as JSON (transcription schema; the "
                             "advanced side with --advanced)")
    parser.add_argument("--team", metavar="TEAMID",
                        help="with --year: every card for that team (e.g. NYA), written "
                             "as a printable team sheet")
    parser.add_argument("--sides", choices=service.SIDES, default="both",
                        help="sides in --html output (default both)")
    args = parser.parse_args(argv)

    # '--id ruthba01 1927' puts the year in the name slot.
    if args.id and args.name and args.year is None and args.name.isdigit():
        args.year, args.name = int(args.name), None
    if args.year_opt is not None:
        args.year = args.year_opt

    db = default_db()
    if args.team:
        return _team(db, args)

    player = _find_player(db, args)
    if player is None:
        return 1
    if args.year is None:
        print(f"{player['name']} ({player['player_id']}), {player['span']}")
        print(f"  batting seasons:  {' '.join(map(str, player['batting_years'])) or '-'}")
        print(f"  pitching seasons: {' '.join(map(str, player['pitching_years'])) or '-'}")
        print("Add a year to make a card.")
        return 0

    kind = "pitcher" if args.pitcher else "batter" if args.batter else "auto"
    try:
        cs = service.make_cards(db, player["player_id"], args.year, kind)
    except service.CardError as exc:
        print(exc.message, file=sys.stderr)
        if exc.years:
            print(f"Seasons that work: {' '.join(map(str, exc.years))}", file=sys.stderr)
        if exc.other_kind:
            print(f"(use --{exc.other_kind})", file=sys.stderr)
        return 1

    side = "advanced" if args.advanced else "basic"
    print(render_advanced_card(cs.advanced) if args.advanced else text_card(cs))
    notes = ([cs.team_note()] if cs.team_note() else []) + cs.warnings
    if args.advanced:
        notes += cs.advanced_warnings
    if notes:
        print("Warnings:")
        for w in notes:
            print(f"  - {w}")
        print()
    _print_rows(cs.honesty[side], cs.honesty_note(side))

    if args.json:
        data = advanced_card_to_json(cs.advanced) if args.advanced \
            else service.basic_card_to_json(cs.basic, cs.stats)
        if not _write(args.json, json.dumps(data, indent=1, ensure_ascii=False), "JSON card"):
            return 1
    if args.html:
        if not _write(args.html, service.card_document(cs, args.sides), "HTML card"):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
