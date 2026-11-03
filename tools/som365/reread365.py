"""Second, independent read of a 365 card: strip all tags, take the text
lines between the column header row and the '(Scroll horizontally' marker,
and re-split them into cells by the 'N-' roll prefixes (a new column starts
whenever the roll number drops back to 2). Compares with parse365 output.

usage: python3 -I reread365.py PAGE.html PARSED.json
"""
import html
import json
import re
import sys

page = open(sys.argv[1], encoding="utf-8", errors="replace").read()
start = page.index("<!-- Name:")
end = page.index("(Scroll horizontally", start)
txt = html.unescape(re.sub(r"<[^>]+>", "\n", page[start:end]))
lines = [l.strip() for l in txt.splitlines() if l.strip()]
# skip header lines up to the 6 column labels
i = 0
while not (lines[i] == "1" or lines[i] == "4"):
    i += 1
i += 6
cols, cur = [], None
prev = 99
for l in lines[i:]:
    m = re.match(r"^([#>$@]?)\s*(\d+)-$", l)
    if m:
        roll = int(m.group(2))
        if roll < prev:
            cols.append([])
        prev = roll
        cols[-1].append({"roll": roll, "glyph": m.group(1), "toks": []})
    else:
        cols[-1][-1]["toks"].append(l)

parsed = json.load(open(sys.argv[2]))
assert len(cols) == 6 == len(parsed), (len(cols), len(parsed))
diffs = 0
for c, (a, b) in enumerate(zip(cols, parsed), 1):
    assert [x["roll"] for x in a] == list(range(2, 13)), [x["roll"] for x in a]
    for x, y in zip(a, b):
        flat = []
        for res, rng in y["parts"]:
            flat.append(res)
            if rng:
                flat.append(rng)
        if y["injury"]:
            flat.append("+ injury")
        if x["glyph"] != y["glyph"] or x["toks"] != flat or x["roll"] != y["roll"]:
            diffs += 1
            print("DIFF col", c, x, y)
print("second read: 6 columns x 11 rolls compared,", diffs, "differences")
