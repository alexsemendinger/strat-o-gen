"""One card pipeline for the web app, the command line and team sets.

`make_cards(db, player_id, year, kind)` turns a player-season into
everything the product shows: the basic card, the advanced (platoon) card
with its advanced-side header ratings, deduplicated plain-English warnings
for each side, an honesty table for each side, the formatted stat line and
season metadata. `team_set(db, year, team_id)` does the same for a whole
roster. Results are cached, so a team set or a reload is instant.
"""

from __future__ import annotations

import html
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace

from . import platoon
from .advanced_ratings import (
    advanced_batter_header_lines, advanced_batter_ratings,
    advanced_pitcher_header_lines, advanced_pitcher_ratings,
)
from .card_json import advanced_card_to_json
from .fielding import position_ratings, rate_position, unrecorded_positions
from .generate import (
    average_batter_chances, average_pitcher_chances,
    generate_advanced_batter_card, generate_advanced_pitcher_card,
    generate_batter_card, generate_pitcher_card,
)
from .model import AdvancedCard, Card
from .render import (
    accuracy_rows, advanced_accuracy_rows, advanced_card_to_html,
    card_to_html, document_html, honesty_table_html, pitcher_batters_faced,
    sheet_pages, stat_line,
)
from .simulate import effective_pa

KINDS = ("batter", "pitcher")
WARN_PA = 150            # below this (and >= 100) add a gentle small-sample note

ADVANCED_EXPLAINER = (
    "The advanced side is for Strat-O-Matic's advanced game: the batter "
    "and pitcher each read a grid chosen by the opponent's hand, so a "
    "hitter can be tougher on righties than lefties, and the percentage "
    "on each grid is how often he faced that hand.")

HONESTY_NOTES = {
    ("batter", "basic"): (
        "What this card produces over his {n} plate appearances, against a "
        "league-average pitcher card, versus what actually happened:"),
    ("batter", "advanced"): (
        "What the two grids produce over his {n} plate appearances, each "
        "against an average pitcher of that hand and weighted by its "
        "percentage, versus what actually happened (hit-by-pitches "
        "included: advanced grids carry them):"),
    ("pitcher", "basic"): (
        "What this card produces over his {n} batters faced (intentional "
        "walks left out), against a league-average batter card, versus "
        "what actually happened:"),
    ("pitcher", "advanced"): (
        "What the two grids produce over his {n} batters faced, each "
        "against average batters of that hand and weighted by its "
        "percentage, versus what actually happened:"),
}


class CardError(Exception):
    """A request that can't make a card, with a message for people (and
    what would work instead)."""

    def __init__(self, message: str, *, status: int = 404,
                 years: list[int] | None = None, other_kind: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.years = years or []
        self.other_kind = other_kind

    def to_json(self) -> dict:
        out = {"error": self.message}
        if self.years:
            out["years"] = self.years
        if self.other_kind:
            out["other_kind"] = self.other_kind
        return out


# --- warnings ---------------------------------------------------------------------

_NOT_TRACKED = re.compile(
    r"^(?P<field>[A-Za-z0-9]+) not tracked (?:in \S+ \d{4}|for this season)"
    r" \(treated as 0\)$")
_FIELD_WORDS = {
    "IBB": "intentional walks", "SF": "sacrifice flies", "CS": "caught stealing",
    "SO": "strikeouts", "HBP": "hit-by-pitches", "TBF": "batters faced",
    "IP": "innings pitched", "HR": "home runs", "SH": "sacrifice hits",
    "SB": "stolen bases", "BB": "walks", "H": "hits",
}
# League batting fields that don't touch a pitcher card.
_PITCHER_IRRELEVANT = {"CS", "SF", "HBP", "SB"}
_SIDE_PREFIX = re.compile(r"^vs (LHP|RHP|LHB|RHB)(?:/(LHP|RHP|LHB|RHB))?: ")
_HAND_WORD = {"L": "left", "R": "right"}


def _side_prefix(m: re.Match) -> str:
    a, b = m.group(1), m.group(2)
    who = "pitchers" if a.endswith("P") else "batters"
    if b:
        return f"Against {_HAND_WORD[a[0]]}-/{_HAND_WORD[b[0]]}-handed {who}: "
    return f"Against {_HAND_WORD[a[0]]}-handed {who}: "


def _humanize(msg: str) -> str:
    msg = _SIDE_PREFIX.sub(_side_prefix, msg.strip())
    msg = msg.replace("effective PA", "plate appearances")
    msg = re.sub(r"\bof PA\b", "of plate appearances", msg)
    msg = msg.replace("IP/H/BB", "innings, hits and walks")
    return msg[:1].upper() + msg[1:] if msg else msg


def tidy_warnings(messages: list[str], kind: str, year: int | None = None,
                  ) -> list[str]:
    """Deduplicated, readable warnings. The generator reports untracked
    fields twice (league and player) in technical shorthand; they become
    one closing line ('Not recorded in 1911: intentional walks, sacrifice
    flies - the card treats them as zero.'), dropping fields that don't
    affect this kind of card. Anything else passes through, lightly
    de-jargoned, in order, without repeats."""
    fields: list[str] = []
    out: list[str] = []
    joined = " ".join(messages)
    cs_note = "caught-stealing not tracked" in joined
    bf_estimate = "batters faced estimated" in joined
    for msg in messages:
        found = _NOT_TRACKED.match(msg.strip())
        if found:
            f = found.group("field")
            if kind == "pitcher" and f in _PITCHER_IRRELEVANT:
                continue
            if (f == "CS" and cs_note) or (f == "TBF" and bf_estimate):
                continue
            if f not in fields:
                fields.append(f)
            continue
        text = _humanize(msg)
        if text and text not in out:
            out.append(text)
    if fields:
        words = ", ".join(_FIELD_WORDS.get(f, f) for f in fields)
        when = f"in {year}" if year else "for this season"
        out.append(f"Not recorded {when}: {words} — the card treats "
                   f"{'it' if len(fields) == 1 else 'them'} as zero.")
    return out


# --- the card set -------------------------------------------------------------------

@dataclass
class CardSet:
    """Everything shown for one player-season card."""
    player_id: str
    year: int
    kind: str                       # 'batter' | 'pitcher'
    name: str                       # 'Babe Ruth'
    team: str                       # team the card prints (most games)
    league: str
    hand: str                       # bats (L/R/S) or throws (L/R)
    stats: dict                     # the full-season line
    basic: Card
    advanced: AdvancedCard
    warnings: list[str]             # basic side (and everything general)
    advanced_warnings: list[str]    # extra notes that apply to the advanced side
    honesty: dict                   # {'basic': rows, 'advanced': rows}
    kinds: list[str]                # kinds this season can make
    teams: list[dict] = field(default_factory=list)  # [{'team_id','name'}]
    denominator: float = 0.0        # PA / batters faced the tables are over

    @property
    def multi_team(self) -> bool:
        return len(self.teams) > 1

    @property
    def title(self) -> str:
        return f"{self.name} {self.year}"

    def honesty_note(self, side: str) -> str:
        return HONESTY_NOTES[(self.kind, side)].format(n=f"{self.denominator:.0f}")

    def team_note(self) -> str | None:
        if not self.multi_team:
            return None
        names = " and ".join(t["name"] for t in self.teams)
        return (f"Played for {names} in {self.year}: the card uses his "
                f"full-season line, as Strat-O-Matic does.")

    def stat_line(self) -> list[tuple[str, str]]:
        return stat_line(self.basic, self.stats)

    def basic_html(self, team: str | None = None) -> str:
        return card_to_html(self.basic, team=team, season_stats=self.stats)

    def advanced_html(self, team: str | None = None) -> str:
        return advanced_card_to_html(self.advanced, team=team)

    def card_data(self) -> dict:
        """Both sides in the transcription JSON schema (see
        data/real_cards/transcriptions): 'basic' is a 3col side, 'advanced'
        the 6col side from card_json.advanced_card_to_json."""
        return {
            "format": "strat-o-gen card data, v1",
            "player_id": self.player_id,
            "name": self.name,
            "year": self.year,
            "kind": self.kind,
            "team": self.team,
            "basic": basic_card_to_json(self.basic, self.stats),
            "advanced": advanced_card_to_json(self.advanced),
            "warnings": self.warnings + self.advanced_warnings,
        }

    def to_api(self) -> dict:
        """The JSON the web app renders."""
        return {
            "player_id": self.player_id,
            "name": self.name,
            "year": self.year,
            "kind": self.kind,
            "kinds": self.kinds,
            "team": self.team,
            "league": self.league,
            "hand": self.hand,
            "teams": self.teams,
            "team_note": self.team_note(),
            "card_html": self.basic_html(),
            "advanced_html": self.advanced_html(),
            "warnings": self.warnings,
            "advanced_warnings": self.advanced_warnings,
            "accuracy": [list(r) for r in self.honesty["basic"]],
            "honesty": {side: [list(r) for r in rows]
                        for side, rows in self.honesty.items()},
            "honesty_notes": {side: self.honesty_note(side)
                              for side in ("basic", "advanced")},
            "advanced_explainer": ADVANCED_EXPLAINER,
            "stat_line": [list(x) for x in self.stat_line()],
            "title": self.title,
        }


def _cell_json(dice_sum: int, splits) -> dict:
    outcomes = []
    for s in splits:
        result = s.text + (" plus injury" if s.injury else "")
        rng = None if (s.lo, s.hi) == (1, 20) else [s.lo, s.hi]
        outcomes.append({"range": rng, "result": result})
    if len(outcomes) == 1 and outcomes[0]["range"] is None:
        raw = outcomes[0]["result"]
    else:
        raw = " / ".join(
            f"{o['result']} {o['range'][0]}"
            + ("" if o["range"][0] == o["range"][1] else f"-{o['range'][1]}")
            for o in outcomes)
    return {"roll": dice_sum, "raw": raw, "outcomes": outcomes}


def basic_card_to_json(card: Card, season_stats: dict | None = None) -> dict:
    """A generated basic card in the transcriptions' `*_3col.json` schema
    (one grid, vs 'all'), with its printed stat record."""
    words = card.name.lower().split()
    slug = "-".join(reversed(words)) if words else "unknown"
    record = {label: text for label, text in stat_line(card, season_stats)}
    kind = "PITCHING RECORD" if card.card_type == "pitcher" else "BATTING RECORD"
    return {
        "cardId": f"{card.card_type}_{slug}_{card.year or 'undated'}",
        "sourceImage": None,
        "cardType": card.card_type,
        "side": "3col",
        "official": False,
        "generated": True,
        "player": {"name": card.name, "bats": None, "throws": None,
                   "team": card.team, "year": card.year, "cardNumber": None,
                   "specialDesignation": None},
        "ratings": {"headerLines": list(card.header_lines)},
        "grids": [{"vs": "all", "percent": None, "columns": [
            {"col": col, "cells": [_cell_json(d, card.columns[col][d])
                                   for d in sorted(card.columns[col])]}
            for col in sorted(card.columns)]}],
        "statRecord": {"kind": kind, "season": card.year, "stats": record},
        "transcription": {"confidence": "generated", "uncertainCells": [],
                          "notes": "Generated by stratogen from the season line."},
    }


# --- pipeline ---------------------------------------------------------------------

def kinds_for_season(db, player_id: str, year: int) -> list[str]:
    return [k for k in KINDS if year in db.playable_years(player_id, k)]


def _kind_word(kind: str) -> str:
    return "bat" if kind == "batter" else "pitch"


def resolve_kind(db, player_id: str, year: int, kind: str | None) -> str:
    """'auto'/None -> what he mostly was that season. Raises CardError
    (with the seasons that do work) when the season can't make that card."""
    name = db.player_name(player_id)
    available = kinds_for_season(db, player_id, year)
    if kind in (None, "", "auto"):
        if not available:
            years = sorted(set(db.playable_years(player_id, "batter"))
                           | set(db.playable_years(player_id, "pitcher")))
            raise CardError(f"{name} has no {year} season to make a card from.",
                            years=years)
        role = db.primary_role(player_id, year)
        return role if role in available else available[0]
    if kind not in KINDS:
        raise CardError("kind must be 'batter', 'pitcher' or 'auto'", status=400)
    if kind in available:
        return kind
    other = next((k for k in available if k != kind), None)
    years = db.playable_years(player_id, kind)
    if other:
        msg = (f"{name} didn't {_kind_word(kind)} in {year} — "
               f"try his {other} card.")
    elif years:
        msg = f"{name} has no {kind} card for {year}."
    else:
        msg = f"{name} never {'batted' if kind == 'batter' else 'pitched'}."
    raise CardError(msg, years=years, other_kind=other)


def _season_teams(db, stats: dict) -> list[dict]:
    ids = list(dict.fromkeys(stats.get("team_ids") or []))
    return [{"team_id": t, "name": db.team_name(stats["year"], t)} for t in ids]


def _build(db, player_id: str, year: int, kind: str) -> CardSet:
    name = db.player_name(player_id)
    try:
        if kind == "pitcher":
            stats = db.pitching_season(player_id, year)
            league = db.season_league(stats)
            fielding = rate_position(db, player_id, year, "P") or 3
            basic, warn_b = generate_pitcher_card(stats, league, fielding_rating=fielding)
            advanced, warn_a = generate_advanced_pitcher_card(
                stats, league, fielding_rating=fielding)
            header = advanced_pitcher_header_lines(
                advanced_pitcher_ratings(db, player_id, year))
            opposing = average_batter_chances(league)
            denominator = pitcher_batters_faced(stats)
        else:
            stats = db.batting_season(player_id, year)
            league = db.season_league(stats)
            positions = position_ratings(db, player_id, year)
            basic, warn_b = generate_batter_card(stats, league, position_ratings=positions)
            advanced, warn_a = generate_advanced_batter_card(
                stats, league, position_ratings=positions)
            header = advanced_batter_header_lines(
                advanced_batter_ratings(db, player_id, year))
            opposing = average_pitcher_chances(league)
            denominator = effective_pa(stats)
            blank = [p for p in unrecorded_positions(db, player_id, year)
                     if any(p == pos for pos, _r, _g in positions)]
            if blank:
                warn_b = warn_b + [
                    f"no fielding stats were recorded at {', '.join(blank)} this "
                    f"season: rated from his prior seasons, or average (3)"]
            if WARN_PA > denominator >= 100:
                warn_b = warn_b + [
                    f"only {denominator:.0f} plate appearances — small "
                    f"samples make streaky cards"]
    except (ValueError, KeyError, ZeroDivisionError) as exc:
        detail = exc.args[0] if exc.args else type(exc).__name__
        raise CardError(f"Can't make a {kind} card for {name} in {year}: {detail}.",
                        status=422, years=db.playable_years(player_id, kind)) from exc

    advanced = replace(advanced, header_lines=header)
    ctx = platoon.league_context(league, db)
    basic_warnings = tidy_warnings(warn_b, kind, year)
    adv_all = tidy_warnings(warn_a, kind, year)
    advanced_warnings = [w for w in adv_all if w not in basic_warnings]
    honesty = {
        "basic": accuracy_rows(basic, stats, opposing),
        "advanced": advanced_accuracy_rows(advanced, stats, ctx),
    }
    return CardSet(
        player_id=player_id, year=year, kind=kind, name=name,
        team=stats.get("team") or "", league=stats.get("league") or "",
        hand=advanced.hand, stats=stats, basic=basic, advanced=advanced,
        warnings=basic_warnings, advanced_warnings=advanced_warnings,
        honesty=honesty, kinds=kinds_for_season(db, player_id, year),
        teams=_season_teams(db, stats), denominator=denominator)


_CACHE: "OrderedDict[tuple, CardSet]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_SIZE = 512


def make_cards(db, player_id: str, year: int, kind: str | None = "auto") -> CardSet:
    """Basic + advanced cards and everything shown with them, for one
    player-season. kind: 'batter', 'pitcher' or 'auto' (his main role that
    season). Raises CardError with a human-readable message."""
    if not isinstance(player_id, str) or not db.player_info(player_id):
        raise CardError("Unknown player.", status=404)
    kind = resolve_kind(db, player_id, year, kind)
    key = (id(db), player_id, year, kind)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE.move_to_end(key)
            return hit
    result = _build(db, player_id, year, kind)
    with _CACHE_LOCK:
        _CACHE[key] = result
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return result


# --- players ------------------------------------------------------------------------

def player_summary(db, player_id: str) -> dict | None:
    """Name, career span (from the stats), main role and the seasons that
    make each kind of card — for search results and autocomplete."""
    info = db.career_summary(player_id)
    if not info:
        return None
    person = db.player_info(player_id)
    first, last = info["first_year"], info["last_year"]
    span = "" if first is None else (str(first) if first == last else f"{first}–{last}")
    role = info["role"]
    position = info["position"]
    if role == "batter" and position == "P":
        position = "two-way"      # e.g. Ohtani: his batting is all DH
    if role == "batter" and info["pitching_years"] and position != "two-way" and (
            len(info["pitching_years"]) >= 3 and info["bf"] >= info["pa"] / 4):
        position = f"{position or 'batter'}/P"
    bats, throws = person.get("bats") or "?", person.get("throws") or "?"
    meta = [span, position or role or "", f"bats {bats}/throws {throws}"]
    return {
        "player_id": player_id,
        "name": info["name"],
        "first_year": first,
        "last_year": last,
        "span": span,
        "role": role,
        "position": position,
        "bats": bats,
        "throws": throws,
        "meta": " · ".join(m for m in meta if m),
        "batting_years": info["batting_years"],
        "pitching_years": info["pitching_years"],
        "can_bat": bool(info["batting_years"]),
        "can_pitch": bool(info["pitching_years"]),
        "primary": role,
        "prominence": info["pa"] + info["bf"],
    }


# --- team sets ------------------------------------------------------------------------

BATTER_PA_PER_GAME = 0.32    # 50 PA over 154 games
PITCHER_IP_PER_GAME = 0.13   # 20 IP over 154 games
TWO_WAY_MIN_GAMES = 15       # games not pitching before a pitcher gets a batter card too


def team_thresholds(team_games: int) -> dict:
    """Playing time a player needs (with this team) to get a card: about
    50 PA or 20 innings over a 154-game season, scaled to the schedule."""
    games = max(team_games or 154, 1)
    return {"pa": max(10, round(BATTER_PA_PER_GAME * games)),
            "ip": max(3, round(PITCHER_IP_PER_GAME * games))}


@dataclass
class TeamCard:
    cards: CardSet
    position: str
    usage: str                  # '677 PA' / '256.1 IP, 32 GS'
    traded_note: str | None     # set when he also played elsewhere


@dataclass
class TeamSet:
    team: dict
    batters: list[TeamCard]
    pitchers: list[TeamCard]
    left_out: list[dict]
    thresholds: dict
    seconds: float = 0.0

    @property
    def title(self) -> str:
        return f"{self.team['year']} {self.team['name']}"

    @property
    def cards(self) -> list[TeamCard]:
        return self.batters + self.pitchers

    def to_api(self) -> dict:
        t = self.team
        return {
            "team": {k: t[k] for k in ("year", "team_id", "name", "league", "W", "L", "G")},
            "title": self.title,
            "thresholds": self.thresholds,
            "cards": [{
                "player_id": c.cards.player_id,
                "name": c.cards.name,
                "kind": c.cards.kind,
                "position": c.position,
                "usage": c.usage,
                "traded_note": c.traded_note,
                "warnings": len(c.cards.warnings) + len(c.cards.advanced_warnings),
                "card_html": c.cards.basic_html(team=t["name"]),
                "advanced_html": c.cards.advanced_html(team=t["name"]),
            } for c in self.cards],
            "left_out": self.left_out,
            "seconds": round(self.seconds, 3),
        }


_POS_ORDER = {p: i for i, p in enumerate(
    ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "OF", "DH"))}


def _ip_text(outs: int) -> str:
    whole, part = divmod(outs, 3)
    return f"{whole}.{part}" if part else str(whole)


def team_set(db, year: int, team_id: str) -> TeamSet:
    """Every card for a team-season: batters with enough plate
    appearances for this team, pitchers with enough innings (see
    team_thresholds), each from his full-season line; who was left out
    and why."""
    start = time.perf_counter()
    team = db.team(year, team_id)
    if team is None:
        raise CardError(f"No team {team_id!r} in {year}.", status=404)
    need = team_thresholds(team["G"])
    batters, pitchers, left_out = [], [], []

    for p in db.team_roster(year, team_id):
        bat, pit = p["batting"], p["pitching"]
        others = p["other_teams"]
        traded = None
        if others:
            names = ", ".join(o["name"] for o in others)
            traded = f"Also played for {names}; card uses his full {year} season."
        role = p["role"]
        made_any = False
        if role is None:
            left_out.append({"player_id": p["player_id"], "name": p["name"],
                             "reason": "no plate appearances or batters faced"})
            continue
        # Pitchers: by innings with this team.
        if pit is not None:
            outs = pit["IPouts"]
            if outs >= need["ip"] * 3 and pit["BF"] > 0:
                try:
                    cs = make_cards(db, p["player_id"], year, "pitcher")
                except CardError as exc:
                    left_out.append({"player_id": p["player_id"], "name": p["name"],
                                     "reason": exc.message})
                else:
                    role_txt = "SP" if pit["GS"] >= max(1, pit["G"] // 2) else "RP"
                    usage = f"{_ip_text(outs)} IP" + (f", {pit['GS']} GS" if pit["GS"] else "")
                    pitchers.append(TeamCard(cs, role_txt, usage, traded))
                    made_any = True
            elif role == "pitcher":
                left_out.append({"player_id": p["player_id"], "name": p["name"],
                                 "reason": f"{_ip_text(outs)} IP here "
                                           f"(needs {need['ip']})"})
        # Batters: position players, plus pitchers who also played the field.
        if bat is not None:
            non_pitching = p["season_bat_g"] - p["season_pitch_g"]
            two_way = role == "pitcher" and non_pitching >= TWO_WAY_MIN_GAMES
            if role == "batter" or two_way:
                if bat["PA"] >= need["pa"]:
                    try:
                        cs = make_cards(db, p["player_id"], year, "batter")
                    except CardError as exc:
                        left_out.append({"player_id": p["player_id"], "name": p["name"],
                                         "reason": exc.message})
                    else:
                        fielded = next((q for q, _g in p["positions"]
                                        if q not in ("P", "PH", "PR")), None)
                        pos = fielded or "DH"
                        if role == "pitcher":
                            pos = f"P/{fielded or 'PH'}"
                        batters.append(TeamCard(cs, pos, f"{bat['PA']} PA", traded))
                        made_any = True
                elif not made_any:
                    left_out.append({"player_id": p["player_id"], "name": p["name"],
                                     "reason": f"{bat['PA']} PA here (needs {need['pa']})"})

    batters.sort(key=lambda c: (_POS_ORDER.get(c.position, 20),
                                -int(c.usage.split()[0])))
    pitchers.sort(key=lambda c: (c.position != "SP",
                                 -float(c.usage.split()[0])))
    left_out.sort(key=lambda x: x["name"])
    return TeamSet(team=team, batters=batters, pitchers=pitchers,
                   left_out=left_out, thresholds=need,
                   seconds=time.perf_counter() - start)


# --- printable documents ------------------------------------------------------------

SIDES = ("basic", "advanced", "both")

PRINT_TIP = ("Print at 100% scale (“Actual size”, not “Fit to "
             "page”) so cards come out at real size: 2.6 inches wide. "
             "Turn on “Background graphics” for the shaded bars.")


def card_document(cs: CardSet, sides: str = "both") -> str:
    """A standalone HTML file for one card: the chosen side(s) at true
    size, plus (on screen only) warnings and the honesty tables."""
    parts = [f"<h1>{html.escape(cs.title)}</h1>",
             f'<p class="doc-sub">{html.escape(cs.team)} · '
             f"{'pitcher' if cs.kind == 'pitcher' else 'batter'} card</p>",
             f'<p class="doc-tip no-print">{html.escape(PRINT_TIP)} '
             '<button type="button" onclick="window.print()">Print</button></p>',
             '<div class="doc-cards">']
    if sides in ("basic", "both"):
        parts.append(cs.basic_html())
    if sides in ("advanced", "both"):
        parts.append(cs.advanced_html())
    parts.append("</div>")
    notes = cs.warnings + cs.advanced_warnings
    if cs.team_note():
        notes = [cs.team_note()] + notes
    if notes:
        parts.append('<section class="doc-section no-print"><h2>Heads up</h2><ul>'
                     + "".join(f"<li>{html.escape(w)}</li>" for w in notes)
                     + "</ul></section>")
    for side in ("basic", "advanced"):
        if sides not in (side, "both"):
            continue
        parts.append(f'<section class="doc-section no-print"><h2>How well does the '
                     f'{side} side match the real season?</h2>'
                     f"<p>{html.escape(cs.honesty_note(side))}</p>"
                     + honesty_table_html(cs.honesty[side], cs.year) + "</section>")
    return document_html(f"{cs.title} {cs.kind} card", "".join(parts))


def team_document(ts: TeamSet, sides: str = "both") -> str:
    """A printable team sheet: every card of the set at true size, basic
    sides 4 to a page, advanced sides 2 to a page (basic pages first when
    printing both)."""
    name = ts.team["name"]
    parts = [f"<h1 class=\"no-print\">{html.escape(ts.title)}</h1>",
             f'<p class="doc-sub no-print">{ts.team["league"]} · '
             f'{ts.team["W"]}-{ts.team["L"]} · {len(ts.cards)} cards</p>',
             f'<p class="doc-tip no-print">{html.escape(PRINT_TIP)} '
             '<button type="button" onclick="window.print()">Print</button></p>']
    if sides in ("basic", "both"):
        parts.append(sheet_pages([c.cards.basic_html(team=name) for c in ts.cards],
                                 "basic"))
    if sides in ("advanced", "both"):
        parts.append(sheet_pages([c.cards.advanced_html(team=name) for c in ts.cards],
                                 "advanced"))
    if ts.left_out:
        parts.append('<section class="doc-section no-print"><h2>Left out</h2><ul>'
                     + "".join(f"<li>{html.escape(x['name'])}: {html.escape(x['reason'])}</li>"
                               for x in ts.left_out) + "</ul></section>")
    side_word = {"basic": "basic sides", "advanced": "advanced sides",
                 "both": "cards"}[sides]
    return document_html(f"{ts.title} {side_word}", "".join(parts))
