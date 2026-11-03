# Importing Strat-O-Matic 365 card pages

Strat-O-Matic Baseball 365 renders each card's advanced side as HTML text,
so a saved 365 card page converts to an exact corpus file — no photo
transcription errors. These scripts produced
`data/real_cards/transcriptions/som_batter_yastrzemski-carl_1967_6col.json`
and `som_pitcher_drysdale-don_1965_6col.json` from the public help pages
(https://365.strat-o-matic.com/help/hittercard, /help/pitchercard). Player
card pages need a 365 login; a page saved from a logged-in browser
("Save Page As… → HTML only") works the same way.

```bash
python3 -I tools/som365/parse365.py PAGE.html parsed.json      # first read (table structure)
python3 -I tools/som365/reread365.py PAGE.html parsed.json     # second, independent read; must report 0 differences
python3 -I tools/som365/build365.py parsed.json SPEC.json OUT.json
```

`SPEC.json` holds the fields that aren't in the grid (cardId, cardType,
player, ratings, per-grid `{vs, percent, power}`, source URL, notes); see
`examples/`. 365 glyphs are kept verbatim in `raw` and named in `markers`
(`#` ballparkHR, `>` ballparkSingle, `$` clutch, `@` atSign). Put the
output in `data/real_cards/transcriptions/`, then update the inventory in
that directory's README and the count pins in `tests/test_transcriptions.py`
and `tests/test_card_text.py`.

These are working scripts from the import, not a polished tool: the HTML
layout they parse is 365's as of 2026, and the share/power/ratings in the
spec are typed by hand from the page header.
