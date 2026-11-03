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
- HBP isn't placed on cards (matching all 14 fixture cards).
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

## Advanced-side ratings

`stratogen/advanced_ratings.py` computes, from the Lahman data, the extra
ratings printed on the *advanced* side of real cards, each calibrated
against the official JSON transcriptions (the four unofficial pitchers are
weak evidence only; the Sewell HOF composite and the undated McDaniel are
excluded). Entry points: `advanced_batter_ratings` /
`advanced_batter_header_lines` and `advanced_pitcher_ratings` /
`advanced_pitcher_header_lines`, producing lines like `cf-1(+2) e7`,
`c-3(0) e1, T-1-7(pb-4)`, `bunting-D`, `hit & run-C`, `pitcher-2 e15`,
`starter(6) relief(3)/N`, `hold -4`, `wp-18`, `bk-4`. Not yet wired into
card generation. Agreement below is with the official cards and is
enforced by `tests/test_advanced_ratings.py`; "LOO" = leave-one-out.

| Rating | Basis | Agreement |
|---|---|---|
| Error `eN` (fielders) | Errors per full game × season length (154/162): an absolute rate, not peer-relative. Cameo positions pool two prior seasons, then are floored at 2× the league rate; catchers net out 0.055 throwing errors per steal attempt | 11/19 exact, 16/19 within 1, all within 3 |
| Error `eN` (pitchers) | Errors per 9 IP × season length | 7/7 exact (unofficial 4/4 within 1) |
| Outfield arm `(±N)` | Assists vs expectation, standardized among the season's regular outfielders (lower = stronger) | 2/6 exact, 4/6 within 1 (LOO 1/6, 4/6) |
| Catcher arm `c-N(±N)` | Caught-stealing % vs league (assists when steals weren't recorded) | 1/2 exact, 2/2 within 1 |
| Catcher `T-1-N` | 7 + 2 × arm — **not grounded**, meaning unconfirmed | 1/2 exact |
| Passed balls `pb-N` | Passed balls per season ÷ 4 | 2/2 exact |
| Bunting A-D | Sacrifice hits vs league expectation (+3 pseudo-bunts) | 12/12 exact (LOO 9/12, 12/12 within 1) |
| Hit & run A-D | Strikeout rate vs league (contact) | 12/12 exact (LOO 11/12, 12/12 within 1); A cut unfitted |
| Pitcher `wp-N` | Wild pitches per 216 IP | 6/7 exact, 7/7 within 1 |
| Pitcher `bk-N` | Balks per 300 IP | 6/7 exact, 7/7 within 1 |
| Pitcher `hold ±N` | **No Lahman basis** (no steals are charged to pitchers): handedness prior, LHP −3 / RHP 0 | 3/7 exact, 4/7 within 1 (LOO 2/7, 4/7) |
| Pitcher bunting | Own sacrifice bunts vs pitchers' league rate; no plate appearances → C | 7/7 exact |
| `starter(N)` | Estimated innings per start, shrunk toward a spot-starter prior | 5/5 exact (LOO 3/5, 5/5 within 1) |
| `relief(N)` | Innings per relief outing; pitchers who also start get ⌈starter/2⌉ | 5/5 exact |
| `relief(N)/X` suffix | Inferred closer rating: N without saves, else ⌊1.7 ln SV⌋ — **weakly grounded** | 5/5 exact (one card constrains it) |

Range (1-5), stealing and running come from `fielding.py` and
`ratings.py` unchanged. On these twelve advanced batter cards they score
range 11/27 exact (24/27 within 1), stealing 10/12, running only 3/12 —
the running formula predates these cards and is the next calibration
target. The stealing detail (`*2-6,9/- (15-12)`) is parsed
(`parse_stealing_detail`) but not generated: the corpus doesn't pin down
its meaning.

## Repository layout

```
app.py                  Flask web app (simple web interface)
generate_card.py        Command-line interface
stratogen/
  model.py              Card data model, chance accounting, validation
  card_text.py          Parser/serializer for the plain-text card format
  card_json.py          Loader for the JSON transcriptions (both sides)
  lahman.py             Offline stats + league averages (1871-2025)
  simulate.py           Statistical tester (exact expected rates + Monte Carlo)
  generate.py           Chance targets, clamping/redistribution, card layout
  benchmark.py          Scoring vs the real-card fixtures
  game.py               Simplified game engine (innings, baserunners)
  ratings.py            Stealing/running ratings (fitted to real cards)
  fielding.py           Fielding ratings 1-5 (calibrated to real cards)
  advanced_ratings.py   Advanced-side ratings: e, arms, bunt, hold, wp/bk, endurance
  render.py             HTML card rendering
data/
  lahman/               Bundled Lahman database (gzipped CSVs)
  real_cards/           Transcribed real cards = ground truth fixtures
    *.txt               14 cards in the plain-text format
    transcriptions/     25 more in JSON (basic + advanced sides, symbols)
tests/                  pytest suite (parser, data, benchmark, app smoke)
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
