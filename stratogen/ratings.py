"""Auxiliary card ratings (stealing, running).

Thresholds are heuristics fitted to the ratings printed on the real-card
fixtures (e.g. Raines 60/9 SB -> AA, Dawson 21/7 -> A, Bonds 13/3 -> B,
Mays 9/4 -> C, Cespedes 3/1 -> D, Murphy 0 -> E). Official formulas are
proprietary; these reproduce all nine known fixture ratings.
"""

from __future__ import annotations


def stealing_rating(sb: int, cs: int) -> str:
    attempts = sb + cs
    rate = sb / attempts if attempts else 0.0
    if sb >= 40 and rate >= 0.80:
        return "AA"
    if sb >= 20 and rate >= 0.70:
        return "A"
    if sb >= 10 and rate >= 0.60:
        return "B"
    if sb >= 4 or (attempts >= 8 and rate >= 0.50):
        return "C"
    if sb >= 1:
        return "D"
    return "E"


def running_rating(stats: dict) -> int:
    """Running speed 1-N (higher = faster), printed as 'running 1-N'.

    Approximate: derived from stolen-base volume and triples rate.
    Fixtures range 10 (Murphy) to 17 (Raines, Mays).
    """
    sb = stats.get("SB", 0) or 0
    triples = stats.get("3B", 0) or 0
    ab = stats.get("AB", 0) or 1
    score = 12
    if sb >= 40:
        score += 5
    elif sb >= 20:
        score += 3
    elif sb >= 10:
        score += 2
    elif sb >= 4:
        score += 1
    elif sb == 0:
        score -= 2
    if triples / ab >= 0.012:
        score += 1
    return max(8, min(17, score))


def batter_header_lines(stats: dict, positions: list[tuple[str, int]]) -> list[str]:
    """Rating lines under the player name, in the printed card style."""
    pos_names = {"P": "pitcher", "C": "catcher", "1B": "firstbase",
                 "2B": "2nd base", "3B": "3rd base", "SS": "shortstop",
                 "LF": "leftfield", "CF": "centerfield", "RF": "rightfield",
                 "OF": "outfield", "DH": "dh"}
    lines = []
    for pos, _games in positions[:3]:
        name = pos_names.get(pos, pos.lower())
        # Fielding quality isn't derivable from basic stats; use average (3).
        lines.append(f"{name}-3")
    if not lines:
        lines.append("dh")
    lines.append(f"stealing-{stealing_rating(stats.get('SB', 0) or 0, stats.get('CS', 0) or 0)}")
    lines.append(f"running 1-{running_rating(stats)}")
    return lines


def pitcher_header_lines(stats: dict) -> list[str]:
    games = stats.get("G", 0) or 0
    starts = stats.get("GS", 0) or 0
    role = []
    if starts >= max(1, games // 2):
        role.append("starter")
        if games - starts >= 5:
            role.append("relief")
    else:
        role.append("relief")
        if starts >= 5:
            role.append("starter")
    return ["pitcher-3"] + role
