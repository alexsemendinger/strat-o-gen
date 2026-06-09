# Real Strat-O-Matic card transcriptions

Ground-truth fixtures for validating the card generator. Each `.txt` file is a
verbatim transcription of a (believed-genuine) Strat-O-Matic card, sourced from
card images found via Google Images (provided 2026-06-09). These are the best
available ground truth, but individual cards may contain transcription or
source errors — if one card consistently fails statistical tests that the
others pass, suspect the card data before suspecting the code.

## File format

- Player name on the first line, then position/rating lines, then team.
- `Column N` headers (1-3 for batters, 4-6 for pitchers), each with rows for
  dice sums 2-12.
- An entry may be split by a d20 roll, written as alternating outcome lines and
  range lines (e.g. `HOMERUN` / `1-12` / `DOUBLE` / `13-20`).
- Continuation lines are indented two spaces.
- A `YEAR BATTING RECORD` / `YEAR PITCHING RECORD` section at the bottom lists
  the season stat line printed on the card.

These files are parsed by `stratogen/card_text.py`; the test suite verifies
every file parses into a structurally valid card (each column's d20 ranges
cover 1-20 with no gaps/overlaps, rows 2-12 all present).

## Inventory

| File | Type | Notes |
|------|------|-------|
| `bonds_2001.txt` | batter | Barry Bonds 2001 (73 HR season) |
| `carter_1975.txt` | batter | Gary Carter 1975 |
| `cespedes_2016.txt` | batter | Yoenis Cespedes 2016 |
| `dawson_1977.txt` | batter | Andre Dawson 1977 |
| `foster_1971.txt` | batter | George Foster 1971 |
| `mays_1965.txt` | batter | Willie Mays 1965 (partial stat line; no BB/SO splits beyond those printed) |
| `murphy_1976.txt` | batter | Dale Murphy 1976 — tiny sample (65 AB), useful edge case |
| `murray_1977.txt` | batter | Eddie Murray 1977 (rookie year) |
| `posnanski_2014.txt` | batter | "Joe Posnanski" — promotional/custom card with a fictional stat line (.390, 2014 KC). Presumably made with SOM's real card process, so still usable as card-vs-printed-stats ground truth. |
| `raines_hero.txt` | batter | Tim Raines "SOM Baseball Hero" commemorative; no year printed and the stat line doesn't exactly match any single real season. Treat with extra suspicion. |
| `colon_2016.txt` | pitcher | Bartolo Colon 2016 |
| `kirby_1975.txt` | pitcher | Clay Kirby 1975. The header reads "2 pitcher-starter"; if that leading 2 is a fielding rating it disagrees with his stats (3 E in 19 chances in 1975, 10 E in 1974) — either a generous official rating or the digit means something else. Treated as a known outlier in `tests/test_fielding.py`. |
| `ryan_1972.txt` | pitcher | Nolan Ryan 1972 (157 BB, 329 SO) |
| `seaver_1969.txt` | pitcher | Tom Seaver 1969 |

## Notation observed on these cards

- `SINGLE*` / `SINGLE**`, `DOUBLE**`: baserunner-advancement variants.
- `groundball (ss)A++` etc.: out, fielded by position, letter = double-play
  rating; `++` is an advancement modifier on the out.
- `lineout (2b) into as many outs as possible`: maximum double/triple play.
- `plus injury`: injury roll attached to the result.
- Pitcher cards: capitalized `GROUNDBALL (2B) X` / `FLYBALL (LF) X` are
  X-chart fielding chances (resolution depends on the fielder's rating);
  `CATCHER'S CARD X` defers to the catcher's fielding card.
- Batter columns are 1-3, pitcher columns are 4-6 (white die 1-3 reads the
  batter card, 4-6 the pitcher card).
