"""HTML rendering for cards, in the style of printed Strat-O-Matic cards.

Every size inside a card is in `em` of the card's base type size, so one
layout serves the screen (scaled to fit the window) and the printer (true
size). Real SOM cards are portrait, about 2.6 in x 4.1 in, so in print a
basic side is 2.6 in wide with 6.7 pt type; the advanced side's two
platoon grids print side by side at the same type size, 5.2 in wide.

Also here: per-column stat formatting (`format_stat`), the honesty tables
(`accuracy_rows`, `advanced_accuracy_rows`) and printable sheets of cards
(`sheet_pages`, `document_html`).
"""

from __future__ import annotations

import html
import math

from .model import AdvancedCard, Card, HR, TRIPLE, DOUBLE, SINGLE, WALK, HBP, SO
from .simulate import (
    actual_batting_rates, actual_pitching_rates, combined_rates,
    derived_stats, effective_pa, hits_from_stats, pitcher_effective_pa,
)

CARD_CSS = """
/* Strat-O-Matic card. Sizes are em of the card's base type size
   (--som-size on screen); print sets true size: 2.6in x 4.1in. */
.som-card { background:#f5f5f0; color:#111; border:0.14em solid #333;
  border-radius:0.27em; font-family:'Arial Narrow','Helvetica Neue',Arial,sans-serif;
  font-size:var(--som-size, 15px); line-height:1.2; text-align:left;
  width:28em; max-width:100%; min-height:44em; box-sizing:border-box;
  margin:0 auto; display:flex; flex-direction:column;
  box-shadow:0 0.27em 0.8em rgba(0,0,0,0.3);
  -webkit-print-color-adjust:exact; print-color-adjust:exact; }
.som-card *, .som-card *::before, .som-card *::after { box-sizing:border-box; }
.som-advanced { width:56em; }
.som-header { padding:0.6em 0.8em 0.55em; border-bottom:1px solid #999; }
.som-player-name { font-weight:bold; font-size:1.4em; color:#000; }
.som-hand { font-size:0.93em; font-weight:bold; margin-left:0.6em; color:#333; }
.som-ratings { font-size:0.93em; color:#333; }
.som-adv-ratings { font-size:0.93em; color:#333; margin-top:0.15em; }
.som-adv-ratings span { white-space:nowrap; margin-right:0.9em; display:inline-block; }
.som-card-label { display:flex; justify-content:space-between; gap:0.6em;
  padding:0.4em 0.8em; background:#e8e8e0; border-bottom:1px solid #999;
  font-size:0.93em; font-weight:bold; }
.som-columns-header { display:flex; background:#d0d0c8; border-bottom:0.14em solid #333; }
.som-col-header { flex:1 1 0; text-align:center; font-weight:bold; font-size:1.13em;
  padding:0.18em; border-right:1px solid #999; }
.som-col-header:last-child { border-right:none; }
.som-columns { display:flex; flex:1 1 auto; }
.som-column { flex:1 1 0; min-width:0; overflow-wrap:anywhere; padding:0.5em 0.45em;
  border-right:1px solid #ccc; }
.som-column:last-child { border-right:none; }
.som-roll { margin:0.27em 0; }
.som-roll .dice { font-weight:bold; color:#000; }
.som-roll .positive { font-weight:bold; color:#000; }
.som-roll .negative { color:#444; }
.som-roll-split { margin-left:1.05em; font-size:0.93em; color:#555; }
.som-injury { margin-left:1.05em; font-size:0.87em; font-style:italic; color:#555; }
.som-rng { white-space:nowrap; }
.som-stats { border-top:0.14em solid #333; padding:0.6em 0.67em 0.67em; background:#e8e8e0; }
.som-stats-title { text-align:center; font-weight:bold; margin-bottom:0.45em;
  border-bottom:1px solid #999; padding-bottom:0.27em; }
.som-stats-table { width:100%; border-collapse:collapse; font-size:0.87em;
  table-layout:fixed; margin-top:-1px; }
.som-stats-table th { background:#d0d0c8; padding:0.2em 0.05em; text-align:center;
  font-weight:bold; border:1px solid #999; font-size:0.9em; letter-spacing:-0.02em;
  overflow:hidden; white-space:nowrap; }
.som-stats-table td { padding:0.2em 0.1em; text-align:center; border:1px solid #999;
  background:#f5f5f0; }
.som-adv-grids { display:flex; flex:1 1 auto; }
.som-adv-grid { flex:1 1 0; min-width:0; display:flex; flex-direction:column;
  border-right:0.14em solid #333; }
.som-adv-grid:last-child { border-right:none; }
.som-adv-banner { display:flex; justify-content:center; align-items:baseline;
  flex-wrap:wrap; gap:0 0.5em; padding:0.3em 0.4em; background:#1f1f1f; color:#f5f5f0;
  font-weight:bold; font-size:0.87em; letter-spacing:0.02em; text-align:center; }
.som-power { color:#f0d98a; white-space:nowrap; }
@media screen and (max-width:700px) {
  .som-advanced { width:28em; }
  .som-advanced .som-adv-grids { flex-direction:column; }
  .som-advanced .som-adv-grid { border-right:none; border-bottom:0.14em solid #333; }
  .som-advanced .som-adv-grid:last-child { border-bottom:none; }
}
@media print {
  .som-card { font-size:calc(6.7pt * var(--som-fit, 1)); width:2.6in;
    min-height:4.1in; max-width:none; margin:0; box-shadow:none;
    break-inside:avoid; page-break-inside:avoid; line-height:1.13; }
  .som-roll { margin:0.18em 0; }
  .som-column { padding:0.4em 0.4em; }
  .som-advanced { width:5.2in; }
  /* the advanced banners print light: two solid black bars per card
     add up over a team sheet of ink-jet paper */
  .som-adv-banner { background:#e4e4dc; color:#111;
    border-bottom:0.1em solid #333; }
  .som-power { color:#6b4f00; }
}
/* An off-screen copy of the print layout (no minimum height), where
   FIT_JS measures each card and sets --som-fit so it prints at the real
   4.1in height instead of growing past it. */
.som-measure { position:absolute; left:-10000px; top:0; visibility:hidden; }
.som-measure .som-card { font-size:calc(6.7pt * var(--som-fit, 1)); width:2.6in;
  min-height:0; max-width:none; margin:0; box-shadow:none; line-height:1.13; }
.som-measure .som-roll { margin:0.18em 0; }
.som-measure .som-column { padding:0.4em 0.4em; }
.som-measure .som-advanced { width:5.2in; }
"""

# Fit each card to the real 4.1in height when it's printed: a card whose
# entries wrap a lot (a six-position utility man, long out texts) would
# otherwise print taller than a real card. Each card is copied into an
# off-screen .som-measure box laid out at print size, and its type scaled
# down just enough to fit, never below MIN_FIT (6.7pt * 0.82 = 5.5pt).
FIT_JS = """
window.somFitCards = function (root) {
  var MIN_FIT = 0.82, TARGET = 4.1 * 96 - 1;
  var probe = document.createElement('div');
  probe.className = 'som-measure';
  document.body.appendChild(probe);
  var cards = (root || document).querySelectorAll('.som-card');
  for (var i = 0; i < cards.length; i++) {
    var card = cards[i], copy = card.cloneNode(true), fit = 1;
    copy.style.removeProperty('--som-fit');
    probe.replaceChildren(copy);
    for (var step = 0; step < 8; step++) {
      copy.style.setProperty('--som-fit', String(fit));
      var height = copy.getBoundingClientRect().height;
      if (height <= TARGET || fit <= MIN_FIT) break;
      fit = Math.max(MIN_FIT, fit * Math.max(0.9, TARGET / height) - 0.005);
    }
    if (fit < 1) card.style.setProperty('--som-fit', fit.toFixed(3));
    else card.style.removeProperty('--som-fit');
  }
  probe.remove();
};
"""

# Printed sheets: whole pages of cards at true size, cut lines = card edges.
# Basic sides go 2 x 2 per page, advanced sides 2 per page; both fit Letter
# and A4 inside 0.4in margins, so no paper size is forced.
SHEET_CSS = """
@page { margin:0.4in; }
.sheet-page { display:grid; grid-template-columns:repeat(2, 2.6in); gap:0.16in 0.2in;
  justify-content:center; align-content:start; align-items:start; }
.sheet-page.sheet-advanced { grid-template-columns:5.2in; }
.sheet-cell { break-inside:avoid; page-break-inside:avoid; }
.sheet-cell .som-card { margin:0; }
.sheet-heading { font:bold 11pt Georgia,'Times New Roman',serif; color:#222;
  text-align:center; margin:0 0 0.15in; }
@media screen {
  .sheet-page { --som-size:calc(2.6in / 28); background:#fff; width:7.7in; max-width:100%;
    margin:0 auto 0.3in; padding:0.3in 0; box-shadow:0 1px 6px rgba(0,0,0,0.25); }
  .sheet-page .som-card { width:2.6in; min-height:4.1in;
    font-size:calc(var(--som-size) * var(--som-fit, 1)); }
  .sheet-page .som-advanced { width:5.2in; }
}
@media print {
  .sheet-page { break-after:page; page-break-after:always; }
  .sheet-page:last-child { break-after:auto; page-break-after:auto; }
}
"""

# Standalone documents (saved card / team sheet files).
DOC_CSS = """
body { margin:0; padding:24px 16px; background:#ece4d2; color:#2c2a25;
  font-family:Georgia,'Times New Roman',serif; }
.doc { max-width:880px; margin:0 auto; }
.doc h1 { font-weight:normal; text-transform:uppercase; letter-spacing:.06em;
  color:#1e2d4f; font-size:22px; margin:0 0 4px; text-align:center; }
.doc .doc-sub { text-align:center; color:#5c533e; font-style:italic; margin:0 0 18px; }
.doc .doc-tip { background:#faf6ea; border:1px solid #b9ab8c; border-radius:4px;
  padding:10px 14px; margin:0 auto 18px; max-width:640px; font-size:14px; }
.doc-cards { display:flex; flex-direction:column; gap:22px; align-items:center; }
.doc-section { background:#faf6ea; border:1px solid #b9ab8c; border-radius:4px;
  padding:14px 18px; margin:18px auto; max-width:640px; font-size:14px; }
.doc-section h2 { font-size:15px; text-transform:uppercase; letter-spacing:.06em;
  color:#1e2d4f; margin:0 0 6px; font-weight:normal; }
.accuracy { border-collapse:collapse; width:100%; background:#fffdf6; }
.accuracy th, .accuracy td { border:1px solid #b9ab8c; padding:4px 10px; text-align:center; }
.accuracy th { background:#1e2d4f; color:#f5efdf; font-weight:normal; }
.accuracy td:first-child, .accuracy th:first-child { text-align:left; }
@media print {
  body { background:none; padding:0; }
  .no-print { display:none !important; }
  .doc { max-width:none; }
  .doc-cards { display:block; }
  .doc-cards .som-card { margin:0 0 0.3in; }
}
"""

_POSITIVE = {HR, TRIPLE, DOUBLE, SINGLE, WALK, HBP}

_BATTING_COLUMNS = [("AVG", "BA"), ("AB", "AB"), ("2B", "2B"), ("3B", "3B"),
                    ("HR", "HR"), ("RBI", "RBI"), ("BB", "BB"), ("SO", "SO"),
                    ("SB", "SB"), ("CS", "CS"), ("SLG%", "SLG"), ("ONBASE%", "OBP")]
_PITCHING_COLUMNS = [("W", "W"), ("L", "L"), ("ERA", "ERA"), ("STARTS", "GS"),
                     ("SAVES", "SV"), ("IP", "IP"), ("HITS", "H"), ("BB", "BB"),
                     ("SO", "SO"), ("HR", "HR")]
_RATE_KEYS = {"BA", "OBP", "SLG"}


# --- stat formatting ----------------------------------------------------------

def format_average(value) -> str:
    """'.394', '.000', '1.000'; '-' when undefined."""
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "-"
    text = f"{value:.3f}"
    return text[1:] if text.startswith("0") else text


def format_innings(ip, ipouts: int | None = None) -> str:
    """Baseball notation: 273.1 is 273 1/3 innings, 273.2 is 273 2/3, and
    whole innings print bare ('273', as on the cards). Works from exact
    outs when given, else from the numeric IP (round(IP * 3) outs), so a
    one-decimal IP like 273.3 reads correctly too."""
    if ipouts is None:
        if ip is None or not isinstance(ip, (int, float)) or not math.isfinite(ip):
            return "-"
        ipouts = int(round(float(ip) * 3))
    whole, part = divmod(int(ipouts), 3)
    return f"{whole}.{part}" if part else str(whole)


def format_stat(key: str, value, stats: dict | None = None) -> str:
    """Format one printed stat by its column, not its value: AVG/SLG/OBP
    '.xxx', ERA two decimals ('0.61', '4.70'; '-' when undefined), IP in
    baseball notation (uses stats['IP_display'] or stats['IPouts'] when
    the season line carries them), counts as integers."""
    if key == "IP":
        context = stats or {}
        shown = context.get("IP_display")
        if shown not in (None, ""):
            return str(shown)
        outs = context.get("IPouts")
        return format_innings(value, outs if isinstance(outs, int) else None)
    if value is None:
        return "-"
    if key in _RATE_KEYS:
        return format_average(value)
    if key == "ERA":
        if not isinstance(value, (int, float)):
            return str(value)
        if math.isinf(value):
            return "inf"
        return "-" if math.isnan(value) else f"{value:.2f}"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def stat_line(card: Card | AdvancedCard, season_stats: dict | None = None,
              ) -> list[tuple[str, str]]:
    """[(printed label, formatted value)] for the card's season record."""
    columns = _PITCHING_COLUMNS if card.card_type == "pitcher" else _BATTING_COLUMNS
    return [(label, format_stat(key, card.stats[key], season_stats))
            for label, key in columns if key in card.stats]


# --- cards ----------------------------------------------------------------------

def _split_html(split, show_range: bool) -> str:
    try:
        cls = "positive" if split.category in _POSITIVE else "negative"
    except ValueError:
        cls = "negative"
    text = html.escape(split.text)
    if show_range:
        rng = f"{split.lo}" if split.lo == split.hi else f"{split.lo}&ndash;{split.hi}"
        return (f'<div class="som-roll-split"><span class="{cls}">{text}</span> '
                f'<span class="som-rng">{rng}</span></div>')
    return f'<span class="{cls}">{text}</span>'


def _grid_html(card: Card) -> list[str]:
    cols = sorted(card.columns)
    parts = ['<div class="som-columns-header">'
             + "".join(f'<div class="som-col-header">{c}</div>' for c in cols)
             + "</div>", '<div class="som-columns">']
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
    return parts


def _display_name(card) -> str:
    return " ".join(w.capitalize() for w in (card.name or "").split()) or "Card"


def _header_rows(card: Card) -> list[str]:
    """The basic side's rating lines as printed: a batter's positions run
    together on one wrapping line (a six-position utility man would
    otherwise stack six lines and push the card past its real 4.1-inch
    height), then stealing and running on their own lines."""
    lines = list(card.header_lines)
    if card.card_type != "batter":
        return lines
    split = next((i for i, line in enumerate(lines)
                  if line.startswith(("stealing", "running"))), len(lines))
    positions, rest = lines[:split], lines[split:]
    return ([", ".join(positions)] if positions else []) + rest


def card_to_html(card: Card, *, team: str | None = None,
                 season_stats: dict | None = None) -> str:
    """The basic side as an HTML fragment (style it with CARD_CSS).

    `team` overrides the printed team (team sets print the set's team for
    a player traded mid-season); `season_stats` (the full season line)
    lets the record format IP from exact outs."""
    kind = "PITCHING" if card.card_type == "pitcher" else "BATTING"
    label = f"{_display_name(card)} {card.year or ''} {kind.lower()} card, basic side"
    parts = [f'<article class="som-card som-basic som-{card.card_type}" '
             f'aria-label="{html.escape(label.replace("  ", " "))}">']
    parts.append('<div class="som-header">')
    parts.append(f'<div class="som-player-name">{html.escape(card.name)}</div>')
    for line in _header_rows(card):
        parts.append(f'<div class="som-ratings">{html.escape(line)}</div>')
    parts.append("</div>")
    team_text = html.escape(team if team is not None else (card.team or ""))
    parts.append(f'<div class="som-card-label"><span>{kind} CARD</span>'
                 f'<span>{team_text}</span></div>')
    parts.extend(_grid_html(card))

    present = stat_line(card, season_stats)
    if present:
        title = f"{card.year} {kind} RECORD" if card.year else f"{kind} RECORD"
        parts.append('<div class="som-stats">')
        parts.append(f'<div class="som-stats-title">{title}</div>')
        for start in range(0, len(present), 6):
            chunk = present[start:start + 6]
            parts.append('<table class="som-stats-table"><tr>'
                         + "".join(f"<th>{html.escape(label)}</th>" for label, _ in chunk)
                         + "</tr><tr>"
                         + "".join(f"<td>{html.escape(text)}</td>" for _, text in chunk)
                         + "</tr></table>")
        parts.append("</div>")
    parts.append("</article>")
    return "\n".join(parts)


_VS_WORDS = {"LHP": "LEFT-HANDED PITCHERS", "RHP": "RIGHT-HANDED PITCHERS",
             "LHB": "LEFT-HANDED BATTERS", "RHB": "RIGHT-HANDED BATTERS"}


def side_banner(side) -> str:
    """'34% AGAINST LEFT-HANDED PITCHERS' (plain text)."""
    return f"{side.percent}% AGAINST {_VS_WORDS.get(side.vs, side.vs)}"


def advanced_card_to_html(card: AdvancedCard, *, team: str | None = None) -> str:
    """The advanced side: header ratings, then one 3-column grid per
    opposing hand, each under a banner with its printed share of PA and
    (batters) Power rating."""
    batter = card.card_type == "batter"
    kind = "BATTING" if batter else "PITCHING"
    label = f"{_display_name(card)} {card.year or ''} {kind.lower()} card, advanced side"
    parts = [f'<article class="som-card som-advanced som-{card.card_type}" '
             f'aria-label="{html.escape(label.replace("  ", " "))}">']
    parts.append('<div class="som-header">')
    hand = f"{'bats' if batter else 'throws'} {card.hand}"
    parts.append(f'<div><span class="som-player-name">{html.escape(card.name)}</span>'
                 f'<span class="som-hand">{html.escape(hand)}</span></div>')
    if card.header_lines:
        parts.append('<div class="som-adv-ratings">'
                     + "".join(f"<span>{html.escape(line)}</span>"
                               for line in card.header_lines)
                     + "</div>")
    parts.append("</div>")
    team_text = html.escape(team if team is not None else (card.team or ""))
    year = f"{card.year} " if card.year else ""
    parts.append(f'<div class="som-card-label"><span>ADVANCED {kind} CARD</span>'
                 f'<span>{year}{team_text}</span></div>')
    parts.append('<div class="som-adv-grids">')
    for side in card.sides:
        banner = html.escape(side_banner(side))
        power = (f'<span class="som-power">&middot; Power-{html.escape(side.power)}</span>'
                 if side.power else "")
        parts.append(f'<section class="som-adv-grid" aria-label="{banner.lower()}">')
        parts.append(f'<div class="som-adv-banner"><span>{banner}</span>{power}</div>')
        parts.extend(_grid_html(side.card))
        parts.append("</section>")
    parts.append("</div></article>")
    return "\n".join(parts)


# --- honesty tables ---------------------------------------------------------------

def _count(x: float) -> str:
    return f"{x:.0f}"


def pitcher_batters_faced(actual_stats: dict) -> float:
    """Batters faced the pitcher's rates are per: simulate's
    pitcher_effective_pa (BFP - IBB - SH, league-calibrated where SH or BFP
    weren't kept), so the honesty table uses the generator's denominator."""
    return pitcher_effective_pa(actual_stats)


UNRECORDED = "not recorded"


def _actual(actual_stats: dict, key: str, value: float) -> str:
    """A season count, or 'not recorded' when the season didn't keep it
    (the card then uses the league rate, so there's nothing to compare)."""
    if key in (actual_stats.get("missing") or ()):
        return UNRECORDED
    return _count(value)


def _pitcher_rows(actual_stats: dict, implied: dict) -> list[tuple[str, str, str]]:
    actual = actual_pitching_rates(actual_stats)
    tbf = pitcher_batters_faced(actual_stats)
    return [
        ("Hits allowed", _count(actual["H_per_PA"] * tbf),
         _count(implied["H_per_PA"] * tbf)),
        ("Walks (non-intentional)", _count(actual[WALK] * tbf),
         _count(implied[WALK] * tbf)),
        ("Strikeouts", _actual(actual_stats, "SO", actual[SO] * tbf),
         _count(implied[SO] * tbf)),
        ("Home runs allowed", _actual(actual_stats, "HR", actual[HR] * tbf),
         _count(implied[HR] * tbf)),
    ]


def _batter_rows(actual_stats: dict, implied: dict, *, hbp: bool,
                 ) -> list[tuple[str, str, str]]:
    actual = actual_batting_rates(actual_stats)
    pa = effective_pa(actual_stats)
    h = hits_from_stats(actual_stats)
    ab = actual_stats.get("AB", 0)
    card_hits = implied["H_per_PA"] * pa
    # Batting average over the season's own at-bats on both sides, so a
    # card that reproduces the hits shows the same average (the card's
    # implied AB would count sac flies and HBP as at-bats).
    rows = [
        ("Batting average", format_average(h / ab) if ab else "-",
         format_average(card_hits / ab) if ab else "-"),
        ("Hits", _count(h), _count(card_hits)),
        ("Doubles", _count(actual[DOUBLE] * pa), _count(implied[DOUBLE] * pa)),
        ("Triples", _count(actual[TRIPLE] * pa), _count(implied[TRIPLE] * pa)),
        ("Home runs", _count(actual[HR] * pa), _count(implied[HR] * pa)),
        ("Walks (non-intentional)", _count(actual[WALK] * pa),
         _count(implied[WALK] * pa)),
        ("Strikeouts", _actual(actual_stats, "SO", actual[SO] * pa),
         _count(implied[SO] * pa)),
    ]
    if hbp or actual[HBP] > 0 or implied.get(HBP, 0) > 0:
        rows.append(("Hit by pitch", _actual(actual_stats, "HBP", actual[HBP] * pa),
                     _count(implied.get(HBP, 0.0) * pa)))
    return rows


def accuracy_rows(card: Card, actual_stats: dict, opposing_chances: dict,
                  ) -> list[tuple[str, str, str]]:
    """(stat, actual, card-produces) rows: the season line vs what the
    basic card yields over the same plate appearances (batters faced),
    against a league-average opponent."""
    if card.card_type == "pitcher":
        return _pitcher_rows(actual_stats,
                             derived_stats(combined_rates(opposing_chances, card)))
    return _batter_rows(actual_stats,
                        derived_stats(combined_rates(card, opposing_chances)),
                        hbp=False)


def advanced_accuracy_rows(card: AdvancedCard, actual_stats: dict, ctx,
                           ) -> list[tuple[str, str, str]]:
    """The same comparison for the advanced side: each grid against its
    matchup's average opposing grid, weighted by the grid's printed share
    (batters: HBP included, since advanced grids carry it)."""
    from .benchmark import (
        advanced_batter_rates, advanced_pitcher_rates, advanced_sides,
    )
    sides = advanced_sides(card)
    if card.card_type == "pitcher":
        return _pitcher_rows(actual_stats, derived_stats(
            advanced_pitcher_rates(sides, card.hand, ctx)))
    return _batter_rows(actual_stats, derived_stats(
        advanced_batter_rates(sides, card.hand, ctx)), hbp=True)


# --- sheets and documents --------------------------------------------------------

BASIC_PER_PAGE = 4       # 2 x 2 at 2.6in x 4.1in
ADVANCED_PER_PAGE = 2    # stacked at 5.2in x 4.1in


def sheet_pages(cards_html: list[str], side: str, heading: str | None = None) -> str:
    """Card fragments laid out as printable pages (side: 'basic' or
    'advanced'), each page breaking cleanly after its last card."""
    per = ADVANCED_PER_PAGE if side == "advanced" else BASIC_PER_PAGE
    pages = []
    for start in range(0, len(cards_html), per):
        cells = "".join(f'<div class="sheet-cell">{h}</div>'
                        for h in cards_html[start:start + per])
        head = ""
        if heading and start == 0:
            head = f'<h2 class="sheet-heading" style="grid-column:1/-1">{html.escape(heading)}</h2>'
        pages.append(f'<section class="sheet-page sheet-{side}">{head}{cells}</section>')
    return "\n".join(pages)


def honesty_table_html(rows, year=None, caption: str | None = None) -> str:
    head = f"Actual {year}" if year else "Actual"
    out = ['<table class="accuracy">']
    if caption:
        out.append(f"<caption>{html.escape(caption)}</caption>")
    out.append(f'<tr><th scope="col">Stat</th><th scope="col">{head}</th>'
               '<th scope="col">This card</th></tr>')
    for label, actual, card in rows:
        out.append(f"<tr><td>{html.escape(str(label))}</td><td>{html.escape(str(actual))}</td>"
                   f"<td>{html.escape(str(card))}</td></tr>")
    out.append("</table>")
    return "".join(out)


def document_html(title: str, body: str) -> str:
    """A standalone, printable HTML document (no external files)."""
    return ("<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{html.escape(title)}</title>"
            f"<style>{CARD_CSS}{SHEET_CSS}{DOC_CSS}</style></head>"
            f"<body><main class=\"doc\">{body}</main>"
            f"<script>{FIT_JS}\nsomFitCards(document);"
            "window.addEventListener('beforeprint', function () "
            "{ somFitCards(document); });</script></body></html>\n")
