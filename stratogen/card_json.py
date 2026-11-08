"""Load the JSON card transcriptions in data/real_cards/transcriptions/.

These were transcribed (by a separate effort) in a richer, lossless schema
than the plain-text fixtures in data/real_cards/*.txt: each physical card
has up to two sides — a basic "3col" side (one grid, used vs any pitcher,
with a printed stat record) and an advanced "6col" side (two platoon grids,
vs LHP/RHP for batters or LHB/RHB for pitchers, weighted by a printed
percentage). The schema also captures situational marker glyphs and a
larger token vocabulary. See data/real_cards/transcriptions/SYMBOLS.md.

This module is the import layer: it normalizes that foreign vocabulary
(`SI*` -> `SINGLE*`, `gb (ss) A` -> `groundball (ss)A`, `HR` -> `HOMERUN`,
`lo (2b) max` -> `lineout (2b) into as many outs as possible`, `N-HR` and
hit locations such as `SINGLE (lf)` kept; marker glyphs, `?`, `●` and
`plus injury` stripped — see parse_result) into our canonical `Card` model
so the same statistical tester and benchmark apply. A situational △ cell
contributes its default result, not its clutch alternate (_cell_splits).
The JSON files remain the verbatim source of truth; the `Card` objects are
a derived view.

For an advanced side, the percentage-weighted average of the two platoon
grids' chances equals the player's overall expected card content
(combined_chances); stratogen.benchmark also scores each grid against its
own matchup (transcription_sides). It is also the export layer for
generated advanced cards: advanced_card_to_json writes the same 6col
schema, so a generated card loads back through this module.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .model import AdvancedCard, Card, Split, CATEGORIES, categorize

TRANSCRIPTIONS_DIR = (
    Path(__file__).resolve().parent.parent / "data" / "real_cards" / "transcriptions")

# --- vocabulary normalization ------------------------------------------------

_MARKER_PREFIX = re.compile(r"^[◆▼△Ω●\s]+")  # ◆▼△Ω● + ws
_TRAIL_GLYPH = re.compile(r"[●?]")                               # ● ?
_INJURY = re.compile(r"\bplus\s+injury\b", re.I)

# Each token family is matched by one anchored pattern that must consume the
# whole token (after the glyphs and "plus injury" are stripped); a token no
# pattern accepts is rejected rather than guessed at.
_LOC = r"(?:\s*\(\s*(?P<pos>[^()]*?)\s*\))?"          # optional (fielder)
_CATCHER_RE = re.compile(r"^CATCH(?:ER'?S?)?(?:\s+CARD)?[\s-]*X$", re.I)
_NHR_RE = re.compile(r"^N-?HR$", re.I)
_HIT_RE = re.compile(
    r"^(?P<kind>SINGLE|SI|DOUBLE|DO|TRIPLE|TR|HOMERUN|HOME\s+RUN|HR)"
    r"(?P<stars>\**)" + _LOC + r"\s*(?P<stars2>\**)$", re.I)
_WALK_RE = re.compile(r"^WALK(?P<stars>\**)$", re.I)
_HBP_RE = re.compile(r"^(?:HBP|HIT\s+BY\s+PITCH)$", re.I)
_STRIKEOUT_RE = re.compile(r"^STRIKE\s*OUT$", re.I)
_OUT_RE = re.compile(
    r"^(?P<kind>GROUND[-\s]?BALL|GB|FLY[-\s]?BALL|FLY|LINE[-\s]?OUT|LO"
    r"|POP[-\s]?OUT|FOUL[-\s]?OUT)" + _LOC +
    r"\s*(?P<cls>[ABC]\+*)?"
    r"\s*(?P<max>max|into\s+as\s+many\s+outs\s+as\s+possible)?"
    r"\s*(?P<x>X)?$", re.I)

_HIT_KINDS = {"SI": "SINGLE", "SINGLE": "SINGLE", "DO": "DOUBLE",
              "DOUBLE": "DOUBLE", "TR": "TRIPLE", "TRIPLE": "TRIPLE",
              "HR": "HOMERUN", "HOMERUN": "HOMERUN", "HOME RUN": "HOMERUN"}
_STARRED_HITS = ("SINGLE", "DOUBLE")       # stars move runners; kept on these
_OUT_KINDS = {"GB": "groundball", "GROUNDBALL": "groundball",
              "FLY": "flyball", "FLYBALL": "flyball",
              "LO": "lineout", "LINEOUT": "lineout",
              "POPOUT": "popout", "FOULOUT": "foulout"}
_MAX_TAIL = " into as many outs as possible"


def _normalize(token: str) -> str | None:
    """Canonical text for a stripped token, or None if unrecognized."""
    if _CATCHER_RE.match(token):
        return "CATCHER'S CARD X"
    if _NHR_RE.match(token):
        return "N-HR"
    m = _HIT_RE.match(token)
    if m:
        kind = _HIT_KINDS[re.sub(r"\s+", " ", m["kind"].upper())]
        stars = (m["stars"] + m["stars2"]) if kind in _STARRED_HITS else ""
        return f"{kind}{stars}" + (f" ({m['pos']})" if m["pos"] else "")
    m = _WALK_RE.match(token)
    if m:
        return f"WALK{m['stars']}"
    if _HBP_RE.match(token):
        return "HBP"
    if _STRIKEOUT_RE.match(token):
        return "strikeout"
    m = _OUT_RE.match(token)
    if m:
        kind = _OUT_KINDS[re.sub(r"[-\s]", "", m["kind"].upper())]
        pos = f" ({m['pos']})" if m["pos"] else ""
        if m["x"]:                                 # fielding-chart chance
            if m["cls"] or m["max"]:
                return None
            return f"{kind.upper()}{pos} X"
        if m["cls"] and kind not in ("groundball", "flyball"):
            return None
        if m["max"] and kind != "lineout":
            return None
        return (f"{kind}{pos}{(m['cls'] or '').upper()}"
                + (_MAX_TAIL if m["max"] else ""))
    return None


def parse_result(token: str) -> tuple[str, bool]:
    """Normalize one transcribed outcome token to canonical card text.

    Returns (canonical_text, injury_flag); raises ValueError for a token
    outside the known vocabulary. The canonical text always classifies
    under stratogen.model.categorize. Mappings:

    - hits: `SI*` -> `SINGLE*`, `DO**` -> `DOUBLE**`, `TR` -> `TRIPLE`,
      `HR` -> `HOMERUN`; a printed hit location is kept after the stars
      (`SINGLE** (lf)`, `DOUBLE (cf)`); stars are kept on singles, doubles
      and walks only. `N-HR` stays `N-HR`.
    - outs: `gb (ss) a+` -> `groundball (ss)A+`, `fly (lf) B` ->
      `flyball (lf)B`, `lo (2b)` -> `lineout (2b)`, and the max-effort
      `lo (2b) max` -> `lineout (2b) into as many outs as possible`.
    - X chances: `GB (ss) X` -> `GROUNDBALL (ss) X`, `FLY (lf) X` ->
      `FLYBALL (lf) X`; `CATCH-X` -> `CATCHER'S CARD X`.
    - dropped (still verbatim in the JSON): leading marker glyphs
      (◆▼△Ω●), the `?` and `●` marks, and `plus injury` (returned as the
      flag).
    """
    t = _MARKER_PREFIX.sub("", token)
    t = _TRAIL_GLYPH.sub("", t)
    injury = bool(_INJURY.search(t))
    t = re.sub(r"\s+", " ", _INJURY.sub("", t)).strip()
    text = _normalize(t)
    if text is None:
        raise ValueError(f"unrecognized transcribed token: {token!r}")
    categorize(text)              # the guarantee above; raises if broken
    return text, injury


# --- data model --------------------------------------------------------------

@dataclass
class Side:
    """One photographed side of a card (basic or advanced)."""
    card_id: str
    card_type: str               # 'batter' | 'pitcher'
    side: str                    # '3col' | '6col'
    official: bool
    player: dict
    grids: list                  # raw JSON grids
    stat_record: dict | None
    confidence: str
    path: Path

    @property
    def is_basic(self) -> bool:
        return self.side == "3col"


@dataclass
class Transcription:
    """A physical card, joining its basic and/or advanced sides by cardId."""
    card_id: str
    card_type: str
    official: bool
    name: str
    year: int | None
    special: str | None
    basic: Side | None = None
    advanced: Side | None = None
    # Lahman teamID when the card covers one stint of a traded player's
    # season (player.stint in the JSON), else None (the full season).
    stint: str | None = None

    @property
    def sides(self) -> list[Side]:
        return [s for s in (self.basic, self.advanced) if s is not None]


def _load_side(path: Path) -> Side:
    d = json.loads(path.read_text(encoding="utf-8"))
    return Side(
        card_id=d["cardId"],
        card_type=d["cardType"],
        side=d["side"],
        official=d.get("official", True),
        player=d.get("player", {}),
        grids=d.get("grids", []),
        stat_record=d.get("statRecord"),
        confidence=d.get("transcription", {}).get("confidence", "unknown"),
        path=path,
    )


def load_transcriptions(directory: str | Path = TRANSCRIPTIONS_DIR,
                        ) -> dict[str, Transcription]:
    """All transcriptions keyed by cardId, basic/advanced sides joined.

    Raises FileNotFoundError when the directory is missing or holds no
    .json side, so a misplaced data directory fails loudly."""
    directory = Path(directory)
    paths = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if not paths:
        raise FileNotFoundError(f"no JSON card transcriptions in {directory}")
    cards: dict[str, Transcription] = {}
    for path in paths:
        side = _load_side(path)
        card = cards.get(side.card_id)
        if card is None:
            card = Transcription(
                card_id=side.card_id, card_type=side.card_type,
                official=side.official, name=side.player.get("name", side.card_id),
                year=side.player.get("year"),
                special=side.player.get("specialDesignation"))
            cards[side.card_id] = card
        card.official = card.official and side.official
        if side.player.get("year") and card.year is None:
            card.year = side.player["year"]
        if side.player.get("stint") and card.stint is None:
            card.stint = side.player["stint"]
        if side.is_basic:
            card.basic = side
        else:
            card.advanced = side
    return cards


# --- grids -> Card / chances -------------------------------------------------

def _is_situational(cell: dict) -> bool:
    """A △ (upTriangle) cell: a default result plus a clutch alternate."""
    return ("upTriangle" in (cell.get("markers") or [])
            or (cell.get("raw") or "").lstrip().startswith("△"))


def _situational_default(cell: dict, ranged: list[dict]) -> str:
    """The default token of a △ cell whose `outcomes` list only the ranged
    clutch alternate (the default was transcribed into `raw` alone, e.g.
    "△2-strikeout / SI* 1-11 / lo (2b) 12-20" or "△ gb (ss) A SI* 1-2 /
    lo (ss) 3-20"): the raw text before the alternate's first ranged
    outcome, less the glyph, the "N-" roll prefix and a "/" separator."""
    raw = cell.get("raw") or ""
    lo, hi = ranged[0]["range"]
    rng = f"{lo}" if lo == hi else f"{lo}-{hi}"
    m = re.search(re.escape(ranged[0]["result"]) + r"\s*" + re.escape(rng)
                  + r"(?![\d-])", raw)
    head = _MARKER_PREFIX.sub("", raw[:m.start()] if m else "")
    head = re.sub(rf"^{cell['roll']}\s*-\s*", "", head).strip().rstrip("/").strip()
    if not head:
        raise ValueError(f"situational cell without a default result: {raw!r}")
    return head


def _cell_splits(cell: dict) -> list[Split]:
    """The d20 partition for one cell.

    A cell is one full-cell result (`range: null`) or a clean d20 split
    whose ranged outcomes partition 1-20 (diamond-marked cells are plain
    splits like this; down-triangle and omega cells are single results).
    Only a situational △ (upTriangle) cell carries both: its default
    result plus a clutch alternate with its own overlapping ranges (in
    the data always a `SI*` / lineout split). The default is the everyday
    reading, so the card's baseline uses it and the alternate stays
    situational metadata (verbatim in the JSON, not in the Card). Some △
    cells list only the alternate in `outcomes` and give the default in
    `raw` alone; it is recovered from there (_situational_default).
    """
    baseline = [o for o in cell["outcomes"] if o.get("range") is None]
    ranged = [o for o in cell["outcomes"] if o.get("range") is not None]
    situational = _is_situational(cell)
    if len(baseline) > 1 or (baseline and ranged and not situational):
        raise ValueError(f"ambiguous cell (several defaults or a default "
                         f"plus a split): {cell.get('raw')!r}")
    if situational and not baseline:
        default = _situational_default(cell, ranged)
    elif baseline:
        default = baseline[0]["result"]
    else:
        default = None
    if default is not None:
        text, injury = parse_result(default)
        return [Split(lo=1, hi=20, text=text, injury=injury)]
    splits = []
    for o in ranged:
        text, injury = parse_result(o["result"])
        splits.append(Split(lo=o["range"][0], hi=o["range"][1],
                            text=text, injury=injury))
    return splits


def _grid_card(side: Side, grid: dict, name: str) -> Card:
    columns: dict[int, dict[int, list[Split]]] = {}
    for col in grid["columns"]:
        columns[col["col"]] = {
            cell["roll"]: _cell_splits(cell) for cell in col["cells"]}
    return Card(name=name.upper(), card_type=side.card_type,
                team=side.player.get("team"), year=side.player.get("year"),
                header_lines=[], stats={}, columns=columns)


def basic_card(card: Transcription) -> Card | None:
    """Card built from the basic (3col) side, or None if not photographed."""
    if card.basic is None:
        return None
    return _grid_card(card.basic, card.basic.grids[0], card.name)


def platoon_cards(card: Transcription) -> list[tuple[float, Card]]:
    """[(weight, Card)] for each advanced platoon grid (weights sum to 1)."""
    if card.advanced is None:
        return []
    grids = card.advanced.grids
    weights = [g.get("percent") or 0 for g in grids]
    total = sum(weights) or len(grids)
    if not any(weights):
        weights = [1] * len(grids)
    return [(w / total, _grid_card(card.advanced, g, card.name))
            for w, g in zip(weights, grids)]


def combined_chances(card: Transcription) -> dict[str, float] | None:
    """Percentage-weighted average of the advanced platoon grids' chances.

    Equals the player's overall expected per-PA card content, so it can be
    scored by the statistical tester exactly like a single card's chances.
    """
    parts = platoon_cards(card)
    if not parts:
        return None
    combined = {cat: 0.0 for cat in CATEGORIES}
    for weight, c in parts:
        for cat, value in c.chances().items():
            combined[cat] += weight * value
    return combined


# --- export (generated advanced cards) ----------------------------------------

def _range_text(lo: int, hi: int) -> str:
    return f"{lo}" if lo == hi else f"{lo}-{hi}"


def _cell_json(dice_sum: int, splits: list[Split]) -> dict:
    outcomes = []
    for s in splits:
        result = s.text + (" plus injury" if s.injury else "")
        rng = None if (s.lo, s.hi) == (1, 20) else [s.lo, s.hi]
        outcomes.append({"range": rng, "result": result})
    if len(outcomes) == 1 and outcomes[0]["range"] is None:
        raw = outcomes[0]["result"]
    else:
        raw = " / ".join(f"{o['result']} {_range_text(*o['range'])}"
                         for o in outcomes)
    return {"roll": dice_sum, "raw": raw, "outcomes": outcomes}


def advanced_card_to_json(card: AdvancedCard) -> dict:
    """Serialize a generated AdvancedCard to the transcription schema of a
    `*_6col.json` side, so load_transcriptions() reads it back like any
    real advanced card. Marked "official": false and "generated": true."""
    batter = card.card_type == "batter"
    words = card.name.lower().split()
    slug = "-".join(reversed(words)) if words else "unknown"
    player = {"name": card.name, "bats": card.hand if batter else None,
              "throws": None if batter else card.hand, "team": card.team,
              "year": card.year, "cardNumber": None,
              "specialDesignation": None}
    ratings: dict = {"headerLines": list(card.header_lines)}
    if batter:
        ratings["power"] = {f"vs{s.vs[0]}": s.power for s in card.sides}
    grids = []
    for side in card.sides:
        grid = {"vs": side.vs, "percent": side.percent}
        if batter:
            grid["power"] = side.power
        grid["columns"] = [
            {"col": col, "cells": [_cell_json(d, side.card.columns[col][d])
                                   for d in sorted(side.card.columns[col])]}
            for col in sorted(side.card.columns)]
        grids.append(grid)
    return {
        "cardId": f"{card.card_type}_{slug}_{card.year or 'undated'}",
        "sourceImage": None,
        "cardType": card.card_type,
        "side": "6col",
        "official": False,
        "generated": True,
        "player": player,
        "ratings": ratings,
        "grids": grids,
        "statRecord": None,
        "transcription": {"confidence": "generated", "uncertainCells": [],
                          "notes": "Generated by stratogen from the season "
                                   "line and league platoon norms."},
    }


# --- stat records ------------------------------------------------------------

_STAT_KEYS = {
    "AVG": "BA", "AVERAGE": "BA", "AB": "AB", "AT BATS": "AB",
    "2B": "2B", "DOUBLES": "2B", "3B": "3B", "TRIPLES": "3B",
    "HR": "HR", "HOMERUNS": "HR", "HOMERUNS ALLOWED": "HR",
    "RBI": "RBI", "BB": "BB", "WALKS": "BB", "WALKS ALLOWED": "BB",
    "SO": "SO", "STRIKEOUTS": "SO", "SB": "SB", "CS": "CS",
    "SLG%": "SLG", "ON BASE%": "OBP", "ONBASE%": "OBP",
    "W": "W", "WON": "W", "L": "L", "LOST": "L", "ERA": "ERA", "E.R.A.": "ERA",
    "IP": "IP", "INNINGS PITCHED": "IP", "HITS ALLOWED": "H",
    "STARTS": "GS", "SAVES": "SV", "G": "G", "H": "H",
}


def stat_record(side: Side | None) -> dict:
    """Printed stat line normalized to canonical keys (numbers parsed)."""
    if side is None or not side.stat_record:
        return {}
    out: dict = {}
    for label, value in side.stat_record.get("stats", {}).items():
        key = _STAT_KEYS.get(label.strip().upper())
        if key is None:
            continue
        if isinstance(value, str):
            v = value.strip()
            try:
                value = float(v) if "." in v else int(v)
            except ValueError:
                continue
        out[key] = value
    if side.stat_record.get("season"):
        out["year"] = side.stat_record["season"]
    return out
