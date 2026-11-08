"""Print the inventory table of data/real_cards/transcriptions/ (Markdown).

Run from the repository root and paste the output over the "Inventory"
section of data/real_cards/transcriptions/README.md:

    python3 tools/real_cards_inventory.py
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTIONS = ROOT / "data" / "real_cards" / "transcriptions"

_BLOGS = {
    "thoughtsandsox": "Thoughts and Sox blog (Wayback)",
    "rangerscards": "rangerscards blog (Wayback)",
    "cary333": "cary333 blog (Wayback)",
    "opinionofkingman": "Kingman blog (Wayback)",
}


def source_label(url: str) -> str:
    """A short human label for a card's sourceUrl."""
    if not url:
        return "photo provided 2026-06-17"
    for key, label in _BLOGS.items():
        if key in url:
            return label
    if "strat-digital-museum" in url:
        issue = re.search(r"Issue\+?(\d+)", url)
        return (f"STRAT FAN #{issue.group(1)} facsimile (SOM Digital Museum)"
                if issue else "SOM Digital Museum")
    if "365.strat-o-matic.com" in url:
        return "Baseball 365 help page (exact HTML)"
    if "talkshow" in url or "talk-show" in url or "the_talk_show" in url:
        when = re.search(r"talkshow(\d\d)(\d\d)\.htm", url)
        label = "SOM 'Talk Show' column"
        if when:
            label += f", {when.group(1)}/20{when.group(2)}"
        return label + (" (Wayback)" if "web.archive.org" in url else "")
    m = re.search(r"announcements/([^/]+)/", url)
    if m:
        return f"SOM announcement: {m.group(1)}"
    if "wp-json/wp/v2/media" in url:
        return "SOM product photo (media library)"
    if "imgur" in url:
        return "imgur"
    if "web.archive.org" in url:
        host = re.search(r"web\.archive\.org/web/\d+[a-z_]*/(?:https?://)?([^/]+)", url)
        return f"{host.group(1) if host else 'archived page'} (Wayback)"
    host = re.search(r"https?://([^/]+)", url)
    return host.group(1) if host else url


def main() -> int:
    cards: dict[str, dict] = defaultdict(lambda: {"sides": [], "sources": set()})
    for path in sorted(TRANSCRIPTIONS.glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        c = cards[d["cardId"]]
        c["sides"].append(d["side"])
        c["name"] = d["player"]["name"]
        c["type"] = d["cardType"]
        c["official"] = d.get("official", True)
        c["sources"].add(source_label(d.get("sourceUrl") or ""))
    print("| Card | Type | Sides | Source |")
    print("|---|---|---|---|")
    for cid, c in sorted(cards.items(), key=lambda kv: (kv[1]["type"], kv[0])):
        sides = " + ".join("basic" if s == "3col" else "advanced"
                           for s in sorted(c["sides"]))
        label = f"{c['name']} {cid.split('_', 2)[-1]}"   # year, HOF, 1960-orig
        if not c["official"]:
            label += " (unofficial)"
        print(f"| {label} | {c['type']} | {sides} | {'; '.join(sorted(c['sources']))} |")
    n_sides = sum(len(c["sides"]) for c in cards.values())
    print(f"\n{len(cards)} cards, {n_sides} sides.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
