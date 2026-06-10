#!/usr/bin/env python3
"""Command-line card generator.

Usage:
    python generate_card.py "Willie Mays" 1965
    python generate_card.py "Nolan Ryan" 1972 --pitcher
    python generate_card.py "Tom Seaver" 1969 --pitcher --html seaver.html
"""

from __future__ import annotations

import argparse
import sys

from stratogen.card_text import render_card
from stratogen.fielding import position_ratings, rate_position
from stratogen.generate import (
    average_batter_chances, average_pitcher_chances,
    generate_batter_card, generate_pitcher_card,
)
from stratogen.lahman import default_db
from stratogen.render import CARD_CSS, accuracy_rows, card_to_html


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Strat-O-Matic card")
    parser.add_argument("name", help="player name, e.g. 'Babe Ruth'")
    parser.add_argument("year", type=int, help="season year, e.g. 1927")
    parser.add_argument("--pitcher", action="store_true",
                        help="generate a pitcher card (default: batter)")
    parser.add_argument("--html", metavar="FILE",
                        help="also write an HTML rendering to FILE")
    args = parser.parse_args()

    db = default_db()
    kind = "pitcher" if args.pitcher else "batter"
    hits = [h for h in db.search_players(args.name)
            if args.year in (h.pitching_years if args.pitcher else h.batting_years)]
    if not hits:
        print(f"No {kind} record found for {args.name!r} in {args.year}.",
              file=sys.stderr)
        return 1
    if len(hits) > 1:
        print(f"Multiple matches for {args.name!r}:", file=sys.stderr)
        for h in hits:
            print(f"  {h.name} ({h.first_year}-{h.last_year})", file=sys.stderr)
        print("Be more specific (full name).", file=sys.stderr)
        return 1
    hit = hits[0]

    if args.pitcher:
        stats = db.pitching_season(hit.player_id, args.year)
        league = db.league_batting(args.year, stats["league"])
        card, warnings = generate_pitcher_card(
            stats, league,
            fielding_rating=rate_position(db, hit.player_id, args.year, "P") or 3)
        opposing = average_batter_chances(league)
    else:
        stats = db.batting_season(hit.player_id, args.year)
        league = db.league_batting(args.year, stats["league"])
        card, warnings = generate_batter_card(
            stats, league,
            position_ratings=position_ratings(db, hit.player_id, args.year))
        opposing = average_pitcher_chances(league)

    print(render_card(card))
    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"  - {w}")
        print()
    print("Card accuracy (actual season vs what this card produces):")
    for label, actual, implied in accuracy_rows(card, stats, opposing):
        print(f"  {label:<26} {actual:>8}  ->  {implied:>8}")

    if args.html:
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
                     f"<style>{CARD_CSS}</style></head><body>"
                     f"{card_to_html(card)}</body></html>")
        print(f"\nHTML card written to {args.html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
