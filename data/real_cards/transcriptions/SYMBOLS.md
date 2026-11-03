# Card notation seen in the transcriptions

A catalogue of every symbol, suffix, and header token that appears in these
JSON transcriptions, with what we know and what we don't. The JSON captures
all of it verbatim; the generator currently *models* only the subset noted
below. The rest is recorded so we can add support later (some of it will be
explained by the Advanced Fielding Chart / Advanced Strategy Chart photos,
to be transcribed separately).

## Result resolution classes (well understood)
- `A` / `B` / `C` after a batted ball — resolve on the strategy chart's
  GROUNDBALLS / FLYBALLS A-B-C tables. Roughly: groundball-A = double-play
  ball, B = productive out, C = runners hold; flyball-A = deep (tag from
  2nd/3rd), B = medium (tag from 3rd), C = shallow. **Modeled** (chances +
  the game-dynamics engine).
- `X` after a batted ball (e.g. `GB (ss) X`, `FLY (cf) X`) — resolve on the
  **fielding chart** for the fielder in parentheses; outcome depends on that
  fielder's 1-5 rating. **Modeled** as a defense-resolved chance (league-avg
  defense in the tester).
- `CATCHER'S CARD X` / `CATCH-X` — defer to the catcher's fielding card.
  Treated as an X-chance.

## Advancement / hit modifiers (understood)
- `*` after a hit — runners advance one extra base (single = +1, the batter
  holds). **Modeled** (symbols + engine).
- `**` — runners advance two bases. **Modeled.**
- `++` after a groundball (e.g. `groundball (2b) A++`) — with a runner held
  or the infield in, becomes a `SINGLE**`; otherwise an ordinary out.
  **Modeled** (placed by speed; the engine treats it as an out in the
  default situation).
- `+` (e.g. `gb (ss) A+`) — a milder advancement modifier than `++`.
  Recorded; treated as an ordinary out for rates. Not separately modeled.
- `max` (e.g. `lo (3b) max`) — "into as many outs as possible" (double/triple
  play). **Modeled** as a max-DP lineout.
- `N-HR` — how advanced pitcher grids print home runs: a homer for a
  Power-N batter, a `SINGLE**` for a Power-W batter (Advanced rules, via
  secondary sources). **Modeled**: generated advanced pitcher grids print
  `N-HR`, `simulate.combined_rates(batter_power="W")` reads them as
  singles, and their count is amplified for the share of Power-W hitters
  (see the README's *Advanced (platoon) cards*). Kept as `N-HR` on import.

## Situational marker glyphs (inferred; recorded, not modeled)
These print *before the roll number* on the advanced (6col) side, attached to
a cell that has a normal result **plus** an alternate d20 split. Our reading
(consistent with the data: the alternate almost always turns contact into a
single) is that they are **situational/clutch alternate readings** — the
normal result applies by default, the alternate fires under a specific
managerial situation (hit-and-run, runners going, infield in, etc.). The
generator uses the default result and preserves the alternate verbatim in
the JSON. Exact trigger per glyph is **unconfirmed**:
- `◆` diamond
- `▼` downTriangle
- `△` upTriangle
- `Ω` omega

## Other cell marks (recorded, not modeled)
- `●` bullet — after some `strikeout` / `popout` results. Meaning unconfirmed
  (possibly "can't advance"/"sure out" flavor).
- `?` questionMark — after a batted ball (`fly (rf) B?`). Unconfirmed
  (possibly a fielder's-choice / extra-base-doubt flag).
- underlined class letter (recorded as `underline:A` / `underline:C`) —
  unconfirmed; likely a fielding-chart cross-reference nuance.
- lowercase vs CAPITAL batted-ball tokens on the advanced side (`gb` vs `GB`,
  `fly` vs `FLY`) — preserved case-sensitively in the JSON; treated as
  meaningful by the transcriber but the distinction is unconfirmed. We map
  both to the same category.

## Header / rating tokens (mostly modeled)
Modeled tokens are computed by `stratogen/advanced_ratings.py` (formulas,
fits and agreement in its docstrings and the README's "Advanced-side
ratings" section; not yet wired into card generation).
- `e<NN>` (e.g. `e16`, `e0`) per fielding position — error rating (lower =
  surer hands). **Modeled.** It is an absolute rate: about NN errors per
  full season (154/162 games) at the position, so dead-ball fielders carry
  big numbers. Outfielders print one e for all three spots. Small samples
  at a secondary position get a poor rating, not e0 (Linz 2B e41 with no
  errors in 6 games). Pitchers: errors per 9 IP × season length.
- `(+N)` / `(-N)` next to the first outfield position (e.g. `cf-3(-4)`) —
  outfield **throwing arm**, lower = stronger (Combs +3, Judge -4).
  **Modeled** from assists, loosely: strong arms that deter runners are
  invisible in box scores.
- Catcher `c-3(0) e1,T-1-7(pb-4)` — `(0)` catcher arm (lower = stronger;
  **modeled** from caught-stealing %), `e1` error rating (**modeled**),
  `pb-4` passed balls (**modeled**: ~1 point per 4 PB a season), `T-1-7`
  throwing rating (**emitted but not grounded**: N rises with a weaker arm
  on both cards, Posada arm 0 -> 7, Silvera +1 -> 9; meaning unconfirmed).
- `Power-N` / `Power-W` — N = can hit HRs off the pitcher card; W = those
  become singles. Per platoon group on the advanced side. **Modeled**:
  W below 1.35% HR/PA on the grid (capped at 1.35x the league rate in
  low-HR eras), and whenever the N formula would clamp. Agrees with 20 of
  the 24 labels here; a W grid carries all of the batter's homers itself.
- `bunting-A..E`, `hit & run-A..E` — bunt / hit-and-run ratings.
  **Modeled** (sacrifice-hit rate and strikeout rate vs the league).
- `stealing-(X)` plus a detail like `*3/- (20-6)` — steal rating and its
  detail. The letter is modeled (`ratings.py`); the detail is **parsed**
  (`parse_stealing_detail`) but not generated. Its meaning is unconfirmed:
  the rolls before/after the slash look like jump rolls (`-` = none) and
  the parenthesized pair like d20 safe ranges, but Linz's two roll sets
  partition 2-12 and his 1-for-7 season prints 15 while Judge's 10-for-10
  prints 20. Not printed on the Henderson, Strawberry and Combs cards.
- Pitcher: `hold ±N` (holding runners; negative = better, Pettitte -3) —
  **emitted as a handedness prior only** (Lahman charges no steals to
  pitchers). `wp-NN` (wild pitch) and `bk-N` (balk) — **modeled** (per
  inning). `pitcher-N eNN` — range and error, **modeled**.
  `starter(N)`/`relief(N)` (endurance) — **modeled**. The `/N`, `/0`,
  `/3` after `relief(N)` on modern cards reads as a closer rating (N = no
  saves) — **modeled, inferred meaning**. `#1WL`/`#2WR` (batting card id)
  — not modeled. Trailing `●` after the endurance tokens — unconfirmed,
  not modeled.
- `%` per advanced grid (e.g. "24% AGAINST LEFT-HAND PITCHERS") — share of
  plate appearances vs that handedness. **Modeled**: generated advanced
  cards print it from the league's handedness shares (part-time righty
  hitters platooned toward 50%; pitchers 0.91x the league's left-side
  share). Mean error 3.3 points on the batters here, 3.6 on the official
  pitchers. Also weights the two grids when scoring.
- `HBP` on advanced batter grids — whole chances, 2 x HBP rate x 108, the
  same on both grids, on edge rows (2/12, 3/11, 4/10). **Modeled** on
  generated advanced batter grids (basic sides and pitcher grids carry
  none, as here).
