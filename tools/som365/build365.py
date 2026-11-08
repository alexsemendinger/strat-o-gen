"""Build a 6col transcription JSON from parse365 output + a header spec.

usage: python3 -I build365.py PARSED.json SPEC.json OUT.json
SPEC holds the non-grid fields (cardId, cardType, player, ratings, grids
meta [{vs, percent, power}], source, transcription notes).
"""
import json
import re
import sys

GLYPHS = {"#": "ballparkHR", ">": "ballparkSingle", "$": "clutch", "@": "atSign"}

cols = json.load(open(sys.argv[1], encoding="utf-8"))
spec = json.load(open(sys.argv[2], encoding="utf-8"))


def result_token(res):
    # 365 prints flyball X-chances as FB(x)X; the corpus spelling is FLY (x) X
    m = re.fullmatch(r"FB\((\w+)\)X", res)
    if m:
        return f"FLY ({m.group(1)}) X"
    return res


def cell_json(c):
    parts = c["parts"]
    raw_parts = [f"{r} {g}" if g else r for r, g in parts]
    raw = f"{c['glyph']}{c['roll']}- " + " / ".join(raw_parts)
    if c["injury"]:
        raw += " + injury"
    outcomes = []
    for res, rng in parts:
        tok = result_token(res)
        if rng:
            lo, _, hi = rng.partition("-")
            rr = [int(lo), int(hi or lo)]
        else:
            rr = None
        outcomes.append({"range": rr, "result": tok})
    if c["injury"]:
        assert len(outcomes) == 1
        outcomes[0]["result"] += " plus injury"
    cell = {"roll": c["roll"], "raw": raw, "outcomes": outcomes}
    markers = []
    if c["glyph"]:
        markers.append(GLYPHS[c["glyph"]])
    if any(r.endswith("?") for r, _ in parts):
        markers.append("questionMark")
    if markers:
        cell["markers"] = markers
    return cell


first = 1 if spec["cardType"] == "batter" else 4
grids = []
for gi, meta in enumerate(spec["gridsMeta"]):
    g = dict(meta)
    g["columns"] = [
        {"col": first + k, "cells": [cell_json(c) for c in cols[gi * 3 + k]]}
        for k in range(3)]
    grids.append(g)

out = {
    "cardId": spec["cardId"],
    "sourceImage": None,
    "sourceUrl": spec["sourceUrl"],
    "cardType": spec["cardType"],
    "side": "6col",
    "official": spec["official"],
    "player": spec["player"],
    "ratings": spec["ratings"],
    "grids": grids,
    "statRecord": None,
    "transcription": spec["transcription"],
}
with open(sys.argv[3], "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
    f.write("\n")
print("wrote", sys.argv[3])
