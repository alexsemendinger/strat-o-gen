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
outcome text. render_card writes this format back; parse_card(render_card(
card)) reproduces the card (type, header, cells, injuries and stats).

The advanced (platoon) side has its own command-line table format,
written by render_advanced_card and read back by parse_advanced_card.
"""

from __future__ import annotations

import re
from pathlib import Path

from .model import (
    AdvancedCard, BATTER_COLUMNS, Card, DICE_WEIGHTS, PITCHER_COLUMNS,
    PlatoonSide, Split,
)
from .lahman import InningsPitched

# The real-card fixtures, resolved from the package (not the working directory).
REAL_CARDS_DIR = Path(__file__).resolve().parent.parent / "data" / "real_cards"

_INNINGS_RE = re.compile(r"^(\d+)(?:\.([012]))?$")
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


def _card_type(columns: set[int], pitching_card_line: bool,
               record_kind: str | None) -> str:
    """'batter' or 'pitcher' from the card's structure (see parse_card)."""
    evidence: dict[str, str] = {}
    if columns <= set(PITCHER_COLUMNS):
        evidence["columns"] = "pitcher"
    elif columns <= set(BATTER_COLUMNS):
        evidence["columns"] = "batter"
    if pitching_card_line:
        evidence["'PITCHING CARD' line"] = "pitcher"
    if record_kind:
        evidence[f"{record_kind} RECORD header"] = (
            "pitcher" if record_kind == "PITCHING" else "batter")
    kinds = set(evidence.values())
    if len(kinds) > 1:
        raise ValueError(f"contradictory card type: {evidence}")
    return kinds.pop() if kinds else "batter"


def parse_card(text: str) -> Card:
    """Parse one card in the plain-text format (see the module docstring).

    The card type comes from the card's structure, never from its rating
    lines (a batter who also pitched lists "pitcher-N" among his
    positions): columns 1-3 or a BATTING RECORD make a batter card,
    columns 4-6, a "PITCHING CARD" line or a PITCHING RECORD a pitcher
    card. Contradictory evidence raises ValueError.
    """
    lines = text.splitlines()
    # locate section boundaries
    column_starts = [i for i, ln in enumerate(lines) if _COLUMN_RE.match(ln)]
    if not column_starts:
        raise ValueError("no 'Column N' sections found")
    record_start = next(
        (i for i, ln in enumerate(lines) if _RECORD_RE.match(ln.strip())), len(lines))

    # --- header: name, rating lines, team (blank lines separate groups) ---
    nonblank_groups: list[list[str]] = []
    current: list[str] = []
    for ln in lines[: column_starts[0]]:
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
    pitching_card_line = False
    team = None
    for group in nonblank_groups[1:]:
        for ln in group:
            if ln.upper() == "PITCHING CARD":
                pitching_card_line = True
            else:
                team = ln

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

    # --- stats record ---
    stats: dict = {}
    year = None
    record_kind = None
    if record_start < len(lines):
        m = _RECORD_RE.match(lines[record_start].strip())
        if m.group(1):
            year = int(m.group(1))
        record_kind = m.group(2)
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
            if value == "-":                  # undefined (e.g. ERA with 0 IP)
                stats[canonical] = None
                continue
            if canonical == "IP":
                # Innings print in baseball notation: 273.1 = 273 1/3.
                m = _INNINGS_RE.match(value)
                if m:
                    outs = int(m.group(1)) * 3 + int(m.group(2) or 0)
                    stats["IP"] = InningsPitched(outs)
                    continue
            try:
                num = float(value) if ("." in value) else int(value)
            except ValueError:
                continue
            stats[canonical] = num

    card_type = _card_type(set(columns), pitching_card_line, record_kind)
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


def load_real_cards(directory: str | Path = REAL_CARDS_DIR) -> dict[str, Card]:
    """Load every .txt fixture in `directory`, keyed by file stem.

    Raises FileNotFoundError when the directory is missing or holds no
    .txt card, so a misplaced data directory fails loudly instead of
    yielding an empty corpus (and silently skipped tests)."""
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"real-card directory not found: {directory}")
    cards = {path.stem: load_card(path) for path in sorted(directory.glob("*.txt"))}
    if not cards:
        raise FileNotFoundError(f"no .txt cards in {directory}")
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
        if value is None:
            text = "-"
        elif isinstance(value, float) and value < 1:
            text = f"{value:.3f}".lstrip("0")
        else:
            text = f"{value}"
        out.append(f"{label:<17} {text}")
    return "\n".join(out) + "\n"


def _cell_lines(splits: list[Split]) -> list[str]:
    lines = []
    for s in splits:
        text = s.text + (" plus injury" if s.injury else "")
        if (s.lo, s.hi) != (1, 20):
            text += f" {s.lo}" if s.lo == s.hi else f" {s.lo}-{s.hi}"
        lines.append(text)
    return lines


def render_advanced_card(card: AdvancedCard) -> str:
    """Plain-text rendering of an advanced (platoon) card for the command
    line: the header, then each grid as a 3-column table labeled with its
    matchup, share of PA and (for batters) Power rating. parse_advanced_card
    reads it back (the stat line is not printed, and shares come back as
    the printed whole percentages)."""
    batter = card.card_type == "batter"
    title = f"{card.name}   {'bats' if batter else 'throws'} {card.hand}"
    sub = " ".join(str(x) for x in (card.year, card.team) if x)
    out = [f"{title}   {sub}" if sub else title, *card.header_lines]
    for side in card.sides:
        label = (f"vs {side.vs}   {side.percent}% of "
                 f"{'plate appearances' if batter else 'batters faced'}")
        if side.power:
            label += f"   Power-{side.power}"
        out += ["", label]
        cols = sorted(side.card.columns)
        cells = {c: {d: _cell_lines(side.card.columns[c][d])
                     for d in side.card.columns[c]} for c in cols}
        width = max([len("Column 0")] + [
            len(line) for c in cols for lines in cells[c].values()
            for line in lines]) + 2
        out.append(("    " + "".join(f"Column {c}".ljust(width)
                                     for c in cols)).rstrip())
        for d in sorted(DICE_WEIGHTS):
            stacks = [cells[c].get(d, []) for c in cols]
            for i in range(max(len(s) for s in stacks)):
                lead = f"{d:>2}  " if i == 0 else "    "
                row = "".join((s[i] if i < len(s) else "").ljust(width)
                              for s in stacks)
                out.append((lead + row).rstrip())
    return "\n".join(out) + "\n"


_ADV_TITLE_RE = re.compile(
    r"^(?P<name>.+?)   (?P<role>bats|throws) (?P<hand>\S+)(?:   (?P<sub>.+))?$")
_ADV_SIDE_RE = re.compile(
    r"^vs (?P<vs>\S+)   (?P<pct>\d+)% of (?:plate appearances|batters faced)"
    r"(?:   Power-(?P<power>\S+))?$")
_ADV_CELL_RE = re.compile(r"^(?P<text>.*?)(?: (?P<lo>\d{1,2})(?:-(?P<hi>\d{1,2}))?)?$")


def _parse_cell_line(line: str) -> Split:
    m = _ADV_CELL_RE.match(line)
    text, injury = m["text"], False
    if text.endswith(" plus injury"):
        text, injury = text[: -len(" plus injury")], True
    lo = int(m["lo"]) if m["lo"] else 1
    hi = int(m["hi"] or m["lo"]) if m["lo"] else 20
    return Split(lo=lo, hi=hi, text=text, injury=injury)


def parse_advanced_card(text: str) -> AdvancedCard:
    """Parse the output of render_advanced_card back into an AdvancedCard.

    Each grid's columns are located from its "Column N" header line, so
    outcome texts may contain spaces. The stat line is not part of the
    format (stats come back empty) and each side's share is its printed
    percentage / 100.
    """
    lines = text.splitlines()
    if not lines or not (m := _ADV_TITLE_RE.match(lines[0].rstrip())):
        raise ValueError("missing advanced-card title line")
    batter = m["role"] == "bats"
    year, team = None, None
    if m["sub"]:
        first, _, rest = m["sub"].partition(" ")
        if re.fullmatch(r"\d{4}", first):
            year, team = int(first), (rest or None)
        else:
            team = m["sub"]
    i = 1
    header_lines = []
    while i < len(lines) and lines[i].strip():
        header_lines.append(lines[i].strip())
        i += 1
    card = AdvancedCard(name=m["name"], card_type="batter" if batter else "pitcher",
                        hand=m["hand"], team=team, year=year,
                        header_lines=header_lines)
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        side = _ADV_SIDE_RE.match(lines[i].rstrip())
        if not side:
            raise ValueError(f"expected a 'vs ...' grid label: {lines[i]!r}")
        header = lines[i + 1] if i + 1 < len(lines) else ""
        starts = [(int(c[1]), c.start()) for c in re.finditer(r"Column (\d)", header)]
        if not starts:
            raise ValueError(f"vs {side['vs']}: missing 'Column N' header")
        bounds = [pos for _c, pos in starts[1:]] + [None]
        columns: dict[int, dict[int, list[Split]]] = {c: {} for c, _ in starts}
        dice_sum = None
        i += 2
        while i < len(lines) and lines[i].strip():
            line = lines[i]
            if line[:4].strip():
                dice_sum = int(line[:4])
            elif dice_sum is None:
                raise ValueError(f"grid line before any dice row: {line!r}")
            for (col, start), end in zip(starts, bounds):
                cell = line[start:end].strip()
                if cell:
                    columns[col].setdefault(dice_sum, []).append(_parse_cell_line(cell))
            i += 1
        grid = Card(name=card.name, card_type=card.card_type, team=team, year=year,
                    header_lines=list(header_lines), columns=columns)
        card.sides.append(PlatoonSide(
            vs=side["vs"], share=int(side["pct"]) / 100.0, card=grid,
            power=side["power"]))
    return card
