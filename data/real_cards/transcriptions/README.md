# JSON card transcriptions

25 additional real Strat-O-Matic cards (13 batters, 12 pitchers),
transcribed from photographs into a richer, lossless JSON schema than the
plain-text fixtures in the parent directory. Provided 2026-06-17.

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
  rates, so advanced-only cards are still benchmarkable without platoon
  generation.)
- **Unofficial cards** (see below) are included but **tolerant**: a failure
  that only they exhibit is allowed.

## Official vs unofficial
Four pitcher cards are flagged `"official": false` (filename `_unofficial`):
Al Orth (1906), Bob Shawkey (1917), Jack Warhop (1914), Bill Zuber (1945).
These are of uncertain provenance — high-quality cards that are probably
genuine (most likely copied or transcribed from real cards), but not
confirmed regulation Strat-O-Matic product, so they may be less reliable
along some dimension. They are advanced-side only.

## Notes / known points
- **Aaron Judge 2024 (basic side)** legitimately under-represents home runs
  (~10 HR chances vs the ~15 his rate implies): his extreme HR *and* walk
  totals can't both fit in 108 chances, so the real card trades away HR —
  the kind of compromise real cards make for extreme seasons. The advanced
  side captures his HR rate accurately. Treated as a documented tolerance,
  not a transcription error (confirmed verbatim from the photo).
- **Joe Sewell** is an all-time "SOM Hall of Famer" card (no single season;
  composite stat line) and **Lindy McDaniel** is an official card with only
  its advanced side photographed and no year. Both are parsed and
  structurally validated but excluded from the statistical benchmark (no
  single-season league context).
- The advanced sides carry situational marker glyphs (`◆ ▼ △ Ω`), `?`/`●`
  marks, error/arm/hold/wp/bk ratings, and platoon percentages that the
  generator does not yet model; all are preserved here for future work
  (notably L/R platoon splits and the advanced fielding/strategy charts).
