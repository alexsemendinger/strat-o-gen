# JSON card transcriptions

73 more real Strat-O-Matic cards (49 batters, 24 pitchers; 108 sides) in a
richer, lossless JSON schema than the plain-text fixtures in the parent
directory. Sources (`sourceUrl` / `sourceImage` in each file; inventory
below):
- photographs provided 2026-06-17 (the first 25 cards);
- Strat-O-Matic's own published images: card-correction announcements,
  promotional and Hall of Fame product pages, product photos in its media
  library, a 2003 "Talk Show" column (via the Wayback Machine), and two
  1941 cards printed in STRAT FAN magazine (Digital Museum);
- exact text: Carl Yastrzemski 1967 and Don Drysdale 1965, the advanced
  cards Strat-O-Matic publishes as HTML on its Baseball 365 help pages.
  365 prints its own glyphs (`#` ballpark HR, `>` ballpark single, `$`
  clutch, `@` ignored by 365); they stay verbatim in `raw` and are named
  that way in `markers`, since their mapping to the printed card's glyphs
  is unconfirmed. 365 cards print no season record;
- scans on collectors' blogs, archived by the Wayback Machine (Bill
  Virdon's 1955-65 cards, both sides and four original printings, and
  others) and imgur.

Every card was read twice from full-resolution crops and validated: each
grid covers dice 2-12 and the d20 exactly (108 chances), and the printed
record is checked against Lahman.

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
- **Ratings** printed on the cards (stealing, running, fielding, the
  advanced-side ratings) are the truth tables for tests/test_ratings.py and
  tests/test_advanced_ratings.py.
- **Printed stat lines** are cross-checked against Lahman (AB/HR/SO for
  batters, W/L/SO/BB/IP for pitchers), and generated basic cards must stay
  within 0.002 per PA of each real basic side.

## Official vs unofficial
Six cards are flagged `"official": false` (filename `_unofficial`):
- Al Orth (1906), Bob Shawkey (1917), Jack Warhop (1914), Bill Zuber
  (1945): advanced-side-only pitcher cards of uncertain provenance,
  probably genuine but not confirmed regulation product (made without
  split data: both grids identical).
- Joe DiMaggio and Ted Williams (1941): both sides as printed in STRAT
  FAN issue 16 (December 1992). The content is believed to be the
  official cards', but the magazine typeset them (visible slips are kept
  verbatim in `raw`).

## Single-team cards and original printings
- A card printed for one team of a traded player's season names that
  stint (`"stint": "NYN"` in `player`); the benchmark scores it against
  that team's line only (Cespedes 2015 Mets, Reed 2017 Red Sox).
- Some seasons exist in two printings: the modern reissue and the 1960s
  original, which used the rating rules of its day and a different grid.
  Originals are filed as `<name>_<year>-orig` (Virdon 1960, 1961, 1964,
  1965); both are scored, but only the modern printing counts toward the
  ratings truth (Virdon 1960 prints stealing B on the original, C on the
  modern card).

## Notes / known points
- **Aaron Judge 2024** under-prints home runs on the basic side (~10 HR
  chances vs the ~15 his rate implies) and strikeouts on both sides
  (scored errors HR .024, SO .030/.033), while his walks fit. It isn't a
  108-chance limit: the generated card fits his HR, BB and SO exactly. It
  is the real card's compromise (confirmed verbatim from the photo), and
  only those categories are tolerated (tests/test_transcriptions.py).
- **Brian Bruney 2008** (34 IP): the combined advanced grids' hit rate is
  tolerated; tiny platoon samples make it noisy.
- **Aroldis Chapman 2014** struck out 52% of the batters he faced, more
  than a 108-chance card can express when half of all plate appearances
  read the batter's card: the card maxes out (60 strikeouts, 30 X, no
  printed hits) and still implies 38% strikeouts. Its hits and strikeouts
  are tolerated.
- **Randy Choate 2014** (36-IP lefty specialist, 59% vs LHB) and **Wilson
  Ramos 2010** (79 AB, no walks printed): one category each is tolerated.
- **DiMaggio and Williams 1941**: walks run low as if intentional walks,
  which cards leave off and Lahman doesn't record for 1941, were removed;
  DiMaggio's 13 strikeouts are below what the average 1941 pitcher card
  alone implies. Those categories are tolerated.
- **No max-effort lineout**: four advanced grids print none (Bonds 2001
  vs RHP, DiMaggio 1941 vs RHP, Williams 1941 both grids); every other
  batter grid prints exactly one.
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

## Inventory

Regenerate with `python3 tools/real_cards_inventory.py`.

| Card | Type | Sides | Source |
|---|---|---|---|
| Joe Adcock 1957 | batter | advanced | SOM announcement: wsbg-final-gene-abood-world-champion |
| Jose Bautista 2015 | batter | advanced | SOM announcement: simulation-goose-gossage-takes-todays-stars |
| Andrew Benintendi 2022 | batter | basic + advanced | photo provided 2026-06-17 |
| Barry Bonds 2001 | batter | advanced | SOM 'Talk Show' column, 10/2003 (Wayback) |
| Andy Carey 1953 | batter | basic + advanced | photo provided 2026-06-17 |
| Yoenis Cespedes 2015 | batter | advanced | SOM announcement: simulation-goose-gossage-takes-todays-stars |
| Earle Combs 1930 | batter | basic + advanced | photo provided 2026-06-17 |
| Nelson Cruz 2009 | batter | basic | rangerscards blog (Wayback) |
| Andre Dawson HOF | batter | basic | SOM announcement: limited-supply-hall-fame-products |
| Joe DiMaggio 1941 (unofficial) | batter | basic + advanced | STRAT FAN #16 facsimile (SOM Digital Museum) |
| Tony Gwynn HOF | batter | basic | SOM announcement: limited-supply-hall-fame-products |
| Bryce Harper 2015 | batter | advanced | SOM announcement: simulation-goose-gossage-takes-todays-stars |
| Rickey Henderson 1986 | batter | basic + advanced | photo provided 2026-06-17 |
| Frank Howard 1971 | batter | advanced | Kingman blog (Wayback) |
| Conor Jackson 2008 | batter | advanced | SOM product photo (media library) |
| Aaron Judge 2024 | batter | basic + advanced | photo provided 2026-06-17 |
| DJ LeMahieu 2021 | batter | basic + advanced | photo provided 2026-06-17 |
| Phil Linz 1963 | batter | basic + advanced | photo provided 2026-06-17 |
| Eddie Murray HOF | batter | basic | SOM announcement: limited-supply-hall-fame-products |
| Wally Pipp 1921 | batter | basic + advanced | photo provided 2026-06-17 |
| Jorge Posada 2003 | batter | basic + advanced | photo provided 2026-06-17 |
| Kirby Puckett HOF | batter | basic | SOM announcement: limited-supply-hall-fame-products |
| Wilson Ramos 2010 | batter | advanced | SOM announcement: baseball-2010-corrections |
| Earl Rapp 1952 | batter | basic | SOM announcement: 1952-baseball-card-corrections |
| Phil Rizzuto 1949 | batter | basic + advanced | photo provided 2026-06-17 |
| Jarrod Saltalamacchia 2009 | batter | basic | rangerscards blog (Wayback) |
| Billy Sample 1983 | batter | basic | SOM announcement: billy-sample-challenge |
| Joe Sewell HOF | batter | basic + advanced | photo provided 2026-06-17 |
| Charlie Silvera 1949 | batter | basic + advanced | photo provided 2026-06-17 |
| Darryl Strawberry 1985 | batter | basic + advanced | photo provided 2026-06-17 |
| Taylor Teagarden 2009 | batter | basic | rangerscards blog (Wayback) |
| Bill Virdon 1955 | batter | basic + advanced | Thoughts and Sox blog (Wayback) |
| Bill Virdon 1956 | batter | basic + advanced | Thoughts and Sox blog (Wayback) |
| Bill Virdon 1957 | batter | basic | Thoughts and Sox blog (Wayback) |
| Bill Virdon 1958 | batter | basic + advanced | Thoughts and Sox blog (Wayback) |
| Bill Virdon 1959 | batter | basic + advanced | Thoughts and Sox blog (Wayback) |
| Bill Virdon 1960 | batter | basic + advanced | Thoughts and Sox blog (Wayback) |
| Bill Virdon 1960-orig | batter | basic | Thoughts and Sox blog (Wayback) |
| Bill Virdon 1961 | batter | basic + advanced | Thoughts and Sox blog (Wayback) |
| Bill Virdon 1961-orig | batter | basic + advanced | Thoughts and Sox blog (Wayback) |
| Bill Virdon 1962 | batter | basic + advanced | Thoughts and Sox blog (Wayback) |
| Bill Virdon 1963 | batter | basic + advanced | Thoughts and Sox blog (Wayback) |
| Bill Virdon 1964 | batter | basic + advanced | Thoughts and Sox blog (Wayback) |
| Bill Virdon 1964-orig | batter | basic | Thoughts and Sox blog (Wayback) |
| Bill Virdon 1965 | batter | basic + advanced | Thoughts and Sox blog (Wayback) |
| Bill Virdon 1965-orig | batter | basic | Thoughts and Sox blog (Wayback) |
| Bill Wambsganss 1920 | batter | basic | imgur |
| Ted Williams 1941 (unofficial) | batter | basic + advanced | STRAT FAN #16 facsimile (SOM Digital Museum) |
| Carl Yastrzemski 1967 | batter | advanced | Baseball 365 help page (exact HTML) |
| Brian Bruney 2008 | pitcher | basic + advanced | photo provided 2026-06-17 |
| Chris Capuano 2014 | pitcher | basic + advanced | photo provided 2026-06-17 |
| Aroldis Chapman 2014 | pitcher | basic | SOM announcement: 2014-baseball-card-corrections |
| Randy Choate 2014 | pitcher | advanced | SOM product photo (media library) |
| Mike Cuellar 1971 | pitcher | advanced | Kingman blog (Wayback) |
| Don Drysdale 1965 | pitcher | advanced | Baseball 365 help page (exact HTML) |
| Scott Feldman 2009 | pitcher | basic | rangerscards blog (Wayback) |
| Paul Gibson 1994 | pitcher | basic + advanced | photo provided 2026-06-17 |
| Rich Gossage 1982 | pitcher | advanced | SOM announcement: simulation-goose-gossage-takes-todays-stars |
| Eddie Guardado 2009 | pitcher | basic | rangerscards blog (Wayback) |
| Brandon McCarthy 2009 | pitcher | basic | rangerscards blog (Wayback) |
| Lindy McDaniel undated | pitcher | advanced | photo provided 2026-06-17 |
| Ramiro Mendoza 2001 | pitcher | basic + advanced | photo provided 2026-06-17 |
| Steve Mingori 1973 | pitcher | basic + advanced | SOM announcement: 1973-baseball-corrections |
| Zach Monroe 1958 | pitcher | basic + advanced | photo provided 2026-06-17 |
| Al Orth 1906 (unofficial) | pitcher | advanced | photo provided 2026-06-17 |
| Melido Perez 1994 | pitcher | basic + advanced | photo provided 2026-06-17 |
| Andy Pettitte 2012 | pitcher | basic + advanced | photo provided 2026-06-17 |
| Addison Reed 2017 | pitcher | basic | SOM announcement: 2017-baseball-card-corrections |
| Bob Shawkey 1917 (unofficial) | pitcher | advanced | photo provided 2026-06-17 |
| Kevin Slowey 2009 | pitcher | basic | SOM announcement: 2009-and-1977-baseball-corrections |
| Jack Warhop 1914 (unofficial) | pitcher | advanced | photo provided 2026-06-17 |
| Oscar Zamora 1975 | pitcher | basic + advanced | cary333 blog (Wayback) |
| Bill Zuber 1945 (unofficial) | pitcher | advanced | photo provided 2026-06-17 |
