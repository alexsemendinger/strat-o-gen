"""Parse and serialize the plain-text card format used in data/real_cards/.

Format (see data/real_cards/README.md):

    PLAYER NAME
    <rating lines: positions, stealing, running, pitcher role>

    [PITCHING CARD]
    TEAM NAME

    Column N
    2-<outcome>
    3-<outcome>
      <continuation, indented two spaces>
    ...
    7-<outcome A>
      1-14            <- d20 split: outcome A on 1-14
      <outcome B>
      15-20           <- outcome B on 15-20
    ...

    YYYY BATTING RECORD   (or PITCHING RECORD; year optional)
    KEY    VALUE
    ...

Hyphen-broken words are rejoined ("GROUND-" + "BALL (2B) X" ->
"GROUNDBALL (2B) X"). The phrase "plus injury" sets the injury flag on
the row's result. "into as many outs as possible" stays part of the
outcome text.
"""

from __future__ import annotations

import re
from pathlib import Path

from .model import Card, Split, DICE_WEIGHTS

_RANGE_RE = re.compile(r"^(\d{1,2})(?:-(\d{1,2}))?$")
_ENTRY_RE = re.compile(r"^(\d{1,2})-(.*)$")
_COLUMN_RE = re.compile(r"^Column\s+(\d)\s*$", re.IGNORECASE)
_RECORD_RE = re.compile(r"^(?:(\d{4})\s+)?(BATTING|PITCHING)\s+RECORD\s*$")

# Map printed stat labels to canonical keys
_STAT_KEYS = {
    "AVG": "BA", "AVERAGE": "BA",
    "AB": "AB", "ATBATS": "AB", "AT BATS": "AB",
    "2B": "2B", "DOUBLES": "2B",
    "3B": "3B", "TRIPLES": "3B",
    "HR": "HR", "HOMERUNS": "HR", "HOMERUNS ALLOWED": "HR",
    "RBI": "RBI",
    "BB": "BB", "WALKS": "BB", "WALKS ALLOWED": "BB",
    "SO": "SO", "STRIKEOUTS": "SO",
    "SB": "SB", "CS": "CS",
    "SLG%": "SLG", "ONBASE%": "OBP",
    "W": "W", "WON": "W",
    "L": "L", "LOST": "L",
    "ERA": "ERA", "E.R.A.": "ERA",
    "IP": "IP", "INNINGS PITCHED": "IP",
    "HITS ALLOWED": "H",
    "STARTS": "GS", "SAVES": "SV",
    "G": "G", "PA": "PA", "H": "H", "HBP": "HBP", "IBB": "IBB", "SF": "SF",
}


def _join_fragments(fragments: list[str]) -> str:
    """Join wrapped lines: a trailing hyphen glues directly to the next line."""
    out = ""
    for frag in fragments:
        frag = frag.strip()
        if not frag:
            continue
        if out.endswith("-"):
            out = out[:-1] + frag
        elif out:
            out += " " + frag
        else:
            out = frag
    return out


def _parse_entry(lines: list[str]) -> list[Split]:
    """Parse the lines of one dice-row entry into d20 splits.

    `lines` is the text after the "N-" prefix plus any continuation lines.
    Alternates outcome text and d20 range lines; no ranges = whole row.
    """
    injury = False
    segments: list[tuple[str, tuple[int, int] | None]] = []
    buffer: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        m = _RANGE_RE.match(line)
        if m:
            lo = int(m.group(1))
            hi = int(m.group(2)) if m.group(2) else lo
            segments.append((_join_fragments(buffer), (lo, hi)))
            buffer = []
        else:
            buffer.append(line)
    trailing = _join_fragments(buffer)
    if trailing.lower().endswith("plus injury"):
        injury = True
        trailing = trailing[: -len("plus injury")].strip()
    if trailing:
        segments.append((trailing, None))

    splits: list[Split] = []
    for text, rng in segments:
        if text.lower().endswith("plus injury"):
            injury = True
            text = text[: -len("plus injury")].strip()
        if not text:
            continue
        if rng is None:
            if len(segments) == 1:
                rng = (1, 20)
            else:
                raise ValueError(f"outcome {text!r} has no d20 range in a split row")
        splits.append(Split(lo=rng[0], hi=rng[1], text=text))
    if injury and splits:
        for s in splits:
            s.injury = True
    return splits


def parse_card(text: str) -> Card:
    lines = text.splitlines()
    # locate section boundaries
    column_starts = [i for i, ln in enumerate(lines) if _COLUMN_RE.match(ln)]
    if not column_starts:
        raise ValueError("no 'Column N' sections found")
    record_start = next(
        (i for i, ln in enumerate(lines) if _RECORD_RE.match(ln.strip())), len(lines))

    # --- header: name, rating lines, team ---
    head = [ln.rstrip() for ln in lines[: column_starts[0]]]
    head = [ln for ln in head if ln.strip() or True]  # keep blanks for grouping
    nonblank_groups: list[list[str]] = []
    current: list[str] = []
    for ln in head:
        if ln.strip():
            current.append(ln.strip())
        elif current:
            nonblank_groups.append(current)
            current = []
    if current:
        nonblank_groups.append(current)
    if not nonblank_groups:
        raise ValueError("missing card header")
    name_group = nonblank_groups[0]
    name = name_group[0]
    header_lines = name_group[1:]
    card_type = "batter"
    team = None
    for group in nonblank_groups[1:]:
        for ln in group:
            if ln.upper() == "PITCHING CARD":
                card_type = "pitcher"
            else:
                team = ln
    # ratings lines can also reveal a pitcher card
    if any("pitcher" in ln.lower() for ln in header_lines):
        card_type = "pitcher"

    # --- columns ---
    columns: dict[int, dict[int, list[Split]]] = {}
    bounds = column_starts + [record_start]
    for start, end in zip(column_starts, bounds[1:]):
        col_num = int(_COLUMN_RE.match(lines[start]).group(1))
        rows: dict[int, list[Split]] = {}
        entry_lines: list[str] = []
        dice_sum: int | None = None

        def flush():
            if dice_sum is not None:
                rows[dice_sum] = _parse_entry(entry_lines)

        for ln in lines[start + 1 : end]:
            if not ln.strip():
                continue
            m = _ENTRY_RE.match(ln)
            if m and not ln[0].isspace() and 2 <= int(m.group(1)) <= 12:
                flush()
                dice_sum = int(m.group(1))
                entry_lines = [m.group(2)]
            else:
                entry_lines.append(ln)
        flush()
        columns[col_num] = rows

    if set(columns) >= {4, 5, 6}:
        card_type = "pitcher"

    # --- stats record ---
    stats: dict = {}
    year = None
    if record_start < len(lines):
        m = _RECORD_RE.match(lines[record_start].strip())
        if m.group(1):
            year = int(m.group(1))
        for ln in lines[record_start + 1 :]:
            ln = ln.strip()
            if not ln:
                continue
            parts = ln.rsplit(None, 1)
            if len(parts) != 2:
                continue
            key, value = parts[0].strip(), parts[1]
            canonical = _STAT_KEYS.get(key.upper())
            if canonical is None:
                continue
            try:
                num = float(value) if ("." in value) else int(value)
            except ValueError:
                continue
            stats[canonical] = num

    return Card(
        name=name,
        card_type=card_type,
        team=team,
        year=year,
        header_lines=header_lines,
        stats=stats,
        columns=columns,
    )


def load_card(path: str | Path) -> Card:
    return parse_card(Path(path).read_text(encoding="utf-8"))


def load_real_cards(directory: str | Path = "data/real_cards") -> dict[str, Card]:
    """Load every .txt fixture in `directory`, keyed by file stem."""
    cards = {}
    for path in sorted(Path(directory).glob("*.txt")):
        cards[path.stem] = load_card(path)
    return cards


# --- serialization -------------------------------------------------------

def render_card(card: Card) -> str:
    """Render a Card back to the plain-text format (semantic round-trip)."""
    out: list[str] = [card.name]
    out.extend(card.header_lines)
    out.append("")
    if card.card_type == "pitcher":
        out.append("PITCHING CARD")
    if card.team:
        out.append(card.team)
    out.append("")
    for col in sorted(card.columns):
        out.append(f"Column {col}")
        for dice_sum in sorted(card.columns[col]):
            splits = card.columns[col][dice_sum]
            if len(splits) == 1 and splits[0].lo == 1 and splits[0].hi == 20:
                out.append(f"{dice_sum}-{splits[0].text}")
            else:
                out.append(f"{dice_sum}-{splits[0].text}")
                rng = (f"{splits[0].lo}" if splits[0].lo == splits[0].hi
                       else f"{splits[0].lo}-{splits[0].hi}")
                out.append(f"  {rng}")
                for s in splits[1:]:
                    out.append(f"  {s.text}")
                    rng = f"{s.lo}" if s.lo == s.hi else f"{s.lo}-{s.hi}"
                    out.append(f"  {rng}")
            if splits and splits[0].injury:
                out.append("  plus injury")
        out.append("")
    record_kind = "PITCHING" if card.card_type == "pitcher" else "BATTING"
    header = f"{card.year} {record_kind} RECORD" if card.year else f"{record_kind} RECORD"
    out.append(header)
    display = {"BA": "AVG", "SLG": "SLG%", "OBP": "ONBASE%", "H": "HITS ALLOWED",
               "GS": "STARTS", "SV": "SAVES", "IP": "IP", "ERA": "ERA"}
    for key, value in card.stats.items():
        label = display.get(key, key)
        if isinstance(value, float) and value < 1:
            text = f"{value:.3f}".lstrip("0")
        else:
            text = f"{value}"
        out.append(f"{label:<17} {text}")
    return "\n".join(out) + "\n"
