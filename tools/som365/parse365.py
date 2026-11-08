"""Parse a Strat-O-Matic 365 card (HTML help/player page) into grid cells.

First read: walks the six <td class="text9" bgcolor=...> column blocks of the
card table and their nested row tables. Prints a JSON list of 6 columns, each
a list of cells {roll, glyph, parts:[(text, range|None)], injury}.

usage: python3 -I parse365.py PAGE.html OUT.json
"""
import html
import json
import re
import sys

page = open(sys.argv[1], encoding="utf-8", errors="replace").read()
# column blocks: outer td with bgcolor + nested table, up to its </table>
blocks = re.findall(
    r'<td class="text9" bgcolor="#(?:DDEEFF|FFEEEE)">\s*<table[^>]*>(.*?)</table>',
    page, re.S)
assert len(blocks) == 6, len(blocks)


def text(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


cols = []
for b in blocks:
    rows = re.findall(r"<tr>(.*?)</tr>", b, re.S)
    cells = []
    for r in rows:
        tds = [text(t) for t in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        head = tds[0] if tds else ""
        m = re.match(r"^([#>$@]?)\s*(\d+)-$", head)
        if m:
            cells.append({"roll": int(m.group(2)), "glyph": m.group(1),
                          "parts": [], "injury": False})
        elif head:
            raise SystemExit(f"unexpected row head {head!r}")
        body = [t for t in tds[1:] if t != ""]
        if not body:
            continue
        if body == ["+ injury"]:
            cells[-1]["injury"] = True
            continue
        res = body[0]
        rng = body[1] if len(body) > 1 else None
        assert len(body) <= 2, body
        cells[-1]["parts"].append((res, rng))
    cols.append(cells)

json.dump(cols, open(sys.argv[2], "w", encoding="utf-8"), indent=1)
for i, c in enumerate(cols):
    print("col", i + 1, [(x["glyph"] + str(x["roll"]), x["parts"], x["injury"]) for x in c])
