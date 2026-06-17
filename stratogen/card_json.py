"""Load the JSON card transcriptions in data/real_cards/transcriptions/.

These were transcribed (by a separate effort) in a richer, lossless schema
than the plain-text fixtures in data/real_cards/*.txt: each physical card
has up to two sides — a basic "3col" side (one grid, used vs any pitcher,
with a printed stat record) and an advanced "6col" side (two platoon grids,
vs LHP/RHP for batters or LHB/RHB for pitchers, weighted by a printed
percentage). The schema also captures situational marker glyphs and a
larger token vocabulary. See data/real_cards/transcriptions/SYMBOLS.md.

This module is the import layer: it normalizes that foreign vocabulary
(`SI*` -> `SINGLE*`, `gb (ss) A` -> `groundball (ss)A`, `N-HR` -> `HOMERUN`,
strips marker glyphs / `?` / `plus injury`) into our canonical `Card`
model so the same statistical tester and benchmark apply. The JSON files
remain the verbatim source of truth; the `Card` objects are a derived view.

Platoon generation is NOT implemented (cards are basic-game style). For an
advanced side we still get a benchmarkable quantity for free: the
percentage-weighted average of the two platoon grids' chances equals the
player's overall expected per-PA rates, and the tester accepts a chances
dict. So advanced-only cards (the unofficial pitchers, McDaniel) can still
be scored without building platoon support.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .model import Card, Split, CATEGORIES, categorize

TRANSCRIPTIONS_DIR = (
    Path(__file__).resolve().parent.parent / "data" / "real_cards" / "transcriptions")

# --- vocabulary normalization ------------------------------------------------

_MARKER_PREFIX = re.compile(r"^[◆▼△Ω●\s]+")  # ◆▼△Ω● + ws
_TRAIL_GLYPH = re.compile(r"[●?]")                               # ● ?
_INJURY = re.compile(r"\bplus\s+injury\b", re.I)
_PAREN = re.compile(r"\(([^)]*)\)")
_TRAIL_STARS = re.compile(r"(\*+)\s*$")
_CLASS = re.compile(r"\)\s*([ABC]\+*)", re.I)


def parse_result(token: str) -> tuple[str, bool]:
    """Normalize one transcribed outcome token to canonical card text.

    Returns (canonical_text, injury_flag). The canonical text always
    classifies under stratogen.model.categorize.
    """
    t = _MARKER_PREFIX.sub("", token)
    t = _TRAIL_GLYPH.sub("", t).strip()
    injury = bool(_INJURY.search(t))
    t = _INJURY.sub("", t).strip()
    up = t.upper()

    # X-chart / catcher results (defense-resolved). Match X only as its own
    # token (preceded by ')', whitespace, or '-') so words like "max" don't
    # register as fielding-chart chances.
    if "CATCHER'S CARD" in up:
        return "CATCHER'S CARD X", injury
    if re.search(r"[)\s-]X$", up):
        pos = _PAREN.search(t)
        if up.startswith(("GB", "GROUND")):
            kind = "GROUNDBALL"
        elif up.startswith("FLY"):
            kind = "FLYBALL"
        else:
            kind = "CATCH"
        return (f"{kind} ({pos.group(1)}) X" if pos else f"{kind} X"), injury

    # trailing advancement stars belong to hits/walks
    stars = ""
    ms = _TRAIL_STARS.search(t)
    if ms:
        stars = ms.group(1)
        up = t[: ms.start()].upper().strip()

    if up.startswith("HOMERUN") or "HR" in up:        # HR, N-HR, HOMERUN
        return "HOMERUN", injury
    if up.startswith(("TR", "TRIPLE")):
        return "TRIPLE", injury
    if up.startswith(("DO", "DOUBLE")):
        return f"DOUBLE{stars}", injury
    if up.startswith(("SI", "SINGLE")):
        return f"SINGLE{stars}", injury
    if up.startswith("WALK"):
        return f"WALK{stars}", injury
    if up.startswith("HBP"):
        return "HBP", injury
    if up.startswith("STRIKEOUT"):
        return "strikeout", injury

    pos = _PAREN.search(t)
    pos_str = f" ({pos.group(1)})" if pos else ""
    if up.startswith(("GB", "GROUNDBALL", "GROUND-BALL", "GROUND BALL")):
        cls = _CLASS.search(t)
        return f"groundball{pos_str}{cls.group(1) if cls else ''}", injury
    if up.startswith(("FLY", "FLYBALL")):
        cls = _CLASS.search(t)
        return f"flyball{pos_str}{cls.group(1) if cls else ''}", injury
    if up.startswith(("LO", "LINEOUT")):
        tail = " into as many outs as possible" if "as many outs" in t.lower() else ""
        return f"lineout{pos_str}{tail}", injury
    if up.startswith("POPOUT"):
        return f"popout{pos_str}", injury
    if up.startswith("FOULOUT"):
        return f"foulout{pos_str}", injury
    raise ValueError(f"unrecognized transcribed token: {token!r}")


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

    @property
    def sides(self) -> list[Side]:
        return [s for s in (self.basic, self.advanced) if s is not None]


def _load_side(path: Path) -> Side:
    d = json.loads(path.read_text(encoding="utf-8"))
    # A couple of files embed the "_unofficial" flag in cardId; strip it so
    # IDs are consistent and the two sides still join.
    card_id = d["cardId"]
    if card_id.endswith("_unofficial"):
        card_id = card_id[: -len("_unofficial")]
    return Side(
        card_id=card_id,
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
    """All transcriptions keyed by cardId, basic/advanced sides joined."""
    cards: dict[str, Transcription] = {}
    for path in sorted(Path(directory).glob("*.json")):
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
        if side.is_basic:
            card.basic = side
        else:
            card.advanced = side
    return cards


# --- grids -> Card / chances -------------------------------------------------

def _cell_splits(cell: dict) -> list[Split]:
    """The d20 partition for one cell.

    A situational cell (marked △/▼/◆/Ω on the advanced side) records a
    default result with `range: null` plus a clutch alternate that carries
    its own ranges; the two overlap. The default is the everyday reading,
    so for the card's baseline rates we use it and treat the alternate as
    situational metadata (preserved verbatim in the JSON, not in the Card).
    Otherwise the outcomes are either one full-cell result or a clean d20
    split partitioning 1-20.
    """
    baseline = [o for o in cell["outcomes"] if o.get("range") is None]
    ranged = [o for o in cell["outcomes"] if o.get("range") is not None]
    if baseline:
        text, injury = parse_result(baseline[0]["result"])
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
            v = value.strip().lstrip("0") or "0" if value.strip().startswith(".") \
                else value.strip()
            try:
                value = float(v) if "." in v else int(v)
            except ValueError:
                continue
        out[key] = value
    if side.stat_record.get("season"):
        out["year"] = side.stat_record["season"]
    return out
