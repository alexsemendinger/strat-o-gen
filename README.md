# Strat-O-Matic Card Maker

Generate statistically accurate, game-usable Strat-O-Matic baseball cards
for **any player season from 1871 to 2025** — batters and pitchers, every
era, fully offline.

## Quick start

**Windows:** double-click `Start Strat-O-Gen.vbs` (first time: see
[WINDOWS_SETUP.md](WINDOWS_SETUP.md)). The app starts in a minimized window
on the taskbar and your browser opens by itself; close that window to quit.
Starting it again while it runs just opens the browser again.

**Mac / Linux (with [uv](https://docs.astral.sh/uv/) — easiest):**
```bash
uv run app.py        # uv reads the script's dependency metadata and
                     # provisions Flask itself; no venv, no pip
```

**Mac / Linux (plain Python 3.9 or newer):**
```bash
python3 -m pip install flask     # 'python3 -m pip' ensures pip and python3
python3 app.py                   # match; bare 'pip' may be a different Python
```
If pip refuses with an "externally managed environment" error (newer
Homebrew/Debian Pythons; `--user` installs are refused too), use uv above
or a virtual environment:
```bash
python3 -m venv .venv && .venv/bin/python -m pip install flask
.venv/bin/python app.py
```
The app opens your browser once it is ready, at http://localhost:5001 (or
the next free port when another program has 5001). Options: `--port N`
(or `STRATOGEN_PORT=N`) and `--no-browser`.

**Command line:**
```bash
python3 generate_card.py "Willie Mays" 1965
python3 generate_card.py "Nolan Ryan" 1972               # pitchers get pitcher cards
python3 generate_card.py "Babe Ruth" 1918 --pitcher      # choose for a two-way season
python3 generate_card.py "Tom Seaver" 1969 --html seaver.html
python3 generate_card.py "Aaron Judge" 2024 --advanced   # L/R platoon side
python3 generate_card.py "Frank Thomas"                  # lists players, IDs, seasons
python3 generate_card.py --id thomafr04 2000             # pick one by ID
python3 generate_card.py --team NYA --year 1927          # printable team sheet
```

The only dependency is Flask (pure Python — no compilers, no native
libraries, installs cleanly on Windows). Player statistics and league
averages come from the bundled [Lahman database](https://sabr.org/lahman-database/)
(`data/lahman/*.csv.gz`), so no internet connection or scraping is needed.

## What you get

- **Name autocomplete:** start typing and pick the player (career span and
  position shown; "Griffey Jr.", "A.J. Pierzynski" and curly apostrophes
  work). Pitchers default to their pitcher card; two-way seasons (Ruth
  1918, Ohtani) offer both.
- **Both sides of every card.** The basic side: the classic 3-column ×
  11-row grid with d20 splits, baserunning symbols (`SINGLE*`,
  `DOUBLE**`), groundball A/B/C ratings, X-chart chances on pitcher
  cards, stealing/running ratings, one injury result and one max-effort
  lineout per batter card, and the season record. The advanced side
  (`--advanced` on the command line): two full grids vs left- and
  right-handed opponents, each under a banner with its share of plate
  appearances ("28% AGAINST LEFT-HANDED PITCHERS") and, for batters, a
  Power-N/W rating, topped by the advanced ratings (error numbers, arms,
  bunting, hit & run, hold, wp/bk, endurance).
- **An honesty table for each side:** what the card produces over the
  season's plate appearances (batters faced), against a league-average
  opponent, vs. what actually happened (hits, HR, BB, SO, ...; the
  advanced side is share-weighted and includes HBP).
- **Warnings** in plain English whenever the card can't fully capture the
  season (see *Known limitations* below) or the era's data is incomplete.
- **Team sets:** every card for a team-season (see *Team sets*).
- **Printing at real size:** a basic side prints 2.6 in wide (6.7 pt
  type), the advanced side's two grids side by side at 5.2 in; print the
  side shown or both; team sheets print 4 basic sides or 2 advanced sides
  per page (Letter or A4). Keep the browser's print scale at 100%.
- **Downloads:** "Save card" writes a standalone HTML file (both sides,
  printable, with the warnings and honesty tables); "Save card data"
  writes JSON `{"basic": ..., "advanced": ...}`, each side in the
  transcription schema of `data/real_cards/transcriptions` (`3col` with
  its stat record; `6col` from `card_json.advanced_card_to_json`).

Same player + year always produces the same card.

## Team sets

Real Strat-O-Matic is played with whole teams. In the app's **Team set**
tab, pick a season to list its teams (by league, in standings order, with
W-L), then a team: every card on the roster is made in well under a second
and shown as a grid (basic or advanced sides), with **Print sheets** (basic
sides, advanced sides, or both) and **Save team sheet** (a standalone
printable HTML file). Command line:
`python3 generate_card.py --team NYA --year 1927 [--sides basic|advanced|both] [--html FILE]`.

- **Who gets a card:** batters with about 50 plate appearances *for this
  team* over a 154-game season and pitchers with about 20 innings, scaled
  to the schedule (0.32 PA and 0.13 IP per team game, at least 10 PA /
  3 IP). Everyone else is listed under "Left out" with the reason.
- **Pitchers who batted** get only their pitcher card unless they also
  played 15+ games off the mound (Wes Ferrell); two-way players (Ruth
  1918, Ohtani) get both cards.
- **Traded players** use their full-season line, as Strat-O-Matic does;
  their card prints the set's team, and they are labeled in the set.

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
built against their own run environments. Rates are per effective PA
(AB + BB − IBB + HBP + SF); for pitchers that means batters faced less
intentional walks and sacrifice hits (`simulate.pitcher_effective_pa`;
where pitching SH or batters faced weren't recorded, a per-league factor
from the Pitching table stands in). Pitcher cards additionally carry the
standard 30-chance X-chart block (defense-dependent results, yielding
X_SINGLE_RATE = 4.9 singles per 30 with average defense), shrunk
automatically for extreme modern relievers whose strikeouts don't fit or
who allowed fewer hits than the block's own singles. 2B/3B allowed aren't
recorded, so a pitcher's non-HR hits follow the league's 1B/2B/3B mix,
with the X singles taken out of his singles.

This formula was validated against real cards: hand-counting Barry Bonds's
2001 card gives 22 HR / 41 BB / 12 K chances; the formula predicts 21.8 /
40.2 / 12.1. Nolan Ryan's 1972 card carries 47 strikeout chances; the
formula predicts 46.1.

Below 50 PA (or batters faced) a season's rates are blended toward the
league's as if it had 50, so a 1-for-1 cup of coffee doesn't print 108
singles; real cards from 65 PA up match the unblended formula.

Outs are allocated, not drawn: once the hits, walks and strikeouts are
placed, every remaining out piece is assigned a type (batter cards 55%
groundball / 22% flyball / 10% lineout / 12% popout / 1% foulout, pitcher
cards 26/48/10/16/0, as measured on the real cards), a letter (the
player's groundball-A share from his GIDP rate) and a fielder by quota,
so every card realizes its mix. The max-effort lineout and the injury sit
on 1-chance rows (dice 2/12) as on every real card, and `++` goes on
groundball-A results.

## How we know the cards are good

`data/real_cards/` contains transcribed real cards used as ground truth:
14 in a plain-text format (`*.txt`) and 25 more in a richer JSON format
(`transcriptions/`, capturing both the basic and advanced/platoon sides plus
situational symbols — see that directory's README and SYMBOLS.md). The test
suite computes each card's **exact** expected outcome rates (no simulation
noise — the dice probabilities are summed in closed form) against a
league-average opponent and compares them to the player's actual season line:

- Real official basic batter cards land within **.000–.008 of the
  season batting average** (median .004; BA compared on the season's own
  at-bats, so matching hits means matching BA). Extreme seasons cost
  more: the real Aaron Judge 2024 card under-prints his HR (basic side)
  and strikeouts (both sides), though a card can hold all of them — the
  generated one fits HR, BB and SO exactly. That card is tolerated for
  exactly those categories; every other category is held to the bars.
- Generated cards must stay **within 0.002 per PA of the real card in
  every category**: the 14 fixtures (`tests/test_benchmark.py`), the basic
  sides of the JSON cards with a real season
  (`tests/test_transcriptions.py`, one named trade-off: Silvera 1949's
  singles, where his clamped extra-base hits come out of singles to keep
  total hits exact) and the advanced sides (`tests/test_platoon.py`). On
  the fixtures they currently match or beat the real card everywhere.
- That comparison is not neutral: generated cards are built by inverting
  the tester (same X hit rate, average cards, HBP and sacrifice handling),
  so an error in those assumptions counts against the real cards only.
  The tester's own parameters are checked against the real cards: e.g.
  the X hit rate the 11 official pitcher cards imply is 4.2 ± 0.5 per 30,
  so the published 4.9 stays (1.4 standard errors off, short of the 2
  that would justify refitting).
- A deterministic sweep of ~600 random pool seasons (`tests/test_sweep.py`)
  checks validity, layout precision (every category within 0.11 chances
  of its target) and the batter-card conventions beyond the fixtures.
- Unofficial cards (uncertain provenance, probably genuine) are held to
  the same per-card bars, but left out of the aggregate accuracy guard.

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
  0.91× the league share. Mean error vs the real cards: 3.6 points (13
  batters), 4.0 (8 official pitchers).
- **Power N/W**, per batter grid: W below 1.35% HR per PA (capped at 1.35×
  the league rate in low-HR eras), and always when the N formula would
  clamp. Matches 22 of the 26 labels on the real cards. A pitcher grid's
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
  caught-stealing rates vs same-position/same-season peers in comparable
  leagues (AL+NL together from 1901; each Negro or 19th-century league on
  its own), blended over the prior two seasons and shrunk for small
  samples. Pitchers' range is chances per nine innings, so relievers and
  starters share one scale. Every position played is listed, as on real
  cards. Agreement with every range rating printed on the real cards:
  basic sides (14 fixtures + 19 JSON cards) 28/53 exact, 50/53 within ±1;
  advanced sides 16/34 exact, 31/34 within ±1; pitchers 8/10 exact
  (leave-one-out 6/10), all within ±1. Box-score stats can't see range a
  fielder never reaches or scouting judgment (Judge's rf-1, LeMahieu's
  2b-1), and a widened corpus didn't support re-fitting the position
  players' weights (no variant beat the current one leave-one-out).
  Before 1954 the fielding data has no AL/NL corner-outfield split: the
  bundled Appearances table names the spots a player actually played
  (games in left, center and right), and each spot is rated on his
  combined outfield line, so a pre-1954 outfielder carries the same
  rating at every spot he played.
- Baserunning symbols: the `*`/`**` shares are the real cards' means for
  every batter (SINGLE** .33, SINGLE* .19, DOUBLE** .39); isolated power,
  which used to set them, anti-correlates with the real cards' shares.
  GIDP tendency sets the groundball-A (double play) share and speed the
  `++` count. With whole cells and only a few hit cells per category, a
  card's realized `*`/`**` mix only approximates the shares.
- Stealing ratings cap at A for seasons where caught-stealing wasn't
  tracked (mostly pre-1951): success rate is unknowable, so volume alone
  decides and the card carries a warning. AA requires a measured elite
  rate. Where stolen bases weren't recorded at all (NL 1876-85, AA
  1882-85, UA 1884) stealing is the neutral C. 18/20 exact on the real
  cards (LeMahieu 2021 and Carey 1953 miss by one).
- Running (1-8 .. 1-17) comes from Bill James's speed score, catchers
  3.5 slower: 9/20 exact, 17/20 within ±1 on the real cards (leave-one-
  out 8/20, 15/20). Reputation ratings (Mays 1965's 1-17 at 34) are the
  misses.
- HBP isn't placed on basic cards (official basic cards drop it too: their
  walk chances fit BB alone far better than BB + HBP); advanced batter
  grids carry it, as the real advanced cards do. A hit-by-pitch magnet's
  basic card warns how far his on-base % will run low (Ron Hunt 1971:
  .402 → .322 in play).
- X-chart fielders on generated pitcher cards are random (60% grounders);
  every real pitcher card spreads its 30 X chances ss 7 / 2b 6 / 3b 3 /
  c 3 / cf 3 / 1b 2 / lf 2 / p 2 / rf 2. Switching to the real budget
  raises X groundballs about a quarter, which the game engine's
  double-play calibration has to absorb first.
- Errors/X-chart resolution assumes league-average defense.

## Game dynamics are tested too

Per-PA rates aren't the whole game, so `stratogen/game.py` is a
simplified basic-game engine that plays full innings with real
baserunners. It has two layers.

**Card rules.** `*`/`**` advancement (`**` on a single or a double moves
every runner exactly two bases, no further; `*` one base on a single);
the no-asterisk running gamble (d20 vs the rating of the lead runner
already on base, +2 with two outs; the batter-runner never goes);
groundball A = double play, B = force at second with the batter safe,
C = everyone moves up, with an unforced runner on third scoring on A/B
grounders only when they're hit to the middle infield; flyball A = every
runner tags, B = sacrifice fly, C = hold; "into as many outs as
possible" lineouts (a triple play with two on); X chances resolved as
singles, errors, or the batted-ball out they are (DP grounders and sac
flies included; lineout/popout X hold the runners); `N-HR` by the
batter's power rating. The groundball/flyball readings follow the basic
chart as SOM league rule sheets describe it; the official chart isn't
reproduced. Advanced (platoon) cards play too: a batter reads his grid
for the pitcher's throwing hand, a pitcher his grid for the batter's
effective hand (switch hitters bat opposite the pitcher), and a Power-W
batter reads the pitcher's `N-HR` as `SINGLE**`.

**League context.** What cards don't carry is added at each
league-season's own rates, from the Lahman league totals of the Teams,
Pitching and catchers' Fielding tables (`league_context(year, league)`,
cached): hit-by-pitch (taken from out readings, where card outs absorbed
it; advanced batter grids print it themselves); errors (56%
reached-on-error — about 37% of all errors, two-thirds of the ROE,
through the X chart, the rest from ordinary outs — and 44% extra-base
errors on hits; card outs come from AB−H, so they already contain every
ROE and nothing is counted twice); stolen-base attempts and success
scaled by the runner's `stealing-X` letter (multipliers measured from
1951-2024 player-seasons; CS imputed from nearby seasons where it wasn't
recorded); wild pitches, passed balls and balks; sacrifice bunts and
intentional walks (both outside the cards' plate appearances; pre-1931
SH that include sacrifice flies are corrected). Opportunity rates and
the two error/DP shares are small constants calibrated on **training**
league-seasons (every year divisible by 4, 62 of them) and verified on
the 186 **held-out** ones; they were last re-fit after the card changes
(quota-allocated outs, fixed `*`/`**` shares) and the `DOUBLE**` fix.

**Accuracy.** League-average lineups (27 independently laid-out average
batter cards against 4 average pitcher cards, 30,000 half-innings) vs
the real league, per nine innings (27 outs — real games average ~8.9
innings), all 248 AL/NL seasons 1901-2024:

| era | train R sim/real | held-out R sim/real |
|---|---|---|
| 1901-1919 | 1.005 (sd 0.034) | 0.991 (sd 0.042) |
| 1920-1941 | 0.998 (0.018) | 0.998 (0.022) |
| 1942-1960 | 1.010 (0.017) | 1.008 (0.019) |
| 1961-1976 | 1.006 (0.015) | 1.006 (0.020) |
| 1977-1992 | 1.012 (0.014) | 1.019 (0.015) |
| 1993-2009 | 1.009 (0.016) | 1.015 (0.013) |
| 2010-2024 | 0.991 (0.023) | 1.000 (0.020) |
| all | 1.004 (sd 0.022), range 0.951-1.075 | 1.005 (sd 0.026), range 0.922-1.091 |

247 of the 248 seasons land within ±8% (1919 AL is +9%); 98% of the
training and 95% of the held-out seasons are within ±5%. On the held-out
seasons the other rates average 0.99-1.02 of real; SB, CS, HBP, E, WP
and SH are within ±10% in 97-100% of seasons, PB in 90%, GIDP in 92% and
IBB in 83%. Double plays turned run 0.89 of real by design: the engine
turns DP grounders and max-effort lineouts only, not strike-'em-out-
throw-'em-out, liners or flies doubling a runner off, or outfield
assists. Weak spots: the dead-ball era drifts with the year (1901-1907
seasons score up to 8% low, 1914-1919 up to 9% high), sacrifice flies run
~12% high, and balks are noisy.

Before the league layer, the engine scored about 13% below real (sd 6%,
as low as −35%); a 0.75-1.05 band hid the gap. Adding the mechanics one
at a time (runs per 27 outs, 1901-2024 mean, in % of real runs): rule
fixes and card recalibration +1%, HBP +4%, errors +9%, WP/PB/BK +3%,
steals −2% (caught stealing outweighs stolen bases), sacrifice bunts
−2.5%, IBB +1%. In the dead-ball era errors alone are worth +22%.

The test suite pins each base-running rule with unit tests and checks
fifteen sampled seasons (three of them training) for runs within ±9%
per season and no era bias, SB/CS/HBP/E/GIDP/WP/PB/SH near the league's
rates (DP turned near its 0.89 expectation; per-season bands never
tighter than three standard errors of the season's event count), era
ordering, and that symbols, running and stealing ratings measurably move
scoring. League-average advanced cards (`average_advanced_card`, the
league's L/R/switch mix with Power-W batters, against an average lefty
and righty) score within the same ±9% in three sampled seasons. Not
simulated: pickoffs, hit-and-run, outfield arms, and infield-in /
holding decisions.

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
`ratings.py` (see *Known limitations* for their agreement on every real
card; on these advanced sides range is 16/34 exact, 31/34 within 1). The stealing detail (`*2-6,9/- (15-12)`) is parsed
(`parse_stealing_detail`) but not generated: the corpus doesn't pin down
its meaning.

## Repository layout

```
app.py                  Web app (Flask): page, JSON API, quiet launcher
templates/index.html    The page
static/                 Page script (app.js), styles (app.css), icon
generate_card.py        Command-line interface (cards, team sheets)
start_windows.bat       Windows launcher (finds Python, installs Flask once)
Start Strat-O-Gen.vbs   Windows double-click launcher (minimized window)
stratogen/
  service.py            The one card pipeline (web, CLI, team sets): both
                        sides, warnings, honesty tables, team sets, files
  model.py              Card data model, chance accounting, validation
  card_text.py          Parser/serializer for the plain-text card format
  card_json.py          JSON transcriptions: loader (both sides) + export
  lahman.py             Offline stats, league averages, handedness, teams,
                        rosters, name autocomplete (1871-2025)
  simulate.py           Statistical tester (exact expected rates + Monte Carlo)
  platoon.py            Platoon model: matchup rates, splits, shares, Power
  generate.py           Chance targets, clamping/redistribution, card layout
                        (basic cards and advanced platoon grids)
  benchmark.py          Scoring vs the real-card fixtures (both sides)
  game.py               Game engine: innings, baserunners, league running game
  ratings.py            Stealing/running ratings (fitted to real cards)
  fielding.py           Fielding ratings 1-5 (calibrated to real cards)
  advanced_ratings.py   Advanced-side ratings: e, arms, bunt, hold, wp/bk, endurance
  render.py             Card HTML, print CSS, stat formatting, honesty
                        tables, printable sheets
data/
  lahman/               Bundled Lahman database (gzipped CSVs)
  real_cards/           Transcribed real cards = ground truth fixtures
    *.txt               14 cards in the plain-text format
    transcriptions/     25 more in JSON (basic + advanced sides, symbols)
tests/                  pytest suite (parser, data, benchmark, platoon, app,
                        CLI, service)
```

`STRAT_CARD_MAKER_SPEC_v2.md` is the original project spec, kept for
reference; where it conflicts with this README, the README reflects what
was actually built.

## Updating for a new season

Download the new CSV release from https://sabr.org/lahman-database/ (every
January) and copy `Batting.csv`, `Pitching.csv`, `People.csv`,
`Teams.csv`, `Fielding.csv` and `Appearances.csv` into `data/lahman/` —
plain `.csv` files work; no need to gzip (when both `X.csv` and
`X.csv.gz` exist the newer one is read). Appearances names the corner
outfield spots for seasons without split fielding (before 1954).
`FieldingOFsplit.csv` isn't in the CSV release; export it from the Access
(.mdb) release with mdbtools (`mdb-export lahman.mdb FieldingOFsplit`) —
without it the new season's outfielders are still listed at the spots
they played (from Appearances) but rated on their combined outfield line.
The app's year bound updates automatically from the data.

## Credits

- **Strat-O-Matic** is a registered trademark of the Strat-O-Matic Game
  Company; this is an independent fan project for personal use.
- Card-formula reverse engineering builds on Bruce Bundy's community
  research (somworld.com / cba-bb.net).
- Statistics: the Lahman Baseball Database (SABR), CC BY-SA 3.0.
