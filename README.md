# Strat-O-Matic Card Maker

Generate statistically accurate, game-usable Strat-O-Matic baseball cards
for **any player season from 1871 to 2025** — batters and pitchers, every
era, fully offline.

## Quick start

**Windows:** double-click `Start Strat-O-Gen.vbs` (first time: see
[WINDOWS_SETUP.md](WINDOWS_SETUP.md)).

**Mac / Linux (with [uv](https://docs.astral.sh/uv/) — easiest):**
```bash
uv run app.py        # uv reads the script's dependency metadata and
                     # provisions Flask itself; no venv, no pip
```

**Mac / Linux (plain Python):**
```bash
python3 -m pip install flask     # 'python3 -m pip' ensures pip and python3
python3 app.py                   # match; bare 'pip' may be a different Python
```
If pip refuses with an "externally managed environment" error (newer
Homebrew/Debian Pythons), use uv above, or
`python3 -m pip install --user flask`.

**Command line:**
```bash
python3 generate_card.py "Willie Mays" 1965
python3 generate_card.py "Nolan Ryan" 1972 --pitcher
python3 generate_card.py "Tom Seaver" 1969 --pitcher --html seaver.html
python3 generate_card.py "Aaron Judge" 2024 --advanced   # L/R platoon side
```

The only dependency is Flask (pure Python — no compilers, no native
libraries, installs cleanly on Windows). Player statistics and league
averages come from the bundled [Lahman database](https://sabr.org/lahman-database/)
(`data/lahman/*.csv.gz`), so no internet connection or scraping is needed.

## What you get

- A printable card in the classic 3-column × 11-row layout with d20 splits,
  baserunning symbols (`SINGLE*`, `DOUBLE**`), groundball A/B/C ratings,
  X-chart chances on pitcher cards, stealing/running ratings, one injury
  result and one max-effort lineout per batter card — like the real thing.
- The advanced (platoon) side too: two full grids vs left- and
  right-handed opponents, each with its printed share of PA and, for
  batters, a Power-N/W rating (command line `--advanced`; see below).
- An honesty table: what the card produces over the season's plate
  appearances vs. what actually happened (hits, HR, BB, SO, ...).
- Warnings whenever the card can't fully capture the season (see
  *Known limitations* below) or the era's data is incomplete.

Same player + year always produces the same card.

## How it works

Strat-O-Matic resolves each plate appearance on the batter's card or the
pitcher's card with equal probability (white die 1-3/4-6), with 2d6 picking
the row and a d20 resolving split chances. Each card carries 108
probability-weighted "chances"; a full batter+pitcher cycle is 216.

A card therefore encodes the player's **deviation from league average** —
the opposing average card supplies the baseline:

```
card_chances(outcome) = (2 × player_rate − league_rate) × 108
```

League rates are computed per year and league from the Lahman data (all
eras, including the Negro Leagues), so a 1908 card and a 2019 card are
built against their own run environments. Pitcher cards additionally carry
the standard 30-chance X-chart block (defense-dependent results), shrunk
automatically for extreme modern relievers whose strikeouts don't fit
otherwise.

This formula was validated against real cards: hand-counting Barry Bonds's
2001 card gives 22 HR / 41 BB / 12 K chances; the formula predicts 21.8 /
40.3 / 10.9. Nolan Ryan's 1972 card carries 47 strikeout chances; the
formula predicts 46.8.

## How we know the cards are good

`data/real_cards/` contains transcribed real cards used as ground truth:
14 in a plain-text format (`*.txt`) and 25 more in a richer JSON format
(`transcriptions/`, capturing both the basic and advanced/platoon sides plus
situational symbols — see that directory's README and SYMBOLS.md). The test
suite computes each card's **exact** expected outcome rates (no simulation
noise — the dice probabilities are summed in closed form) against a
league-average opponent and compares them to the player's actual season line:

- Real official cards land within **~0.003–0.009 of the season batting
  average** (their own d20 granularity and clamping cost them the rest).
  Extreme seasons cost more: the real Aaron Judge 2024 card can't fit both
  his home runs and his walks in 108 chances, so it trades away HR — a
  limitation generated cards share.
- Generated cards must match or beat the real card's error **on every
  category of every benchmark case** — `tests/test_benchmark.py` enforces
  this, and currently generated cards do at least as well across the board.
- A few unofficial cards (uncertain provenance, probably genuine) are
  included but tested *tolerantly*: a failure only they exhibit is allowed.

Run the suite:
```bash
python3 -m pip install pytest
python3 -m pytest
```

## Advanced (platoon) cards

`generate_advanced_batter_card` / `generate_advanced_pitcher_card`
(command line: `--advanced`, plus `--json FILE`) build the advanced side:
two full 108-chance grids — batters vs LHP/RHP, pitchers vs LHB/RHB — each
reproducing the player's line *in its matchup* against that matchup's
average opposing grid:

```
grid_chances = (2 × player_rate_in_matchup − league_rate_in_matchup) × 108
```

- **Splits** (`stratogen/platoon.py`). Lahman has no platoon data, and one
  season of an individual's split is mostly noise anyway, so every player
  gets the league-average platoon effect for his hand: one documented
  table of same-/opposite-hand ratios (a lefty hitter vs lefties strikes
  out 1.22× and homers 0.76× as often). Switch hitters always bat
  opposite-handed and have no individual split. Matchup league rates come
  from each league-year's handedness (share of batters faced by LHP; L/R/
  switch share of PA), renormalized so their mix is exactly the league
  line; the player's split is renormalized so his share-weighted mix is
  exactly his line.
- **Printed percentages.** Batters face lefties at the league's LHP share,
  part-time righties more (platoon players start against lefties);
  pitchers face left-side hitters (switch hitters included vs a righty) at
  0.91× the league share. Mean error vs the real cards: 3.3 points (12
  batters), 3.6 (7 official pitchers).
- **Power N/W**, per batter grid: W below 1.35% HR per PA (capped at 1.35×
  the league rate in low-HR eras), and always when the N formula would
  clamp. Matches 20 of the 24 labels on the real cards. A pitcher grid's
  N-HR is a `SINGLE**` for a W batter, so a W grid carries all of the
  batter's homers (2 × rate × 108): it never clamps, so a 0-HR season is
  exact.
- **Pitcher N-HR.** Only Power-N hitters (share 1 − w of a matchup's PA,
  found by applying the Power rule to the whole league-year) can homer on
  a pitcher's N-HR, so his deviation from the average pitcher's N-HR count
  is amplified by 1/(1 − w), with the extra taken from his singles
  (w capped at 0.75 for dead-ball leagues, warned). That reproduces his line
  against the matchup's real N/W mix, and the league closes exactly.
- **HBP:** batter grids carry 2 × HBP rate × 108 as whole chances on the
  edge rows real cards use; pitcher grids carry none.
- Lines too extreme for one grid get a narrower split (warned).
  `card_json.advanced_card_to_json` writes the transcriptions' JSON schema;
  `card_text.render_advanced_card` renders plain text. The advanced header
  ratings are the basic ones for now (`AdvancedCard.header_lines`).

`tests/test_platoon.py` holds generated advanced cards to at least the
basic card's accuracy on the archetypes, and to at least the real advanced
cards' accuracy on the corpus. Hitters' home runs are exact on every
generated advanced card; the price is paid by HR-stingy pitchers. Since W
hitters bring their own homers, no pitcher can allow fewer than
lg_HR × (1 + w) / 2 per PA (basic floor: lg_HR / 2). In play, Maddux 1995
gives up 1.6% HR/PA against his real 1.0% (basic card: 1.3%), with a
warning. PA-weighted over every player in the league, HR error still
falls: 2024 AL 0.0006 → 0.0003 per PA; 1995 NL 0.0009 → 0.0005; 1930 AL
0.0010 → 0.0007. The exception is dead-ball 1913 AL, 0.0004 → 0.0005. The
real SOM pitcher cards don't seem to compensate for W hitters at all,
which leaves their pitchers' HR inexact in play.

## Known limitations (shared with official cards)

A card can't hold negative chances, so when a player is *below* league
average in a category, the opposing average card supplies more of that
outcome than the player actually produced:

- A never-strikes-out batter (Gwynn) will strike out at about half the
  league rate in play — more than he really did.
- A 0-HR season still yields about half the league HR rate on the basic
  card. (Fixed on the advanced side: such a hitter is Power-W and exact.
  The cost moves to HR-stingy pitchers, see above.)
- An elite control pitcher (Maddux) walks more in play than his real rate.

The generator redistributes what it can (clamped hit deficits are absorbed
by other hit types to preserve batting average and total hits) and **warns
explicitly** about what it can't. The real-card benchmark shows official
cards have exactly the same behavior.

Other simplifications:
- Advanced-side platoon splits are league norms for the player's hand,
  not his actual split (Lahman has none; official advanced cards print
  actual, very noisy splits).
- Fielding ratings (1-5 per position, printed on the card header) are
  computed from range factor, fielding percentage, and catcher
  caught-stealing rates vs same-position/same-season peers, blended over
  the prior two seasons and shrunk for small samples. Calibrated against
  the 20 ratings printed on the fixture cards (10 exact, 19 within ±1).
  Box-score stats can't see range a fielder never reaches or scouting
  judgment, so expect occasional ±1 disagreement with official cards.
- Baserunning symbols are player-derived but heuristic: isolated power
  sets the `**` share (automatic two-base advancement), soft contact the
  `*` share, GIDP tendency the groundball-A (double play) share, and
  speed the `++` count. Directionally right, not reverse-engineered from
  official cards.
- Stealing ratings cap at A for seasons where caught-stealing wasn't
  tracked (mostly pre-1951): success rate is unknowable, so volume alone
  decides and the card carries a warning. AA requires a measured elite
  rate.
- HBP isn't placed on basic cards (matching all 14 fixture cards);
  advanced batter grids carry it, as the real advanced cards do.
- Errors/X-chart resolution assumes league-average defense.

## Game dynamics are tested too

Per-PA rates aren't the whole game, so `stratogen/game.py` is a
simplified basic-game engine that plays full innings with real
baserunners: `*`/`**` advancement, the rulebook's no-asterisk running
gamble (d20 vs the lead runner's rating, +2 with two outs), double plays
off groundball-A, sacrifice-fly tags, max-effort lineouts, and X-chart
errors. The test suite checks emergent behavior: a lineup of
league-average cards scores within a documented band of the league's
actual runs per game across run environments from 1968 to 1930 (the
engine omits steals, non-X errors, HBP and small-ball, costing a
consistent ~12-14%), eras order correctly, and symbol profiles and
running ratings measurably move run scoring.

## Repository layout

```
app.py                  Flask web app (simple web interface)
generate_card.py        Command-line interface
stratogen/
  model.py              Card data model, chance accounting, validation
  card_text.py          Parser/serializer for the plain-text card format
  card_json.py          JSON transcriptions: loader (both sides) + export
  lahman.py             Offline stats, league averages, handedness (1871-2025)
  simulate.py           Statistical tester (exact expected rates + Monte Carlo)
  platoon.py            Platoon model: matchup rates, splits, shares, Power
  generate.py           Chance targets, clamping/redistribution, card layout
                        (basic cards and advanced platoon grids)
  benchmark.py          Scoring vs the real-card fixtures (both sides)
  game.py               Simplified game engine (innings, baserunners)
  ratings.py            Stealing/running ratings (fitted to real cards)
  fielding.py           Fielding ratings 1-5 (calibrated to real cards)
  render.py             HTML card rendering
data/
  lahman/               Bundled Lahman database (gzipped CSVs)
  real_cards/           Transcribed real cards = ground truth fixtures
    *.txt               14 cards in the plain-text format
    transcriptions/     25 more in JSON (basic + advanced sides, symbols)
tests/                  pytest suite (parser, data, benchmark, platoon, app)
```

`STRAT_CARD_MAKER_SPEC_v2.md` is the original project spec, kept for
reference; where it conflicts with this README, the README reflects what
was actually built.

## Updating for a new season

Download the new CSV release from https://sabr.org/lahman-database/ (every
January), gzip `Batting.csv`, `Pitching.csv`, `People.csv`, `Teams.csv`,
`Fielding.csv`, and replace the files in `data/lahman/`.
`FieldingOFsplit.csv` isn't in the CSV release; export it from the Access
(.mdb) release with mdbtools (`mdb-export lahman.mdb FieldingOFsplit`).
The app's year bound updates automatically from the data.

## Credits

- **Strat-O-Matic** is a registered trademark of the Strat-O-Matic Game
  Company; this is an independent fan project for personal use.
- Card-formula reverse engineering builds on Bruce Bundy's community
  research (somworld.com / cba-bb.net).
- Statistics: the Lahman Baseball Database (SABR), CC BY-SA 3.0.
