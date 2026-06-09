"""HTML rendering for cards, in the style of printed Strat-O-Matic cards."""

from __future__ import annotations

import html

from .model import Card, HR, TRIPLE, DOUBLE, SINGLE, WALK, SO, OUT
from .simulate import (
    actual_batting_rates, actual_pitching_rates, combined_rates,
    derived_stats, effective_pa, hits_from_stats,
)

CARD_CSS = """
.som-card { background:#f5f5f0; border:2px solid #333; border-radius:4px;
  font-family:'Arial Narrow',Arial,sans-serif; max-width:520px; margin:0 auto;
  box-shadow:0 4px 12px rgba(0,0,0,0.3); }
.som-header { padding:8px 12px; border-bottom:1px solid #999; }
.som-player-name { font-weight:bold; font-size:18px; color:#000; }
.som-ratings { font-size:12px; color:#333; }
.som-card-label { display:flex; justify-content:space-between; padding:6px 12px;
  background:#e8e8e0; border-bottom:1px solid #999; font-size:12px; font-weight:bold; }
.som-columns-header { display:flex; background:#d0d0c8; border-bottom:2px solid #333; }
.som-col-header { flex:1; text-align:center; font-weight:bold; font-size:16px;
  padding:4px; border-right:1px solid #999; }
.som-col-header:last-child { border-right:none; }
.som-columns { display:flex; }
.som-column { flex:1; padding:6px 8px; border-right:1px solid #ccc; font-size:12px; }
.som-column:last-child { border-right:none; }
.som-roll { margin:2px 0; line-height:1.3; }
.som-roll .dice { font-weight:bold; color:#000; }
.som-roll .positive { font-weight:bold; color:#000; }
.som-roll .negative { color:#444; }
.som-roll-split { margin-left:20px; font-size:11px; color:#555; }
.som-injury { margin-left:20px; font-size:11px; font-style:italic; color:#555; }
.som-stats { border-top:2px solid #333; padding:10px; background:#e8e8e0; }
.som-stats-title { text-align:center; font-weight:bold; font-size:13px;
  margin-bottom:8px; border-bottom:1px solid #999; padding-bottom:4px; }
.som-stats-table { width:100%; border-collapse:collapse; font-size:11px; }
.som-stats-table th { background:#d0d0c8; padding:3px 6px; text-align:center;
  font-weight:bold; border:1px solid #999; }
.som-stats-table td { padding:3px 6px; text-align:center; border:1px solid #999;
  background:#f5f5f0; }
@media print {
  body * { visibility:hidden; }
  .som-card, .som-card * { visibility:visible; }
  .som-card { position:absolute; left:0; top:0; box-shadow:none; }
}
"""

_POSITIVE = {HR, TRIPLE, DOUBLE, SINGLE, WALK}

_BATTING_COLUMNS = [("AVG", "BA"), ("AB", "AB"), ("2B", "2B"), ("3B", "3B"),
                    ("HR", "HR"), ("RBI", "RBI"), ("BB", "BB"), ("SO", "SO"),
                    ("SB", "SB"), ("CS", "CS"), ("SLG%", "SLG"), ("ONBASE%", "OBP")]
_PITCHING_COLUMNS = [("W", "W"), ("L", "L"), ("ERA", "ERA"), ("STARTS", "GS"),
                     ("SAVES", "SV"), ("IP", "IP"), ("HITS", "H"), ("BB", "BB"),
                     ("SO", "SO"), ("HR", "HR")]


def _fmt(value) -> str:
    if isinstance(value, float) and 0 < value < 1:
        return f"{value:.3f}".lstrip("0")
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def _split_html(split, show_range: bool) -> str:
    cls = "positive" if split.category in _POSITIVE else "negative"
    text = html.escape(split.text)
    if show_range:
        rng = f"{split.lo}" if split.lo == split.hi else f"{split.lo}&ndash;{split.hi}"
        return f'<div class="som-roll-split"><span class="{cls}">{text}</span> {rng}</div>'
    return f'<span class="{cls}">{text}</span>'


def card_to_html(card: Card) -> str:
    """Render a card as an HTML fragment (style it with CARD_CSS)."""
    parts = ['<div class="som-card">']
    parts.append('<div class="som-header">')
    parts.append(f'<div class="som-player-name">{html.escape(card.name)}</div>')
    for line in card.header_lines:
        parts.append(f'<div class="som-ratings">{html.escape(line)}</div>')
    parts.append("</div>")
    label = "PITCHING CARD" if card.card_type == "pitcher" else "BATTING CARD"
    team = html.escape(card.team or "")
    parts.append(f'<div class="som-card-label"><span>{label}</span>'
                 f'<span>{team}</span></div>')
    cols = sorted(card.columns)
    parts.append('<div class="som-columns-header">'
                 + "".join(f'<div class="som-col-header">{c}</div>' for c in cols)
                 + "</div>")
    parts.append('<div class="som-columns">')
    for col in cols:
        parts.append('<div class="som-column">')
        for dice in sorted(card.columns[col]):
            splits = card.columns[col][dice]
            if len(splits) == 1:
                inner = _split_html(splits[0], show_range=False)
                parts.append(f'<div class="som-roll"><span class="dice">{dice}-</span>'
                             f'{inner}</div>')
            else:
                parts.append(f'<div class="som-roll"><span class="dice">{dice}-</span></div>')
                for s in splits:
                    parts.append(_split_html(s, show_range=True))
            if splits and splits[0].injury:
                parts.append('<div class="som-injury">plus injury</div>')
        parts.append("</div>")
    parts.append("</div>")

    columns = _PITCHING_COLUMNS if card.card_type == "pitcher" else _BATTING_COLUMNS
    present = [(label, key) for label, key in columns if key in card.stats]
    if present:
        kind = "PITCHING" if card.card_type == "pitcher" else "BATTING"
        title = f"{card.year} {kind} RECORD" if card.year else f"{kind} RECORD"
        parts.append('<div class="som-stats">')
        parts.append(f'<div class="som-stats-title">{title}</div>')
        for chunk_start in range(0, len(present), 6):
            chunk = present[chunk_start:chunk_start + 6]
            parts.append('<table class="som-stats-table"><tr>'
                         + "".join(f"<th>{label}</th>" for label, _ in chunk)
                         + "</tr><tr>"
                         + "".join(f"<td>{_fmt(card.stats[key])}</td>"
                                   for _, key in chunk)
                         + "</tr></table>")
        parts.append("</div>")
    parts.append("</div>")
    return "\n".join(parts)


def accuracy_rows(card: Card, actual_stats: dict, opposing_chances: dict,
                  ) -> list[tuple[str, str, str]]:
    """(stat, actual, card-produces) rows comparing the season line with
    what the card yields over the same number of plate appearances."""
    if card.card_type == "pitcher":
        implied = derived_stats(combined_rates(opposing_chances, card))
        actual = actual_pitching_rates(actual_stats)
        tbf = (actual_stats.get("TBF") or
               actual_stats.get("IP", 0) * 3 + actual_stats.get("H", 0)
               + actual_stats.get("BB", 0)) - actual_stats.get("IBB", 0)
        rows = [
            ("Hits allowed", f"{actual['H_per_PA'] * tbf:.0f}",
             f"{implied['H_per_PA'] * tbf:.0f}"),
            ("Walks", f"{actual[WALK] * tbf:.0f}", f"{implied[WALK] * tbf:.0f}"),
            ("Strikeouts", f"{actual[SO] * tbf:.0f}", f"{implied[SO] * tbf:.0f}"),
            ("Home runs allowed", f"{actual[HR] * tbf:.0f}",
             f"{implied[HR] * tbf:.0f}"),
        ]
        return rows
    implied = derived_stats(combined_rates(card, opposing_chances))
    actual = actual_batting_rates(actual_stats)
    pa = effective_pa(actual_stats)
    h = hits_from_stats(actual_stats)
    ab = actual_stats.get("AB", 0)
    implied_ab = (1.0 - implied[WALK]) * pa
    rows = [
        ("Batting average", f"{h / ab:.3f}" if ab else "-", f"{implied['BA']:.3f}"),
        ("Hits", f"{h:.0f}", f"{implied['H_per_PA'] * pa:.0f}"),
        ("Home runs", f"{actual[HR] * pa:.0f}", f"{implied[HR] * pa:.0f}"),
        ("Doubles", f"{actual[DOUBLE] * pa:.0f}", f"{implied[DOUBLE] * pa:.0f}"),
        ("Triples", f"{actual[TRIPLE] * pa:.0f}", f"{implied[TRIPLE] * pa:.0f}"),
        ("Walks (non-intentional)", f"{actual[WALK] * pa:.0f}",
         f"{implied[WALK] * pa:.0f}"),
        ("Strikeouts", f"{actual[SO] * pa:.0f}", f"{implied[SO] * pa:.0f}"),
    ]
    return rows
