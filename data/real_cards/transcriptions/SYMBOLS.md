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
- `N-HR` — ballpark-dependent home run (homer in some parks, out/lesser hit
  in others). Recorded; counted as a home run for rates. Park effects not
  modeled.

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

## Header / rating tokens (partially modeled)
- `e<NN>` (e.g. `e16`, `e0`) per fielding position — error rating (lower =
  surer hands). **Not yet modeled** (we emit a 1-5 fielding rating only).
- `(+N)` / `(-N)` next to an outfield rating (e.g. `cf-3(-4)`) — outfield
  **throwing arm** rating. Not modeled.
- `Power-N` / `Power-W` — N = can hit HRs off the pitcher card; W = those
  become singles. Per platoon group on the advanced side. Not yet modeled
  (we don't yet special-case weak power).
- `bunting-A..E`, `hit & run-A..E` — bunt / hit-and-run ratings. Not modeled.
- `stealing-(X)` plus a detail like `*3/- (20-6)` — steal rating and its
  lead/secondary detail. We model the letter only.
- Pitcher: `hold ±N` (holding runners), `wp-NN` (wild pitch), `bk-N` (balk),
  `T-1-7-9` / "T ratings" (throwing), `#1WL`/`#2WR` (batting card id),
  `starter(N)`/`relief(N)` (rest/usage). Not modeled.
- `%` per advanced grid (e.g. "24% AGAINST LEFT-HAND PITCHERS") — share of
  plate appearances vs that handedness. Used to weight the two platoon grids
  when computing combined rates for benchmarking; full platoon **card
  generation** is not implemented.
