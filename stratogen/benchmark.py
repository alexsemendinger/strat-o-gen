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
from .card_json import (
    Transcription, basic_card, combined_chances, load_transcriptions,
    platoon_cards,
)
from .generate import (
    average_advanced_batter_chances, average_advanced_pitcher_chances,
    average_batter_chances, average_pitcher_chances,
)
from .lahman import LahmanDB, default_db
from .model import AdvancedCard, Card, HBP
from .simulate import (
    RATE_CATEGORIES, actual_batting_rates, actual_pitching_rates,
    batting_errors, combined_rates, derived_stats, pitching_errors,
)
from . import platoon

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


@dataclass
class TranscriptionCase:
    """A JSON-transcribed card scored against its real Lahman season.

    `reps` maps representation name -> scoreable target: "basic" -> the
    3col-side Card; "advanced" -> the percentage-weighted platoon chances
    dict. A card may have one or both.
    """
    card_id: str
    transcription: Transcription
    actual_stats: dict
    league: dict
    reps: dict
    official: bool

    @property
    def card_type(self) -> str:
        return self.transcription.card_type


def transcription_cases(db: LahmanDB | None = None) -> list[TranscriptionCase]:
    """Build scoreable cases from the JSON transcriptions.

    Only cards that resolve to a real (player, year) in Lahman get a case
    (HOF/undated cards have no single-season context for league averages —
    they are still parsed and structurally validated elsewhere).
    """
    db = db or default_db()
    cases = []
    for card_id, card in sorted(load_transcriptions().items()):
        if card.year is None:
            continue
        getter = (db.pitching_season if card.card_type == "pitcher"
                  else db.batting_season)
        pid = None
        for hit in db.search_players(card.name):
            years = (hit.pitching_years if card.card_type == "pitcher"
                     else hit.batting_years)
            if card.year in years:
                pid = hit.player_id
                break
        if pid is None:
            continue
        stats = getter(pid, card.year)
        reps = {}
        bc = basic_card(card)
        if bc is not None:
            reps["basic"] = bc
        cc = combined_chances(card)
        if cc is not None:
            reps["advanced"] = cc
        if not reps:
            continue
        cases.append(TranscriptionCase(
            card_id=card_id, transcription=card, actual_stats=stats,
            league=db.league_batting(stats["year"], stats["league"]),
            reps=reps, official=card.official))
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
    return pitching_errors(implied, actual_pitching_rates(actual_stats, league))


# --- advanced (platoon) cards ---------------------------------------------------
#
# An advanced card is scored side by side: each grid against the average
# opposing grid of its own matchup, weighted by the grid's share of PA.
# Sides are (vs, share, card_or_chances, power) tuples so real
# transcriptions and generated AdvancedCards score identically.

def advanced_sides(card: AdvancedCard) -> list[tuple]:
    return [(s.vs, s.share, s.card, s.power) for s in card.sides]


def transcription_sides(card: Transcription) -> list[tuple]:
    """Sides of a transcribed advanced card (weights normalized to 1)."""
    grids = card.advanced.grids if card.advanced else []
    return [(g["vs"], weight, grid_card, g.get("power") or "N")
            for (weight, grid_card), g in zip(platoon_cards(card), grids)]


def advanced_batter_rates(sides, bats: str, ctx) -> dict[str, float]:
    """Share-weighted per-PA rates of a batter's grids, each against the
    average pitcher grid of its matchup (Power-W grids read that grid's
    N-HR as singles)."""
    total = {cat: 0.0 for cat in RATE_CATEGORIES}
    for vs, share, grid, power in sides:
        p = vs[0]
        opp = average_advanced_pitcher_chances(
            ctx.cell_league(p, platoon.effective_hand(bats, p)))
        for cat, v in combined_rates(grid, opp, batter_power=power).items():
            total[cat] += share * v
    return total


def advanced_pitcher_rates(sides, throws: str, ctx) -> dict[str, float]:
    """Share-weighted per-PA rates of a pitcher's grids, each against its
    matchup's average batter grid — a mix of Power-N batters (share
    1 - w, who homer on the N-HR) and Power-W batters (share w, for whom
    the N-HR are singles)."""
    p = platoon.throwing_hand(throws)
    p = "R" if p == "?" else p
    total = {cat: 0.0 for cat in RATE_CATEGORIES}
    for vs, share, grid, _power in sides:
        h = vs[0]
        w = ctx.weak_share[(p, h)]
        opp = average_advanced_batter_chances(ctx.cell_league(p, h), w)
        n = combined_rates(opp, grid, batter_power="N")
        wk = combined_rates(opp, grid, batter_power="W")
        for cat in RATE_CATEGORIES:
            total[cat] += share * ((1.0 - w) * n[cat] + w * wk[cat])
    return total


def score_advanced_batter(sides, bats: str, actual_stats: dict, ctx,
                          ) -> dict[str, float]:
    """Rate errors of an advanced batter card (HBP included)."""
    implied = derived_stats(advanced_batter_rates(sides, bats, ctx))
    actual = actual_batting_rates(actual_stats)
    errors = batting_errors(implied, actual)
    errors[HBP] = abs(implied[HBP] - actual[HBP])
    return errors


def score_advanced_pitcher(sides, throws: str, actual_stats: dict, ctx,
                           ) -> dict[str, float]:
    implied = derived_stats(advanced_pitcher_rates(sides, throws, ctx))
    return pitching_errors(implied, actual_pitching_rates(actual_stats))


def score_case(case: BenchmarkCase, card_or_chances=None) -> dict[str, float]:
    """Score a card (default: the real fixture card) against the case."""
    target = card_or_chances if card_or_chances is not None else case.card
    if case.card.card_type == "pitcher":
        return score_pitcher_card(target, case.actual_stats, case.league)
    return score_batter_card(target, case.actual_stats, case.league)
