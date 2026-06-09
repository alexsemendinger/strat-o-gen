# Strat-O-Matic Card Maker

Generate statistically accurate, game-usable Strat-O-Matic baseball cards
for **any player season from 1871 to 2025** — batters and pitchers, every
era, fully offline.

## Quick start

**Windows:** double-click `Start Strat-O-Gen.vbs` (first time: see
[WINDOWS_SETUP.md](WINDOWS_SETUP.md)).

**Mac / Linux:**
```bash
pip install flask
python3 app.py          # opens http://localhost:5001 in your browser
```

**Command line:**
```bash
python3 generate_card.py "Willie Mays" 1965
python3 generate_card.py "Nolan Ryan" 1972 --pitcher
python3 generate_card.py "Tom Seaver" 1969 --pitcher --html seaver.html
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

`data/real_cards/` contains 14 transcribed official cards (10 batters, 4
pitchers). The test suite computes each card's **exact** expected outcome
rates (no simulation noise — the dice probabilities are summed in closed
form) against a league-average opponent and compares them to the player's
actual season line:

- Real official cards land within **0.003–0.009 of the season batting
  average** (their own d20 granularity and clamping cost them the rest).
- Generated cards must match or beat the real card's error **on every
  category of every benchmark case** — `tests/test_benchmark.py` enforces
  this, and currently generated cards do at least as well across the board.

Run the suite:
```bash
pip install pytest
python3 -m pytest
```

## Known limitations (shared with official cards)

A card can't hold negative chances, so when a player is *below* league
average in a category, the opposing average card supplies more of that
outcome than the player actually produced:

- A never-strikes-out batter (Gwynn) will strike out at about half the
  league rate in play — more than he really did.
- A 0-HR season still yields about half the league HR rate.
- An elite control pitcher (Maddux) walks more in play than his real rate.

The generator redistributes what it can (clamped hit deficits are absorbed
by other hit types to preserve batting average and total hits) and **warns
explicitly** about what it can't. The real-card benchmark shows official
cards have exactly the same behavior.

Other simplifications:
- No lefty/righty platoon splits (basic-game style cards).
- Fielding ratings default to average (3) — basic season stats can't
  measure defense well.
- HBP isn't placed on cards (matching all 14 fixture cards).
- Errors/X-chart resolution assumes league-average defense.

## Repository layout

```
app.py                  Flask web app (the dad-friendly interface)
generate_card.py        Command-line interface
stratogen/
  model.py              Card data model, chance accounting, validation
  card_text.py          Parser/serializer for the plain-text card format
  lahman.py             Offline stats + league averages (1871-2025)
  simulate.py           Statistical tester (exact expected rates + Monte Carlo)
  generate.py           Chance targets, clamping/redistribution, card layout
  benchmark.py          Scoring vs the real-card fixtures
  ratings.py            Stealing/running ratings (fitted to real cards)
  render.py             HTML card rendering
data/
  lahman/               Bundled Lahman database (gzipped CSVs)
  real_cards/           Transcribed official cards = ground truth fixtures
tests/                  pytest suite (parser, data, benchmark, app smoke)
```

`STRAT_CARD_MAKER_SPEC_v2.md` is the original project spec, kept for
reference; where it conflicts with this README, the README reflects what
was actually built.

## Updating for a new season

Download the new CSV release from https://sabr.org/lahman-database/ (every
January), gzip `Batting.csv`, `Pitching.csv`, `People.csv`, `Teams.csv`,
`Fielding.csv`, and replace the files in `data/lahman/`.

## Credits

- **Strat-O-Matic** is a registered trademark of the Strat-O-Matic Game
  Company; this is an independent fan project for personal use.
- Card-formula reverse engineering builds on Bruce Bundy's community
  research (somworld.com / cba-bb.net).
- Statistics: the Lahman Baseball Database (SABR), CC BY-SA 3.0.
