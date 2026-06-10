"""Benchmark real cards against real stats.

This is how we know whether generated cards are good enough: official
Strat-O-Matic cards themselves don't reproduce season stats perfectly, so
we measure the error profile of the real-card fixtures and require
generated cards to land in the same ballpark.

Both real and generated cards are scored by the same tester against the
same average opposing card, so any bias in the average-card construction
affects both sides equally and cancels out of the comparison.
"""

from __future__ import annotations

from dataclasses import dataclass

from .card_text import load_real_cards
from .generate import average_batter_chances, average_pitcher_chances
from .lahman import LahmanDB, default_db
from .model import Card
from .simulate import (
    actual_batting_rates, actual_pitching_rates, batting_errors,
    combined_rates, derived_stats, pitching_errors,
)

# Fixture cards with no real season behind them use the stat line printed on
# the card and an assumed league context.
_SYNTHETIC_CONTEXT = {
    "posnanski_2014": (2014, "AL"),   # promotional card, fictional stat line
    "raines_hero": (1987, "NL"),      # commemorative composite, no year printed
}


@dataclass
class BenchmarkCase:
    stem: str
    card: Card
    actual_stats: dict      # real season line (Lahman) or printed line
    league: dict            # league averages for the season context
    synthetic: bool = False


def _find_player_season(db: LahmanDB, name: str, year: int, kind: str) -> dict:
    """Resolve a card's player/year to a Lahman season, by name."""
    for hit in db.search_players(name):
        years = hit.pitching_years if kind == "pitcher" else hit.batting_years
        if year in years:
            getter = db.pitching_season if kind == "pitcher" else db.batting_season
            return getter(hit.player_id, year)
    raise LookupError(f"no {kind} season found for {name!r} {year}")


def benchmark_cases(db: LahmanDB | None = None) -> list[BenchmarkCase]:
    db = db or default_db()
    cases = []
    for stem, card in load_real_cards().items():
        if stem in _SYNTHETIC_CONTEXT:
            year, lg = _SYNTHETIC_CONTEXT[stem]
            stats = dict(card.stats)
            cases.append(BenchmarkCase(
                stem=stem, card=card, actual_stats=stats,
                league=db.league_batting(year, lg), synthetic=True))
            continue
        stats = _find_player_season(db, card.name, card.year, card.card_type)
        # Cross-check the printed stat line against the database; a mismatch
        # means a wrong player match or a suspect card transcription.
        for key in ("AB", "HR", "SO"):
            printed = card.stats.get(key)
            if printed is not None and abs(printed - stats.get(key, -1)) > 2:
                raise ValueError(
                    f"{stem}: printed {key}={printed} but Lahman says "
                    f"{stats.get(key)} — wrong player match or bad card data?")
        cases.append(BenchmarkCase(
            stem=stem, card=card, actual_stats=stats,
            league=db.league_batting(stats["year"], stats["league"])))
    return cases


def score_batter_card(card_or_chances, actual_stats: dict,
                      league: dict) -> dict[str, float]:
    """Absolute per-PA rate errors of a batter card vs the actual line."""
    implied = derived_stats(
        combined_rates(card_or_chances, average_pitcher_chances(league)))
    return batting_errors(implied, actual_batting_rates(actual_stats))


def score_pitcher_card(card_or_chances, actual_stats: dict,
                       league: dict) -> dict[str, float]:
    implied = derived_stats(
        combined_rates(average_batter_chances(league), card_or_chances))
    return pitching_errors(implied, actual_pitching_rates(actual_stats))


def score_case(case: BenchmarkCase, card_or_chances=None) -> dict[str, float]:
    """Score a card (default: the real fixture card) against the case."""
    target = card_or_chances if card_or_chances is not None else case.card
    if case.card.card_type == "pitcher":
        return score_pitcher_card(target, case.actual_stats, case.league)
    return score_batter_card(target, case.actual_stats, case.league)
