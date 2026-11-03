# JSON card transcriptions

27 additional real Strat-O-Matic cards (14 batters, 13 pitchers) in a
richer, lossless JSON schema than the plain-text fixtures in the parent
directory. 25 were transcribed from photographs (provided 2026-06-17).
Two more are exact: Carl Yastrzemski 1967 and Don Drysdale 1965, the
advanced cards Strat-O-Matic publishes as HTML text on its Baseball 365
help pages (https://365.strat-o-matic.com/help/hittercard and
/help/pitchercard; `sourceUrl` in each file). 365 prints its own glyphs
(`#` ballpark HR, `>` ballpark single, `$` clutch, `@` ignored by 365);
they stay verbatim in `raw` and are named that way in `markers`, since
their mapping to the printed card's glyphs is unconfirmed. 365 cards
print no season record.

Each physical card has up to two photographed **sides**, one JSON file each
(joined by `cardId`):
- **`3col`** — the *basic* side: one result grid (columns 1-3 for batters,
  4-6 for pitchers) used against any opponent, plus the printed season stat
  record. Maps directly onto our `Card` model.
- **`6col`** — the *advanced* side: two platoon grids (vs LHP/RHP for
  batters, vs LHB/RHB for pitchers) with a printed usage percentage, plus
  extra ratings and situational marker glyphs.

Loaded by `stratogen/card_json.py`, which normalizes the transcription
vocabulary into our canonical `Card` model. The JSON here stays the verbatim
source of truth. Notation is catalogued in `SYMBOLS.md`.

## How these are used in the test suite
- **All sides**: structural validity (each grid is a coherent 108-chance
  card) and full vocabulary coverage of the normalizer.
- **Basic sides** and **percentage-weighted advanced sides**: scored by the
  statistical tester against the player's real Lahman season. (The weighted
  average of the two platoon grids equals the player's overall expected
  rates, so advanced-only cards are benchmarkable against a basic average
  card.)
- **Advanced sides, grid by grid** (tests/test_platoon.py): each grid
  against its own matchup's average opposing grid, with the printed
  percentages and Power labels. This is the bar generated advanced cards
  must clear, and the source of the share-model and Power-rule fits.
- **Unofficial cards** (see below) are held to the same per-card bars but
  left out of the aggregate accuracy guard.
- **Printed stat lines** are cross-checked against Lahman (AB/HR/SO for
  batters, W/L/SO/BB/IP for pitchers), and generated basic cards must stay
  within 0.002 per PA of each real basic side.

## Official vs unofficial
Four pitcher cards are flagged `"official": false` (filename `_unofficial`):
Al Orth (1906), Bob Shawkey (1917), Jack Warhop (1914), Bill Zuber (1945).
These are of uncertain provenance — high-quality cards that are probably
genuine (most likely copied or transcribed from real cards), but not
confirmed regulation Strat-O-Matic product, so they may be less reliable
along some dimension. They are advanced-side only.

## Notes / known points
- **Aaron Judge 2024** under-prints home runs on the basic side (~10 HR
  chances vs the ~15 his rate implies) and strikeouts on both sides
  (scored errors HR .024, SO .030/.033), while his walks fit. It isn't a
  108-chance limit: the generated card fits his HR, BB and SO exactly. It
  is the real card's compromise (confirmed verbatim from the photo), and
  only those categories are tolerated (tests/test_transcriptions.py).
- **Brian Bruney 2008** (34 IP): the combined advanced grids' hit rate is
  tolerated; tiny platoon samples make it noisy.
- **Phil Linz 1963**: the statRecord prints 6 HR, but the card's own SLG
  (.349) and Lahman both say 2; recorded as a known print difference.
- **Joe Sewell** is an all-time "SOM Hall of Famer" card (no single season;
  composite stat line) and **Lindy McDaniel** is an official card with only
  its advanced side photographed and no year. Both are parsed and
  structurally validated but excluded from the statistical benchmark (no
  single-season league context).
- The advanced sides carry situational marker glyphs (`◆ ▼ △ Ω`), `?`/`●`
  marks, and error/arm/hold/wp/bk ratings that the generator does not yet
  model; all are preserved here for future work (notably the advanced
  fielding/strategy charts). The L/R platoon grids, their percentages,
  Power-N/W, `N-HR` and advanced-side HBP are now generated
  (stratogen/platoon.py), and generated advanced cards are benchmarked
  against these (tests/test_platoon.py). The official advanced cards
  print each player's actual split, which is very noisy (Carey 1953: 2
  walk chances vs LHP, 19 vs RHP). The four unofficial cards, made
  without split data, print identical grids; the generator uses
  league-norm splits.
