"""Auxiliary card ratings (stealing, running, header lines).

Fitted to the ratings printed on the dated real batter cards (the
plain-text fixtures and the JSON transcriptions; tests/test_ratings.py).
Stealing thresholds are heuristics on steal volume and success (Raines
60/9 SB -> AA, Dawson 21/7 -> A, Bonds 13/3 -> B, Mays 9/4 -> C, Cespedes
3/1 -> D, Murphy 0 -> E; see stealing_rating). Running comes from Bill
James's speed score. Official formulas are proprietary.
"""

from __future__ import annotations


def stealing_rating(sb: int, cs: int, cs_missing: bool = False,
                   sb_missing: bool = False) -> str:
    """Stealing letter rating (AA best ... E worst).

    When caught-stealing wasn't tracked (most seasons before 1951),
    success rate is unknowable and rating purely on SB/(SB+0) would hand
    every high-volume runner a perfect record. Instead, volume alone sets
    the rating, capped at A: AA is reserved for runners with a *measured*
    elite success rate. When stolen bases weren't recorded at all (NL
    1876-85, AA 1882-85, UA 1884) the rating is the neutral C, not E.

    Fitted on the dated real batter cards: C takes steals plus ten times
    the success rate of at least 12 (Harper 2015's 6-for-10 and Carter
    1975's 5-for-7 are C, Virdon 1958's 5-for-8 and LeMahieu 2021's 4-for-6
    D; any 7 steals at a 50% rate qualify); D takes 2 (Howard 1971's 1-for-1
    and Virdon 1963's 1-for-3 are E). 45/48 exact, all within one grade;
    the misses are Carey 1953 (a 2-for-3 cameo printed C), Linz 1963
    (1-for-7 printed D) and Conor Jackson 2008 (10-for-12 printed C, where
    Judge 2024's 10-for-10 prints B).
    """
    if sb_missing:
        return "C"
    if cs_missing and cs == 0:
        if sb >= 50:
            return "A"
        if sb >= 20:
            return "B"
        if sb >= 7:
            return "C"
        if sb >= 2:
            return "D"
        return "E"
    attempts = sb + cs
    rate = sb / attempts if attempts else 0.0
    if sb >= 40 and rate >= 0.80:
        return "AA"
    if sb >= 20 and rate >= 0.70:
        return "A"
    if sb >= 10 and rate >= 0.60:
        return "B"
    if sb + 10.0 * rate >= 12.0:
        return "C"
    if sb >= 2:
        return "D"
    return "E"


# running 1-N = round(RUNNING_BASE + RUNNING_PER_SPEED x speed score
# + RUNNING_CATCHER if a catcher), clamped to the printed 1-8 .. 1-17.
RUNNING_BASE = 10.5
RUNNING_PER_SPEED = 0.8
RUNNING_CATCHER = -3.5
RUNNING_RANGE = (8, 17)


def speed_score(stats: dict) -> float:
    """Bill James's speed score (0-10), from the components the season
    recorded: stolen-base success (needs CS), steal attempts per time on
    first, triples per ball in play, runs scored per time on base, and
    (rarely grounding into double plays) GIDP per ball in play. Without
    stolen-base data the steal components are left out."""
    missing = set(stats.get("missing") or [])

    def g(key):
        return stats.get(key, 0) or 0

    singles = g("H") - g("2B") - g("3B") - g("HR")
    on_first = max(1, singles + g("BB") + g("HBP"))
    in_play = max(1, g("AB") - g("HR") - g("SO"))
    parts = []
    if "SB" not in missing:
        sb, cs = g("SB"), g("CS")
        attempts = sb + cs
        if "CS" not in missing:
            parts.append(((sb + 3) / (sb + cs + 7) - 0.4) * 20)
        else:
            attempts = sb * 1.4   # typical caught-stealing share
        parts.append((attempts / on_first) ** 0.5 / 0.07)
    parts.append(g("3B") / in_play / 0.0016)
    on_base = max(1, g("H") + g("BB") + g("HBP") - g("HR"))
    parts.append(((g("R") - g("HR")) / on_base - 0.1) / 0.04)
    if "GIDP" not in missing:
        parts.append((0.063 - g("GIDP") / in_play) / 0.007)
    parts = [max(0.0, min(10.0, x)) for x in parts]
    return sum(parts) / len(parts)


def running_rating(stats: dict, catcher: bool = False) -> int:
    """Running speed 1-N (higher = faster), printed as 'running 1-N'.

    round(10.5 + 0.8 x speed_score - 3.5 if a catcher), clamped to 8..17.
    Fitted (two coefficients plus the catcher term, then rounded) on the
    20 dated real batter cards — the 8 plain-text fixtures and the 12
    JSON transcriptions: 9/20 exact, 17/20 within one, mean error 0.85;
    leave-one-out (refitting without each card) 8/20 exact, 15/20 within
    one, mean error 1.00. The stolen-base/triples heuristic it replaces
    scored 6/20, 12/20, 1.45 and could never print 8 or 9. Catchers are
    slow beyond what their line shows (Posada 9, Silvera 8). Outliers:
    Mays 1965 (card 17, a 34-year-old's 9 steals: 14 here, a reputation
    rating) and Pipp 1921 (card 12, 17 triples: 16 here).
    """
    score = RUNNING_BASE + RUNNING_PER_SPEED * speed_score(stats)
    if catcher:
        score += RUNNING_CATCHER
    lo, hi = RUNNING_RANGE
    return max(lo, min(hi, int(score + 0.5)))


_POS_NAMES = {"P": "pitcher", "C": "catcher", "1B": "1st base",
              "2B": "2nd base", "3B": "3rd base", "SS": "shortstop",
              "LF": "leftfield", "CF": "centerfield", "RF": "rightfield",
              "OF": "outfield", "DH": "dh"}


def batter_header_lines(stats: dict,
                        position_ratings: list[tuple[str, int, int]],
                        ) -> list[str]:
    """Rating lines under the player name, in the printed card style.

    `position_ratings` is [(position, fielding rating 1-5, games)], e.g.
    from stratogen.fielding.position_ratings(). Without it, positions are
    omitted entirely rather than guessed.
    """
    lines = []
    for pos, rating, _games in position_ratings:
        lines.append(f"{_POS_NAMES.get(pos, pos.lower())}-{rating}")
    if not lines:
        lines.append("dh")
    missing = stats.get("missing") or []
    steal = stealing_rating(stats.get("SB", 0) or 0, stats.get("CS", 0) or 0,
                            cs_missing="CS" in missing,
                            sb_missing="SB" in missing)
    lines.append(f"stealing-{steal}")
    catcher = bool(position_ratings) and position_ratings[0][0] == "C"
    lines.append(f"running 1-{running_rating(stats, catcher=catcher)}")
    return lines


# A pitcher needs this many starts for a (secondary) starter role: Mendoza
# 2001's two starts print 'relief starter', Bruney 2008's one prints
# 'relief' only. Shared with advanced_ratings' starter(N).
STARTER_MIN_GS = 2


def pitcher_header_lines(stats: dict, fielding_rating: int = 3) -> list[str]:
    games = stats.get("G", 0) or 0
    starts = stats.get("GS", 0) or 0
    role = []
    if starts >= max(1, games // 2):
        role.append("starter")
        if games - starts >= 5:
            role.append("relief")
    else:
        role.append("relief")
        if starts >= STARTER_MIN_GS:
            role.append("starter")
    return [f"pitcher-{fielding_rating}"] + role
