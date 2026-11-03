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
baserunners. It has two layers.

**Card rules.** `*`/`**` advancement; the no-asterisk running gamble
(d20 vs the rating of the lead runner already on base, +2 with two outs;
the batter-runner never goes); groundball A = double play, B = force at
second with the batter safe, C = everyone moves up, with an unforced
runner on third scoring on A/B grounders only when they're hit to the
middle infield; flyball A = every runner tags, B = sacrifice fly, C =
hold; "into as many outs as possible" lineouts (a triple play with two
on); X chances resolved as singles, errors, or the batted-ball out they
are (DP grounders and sac flies included); `N-HR` by the batter's power
rating. The groundball/flyball readings follow the basic chart as SOM
league rule sheets describe it; the official chart isn't reproduced.

**League context.** What cards don't carry is added at each
league-season's own rates, from the Lahman Teams, Pitching and catchers'
Fielding tables (`league_context(year, league)`, cached): hit-by-pitch
(taken from out readings, where card outs absorbed it); errors (70%
reached-on-error — about 40% of all errors through the X chart, the rest
from ordinary outs — and 30% extra-base errors on hits; card outs come
from AB−H, so they already contain every ROE and nothing is counted
twice); stolen-base attempts and success scaled by the runner's
`stealing-X` letter (multipliers measured from 1951-2024 player-seasons;
CS imputed from nearby seasons where it wasn't recorded); wild pitches,
passed balls and balks; sacrifice bunts and intentional walks (both
outside the cards' plate appearances; pre-1931 SH that include sacrifice
flies are corrected). Opportunity rates and the two error/DP shares are
small constants calibrated on **training** league-seasons (every year
divisible by 4, 62 of them) and verified on the 186 **held-out** ones.

**Accuracy.** League-average lineups (27 independently laid-out average
batter cards against 4 average pitcher cards, 30,000 half-innings) vs
the real league, per nine innings (27 outs — real games average ~8.9
innings), all 248 AL/NL seasons 1901-2024:

| era | train R sim/real | held-out R sim/real |
|---|---|---|
| 1901-1919 | 0.996 (sd 0.028) | 0.994 (sd 0.035) |
| 1920-1941 | 1.008 (0.021) | 1.006 (0.026) |
| 1942-1960 | 0.999 (0.020) | 1.005 (0.021) |
| 1961-1976 | 1.006 (0.013) | 1.004 (0.014) |
| 1977-1992 | 1.014 (0.018) | 1.018 (0.018) |
| 1993-2009 | 1.012 (0.012) | 1.012 (0.014) |
| 2010-2024 | 0.991 (0.028) | 1.003 (0.023) |
| all | 1.004, range 0.934-1.051 | 1.006, range 0.926-1.066 |

Every season lands within ±8% (96-97% within ±5%). On the held-out
seasons the other rates average 1.00-1.01 of real; SB, CS, HBP, E, WP
and SH are within ±10% in 97-100% of seasons, PB in 92%, double plays
turned in 87%, IBB in 76% and GIDP in 71%. Weak spots: the AL of
1905-1908 scores 5-7% low, sacrifice flies run 7-10% high, and balks are
noisy.

Before this, the engine had none of the league layer and scored about
13% below real (sd 6%, as low as −35%); a 0.75-1.05 band hid the gap.
Adding the mechanics one at a time (runs per 27 outs, 1901-2024 mean,
in % of real runs): rule fixes and card recalibration +1%, HBP +4%,
errors +9%, WP/PB/BK +3%, steals −2% (caught stealing outweighs stolen
bases), sacrifice bunts −2.5%, IBB +1%. In the dead-ball era errors
alone are worth +22%.

The test suite pins each base-running rule with unit tests and checks
fifteen sampled seasons (three of them training) for runs within ±9%
per season and no era bias, SB/CS/HBP/E/DP/GIDP/WP/PB/SH near the
league's rates, era ordering, and that symbols, running and stealing
ratings measurably move scoring. Not simulated: pickoffs, hit-and-run,
outfield arms, infield-in / holding decisions, and platoon (advanced)
reading — `GameSimulator` takes `grid_selector` and `power_of` hooks for
that.

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
  game.py               Game engine: innings, baserunners, league running game
  ratings.py            Stealing/running ratings (fitted to real cards)
  fielding.py           Fielding ratings 1-5 (calibrated to real cards)
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
